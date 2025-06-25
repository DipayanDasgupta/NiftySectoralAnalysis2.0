# ~/CombinedNiftyNewsApp/app.py
import os
import logging
from flask import Flask, render_template, request, jsonify, session as flask_session
from datetime import datetime, timedelta, timezone
import json
from sqlalchemy.orm import Session

# Project-specific utils
from utils import gemini_utils, sentiment_analyzer, db_crud
from utils.database_models import SessionLocal, create_db_and_tables
# For optional on-demand scraping with news-fetch (which imports selenium):
from utils.newsfetch_lib.google import GoogleSearchNewsURLExtractor # This line triggers the need for selenium
from utils.newsfetch_lib.news import Newspaper
from utils.database_models import ScrapedArticle # For type hinting

import config # Your existing config.py
# from .config import NEWSAPI_ORG_API_KEY as FALLBACK_NEWSAPI_KEY # Likely not needed if `import config` is used

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
# DATABASE_URL is configured in database_models.py using os.environ.get
# app.config['SQLALCHEMY_DATABASE_URL'] = os.environ.get("DATABASE_URL", "sqlite:///./news_data.db") # Not strictly needed here if SessionLocal uses it

# --- Logging Setup ---
# (Your existing logging setup - ensure it's complete)
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d (%(funcName)s)] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "app.log")) # Log to a file in app root
    ]
)
logger = logging.getLogger(__name__) 
logging.getLogger("werkzeug").setLevel(logging.INFO) # Quieter Werkzeug
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("nltk").setLevel(logging.INFO) 
logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(logging.WARNING) # Quieter Selenium
logging.getLogger("undetected_chromedriver").setLevel(logging.WARNING) # Quieter UC
logging.getLogger("utils.newsfetch_lib.google").setLevel(logging.INFO) # Control google.py logs
# ... other library log levels ...


# --- Database ---
def get_db(): 
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Key Management ---
def get_api_keys_from_session_or_config():
    keys = {
        'gemini': flask_session.get('gemini_key_sess', config.GEMINI_API_KEY),
        # 'newsapi': flask_session.get('newsapi_key_sess', config.NEWSAPI_ORG_API_KEY), # If using as fallback
    }
    logger.debug(f"API Keys used - Gemini Set: {bool(keys['gemini'] and keys['gemini'] != 'YOUR_GEMINI_API_KEY_HERE')}")
    return keys

# --- UI Log Helper ---
def setup_local_logger(ui_log_list):
    def append_log_local(message, level='INFO'):
         timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
         level_upper = level.upper()
         entry = {'timestamp': timestamp, 'message': str(message), 'level': level_upper}
         ui_log_list.append(entry)
         if level_upper == 'ERROR': logger.error(f"UI_LOG: {message}")
         elif level_upper == 'WARNING': logger.warning(f"UI_LOG: {message}")
         else: logger.info(f"UI_LOG: {message}")
    return append_log_local

# --- Date Parsing Helper ---
def robust_date_parse(date_str):
     if not date_str: return None
     for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'): # Common date formats
         try:
             return datetime.strptime(date_str, fmt).date()
         except ValueError:
             continue
     logger.warning(f"Could not parse date string from UI: {date_str}")
     return None

# === ROUTES ===
@app.route('/')
def index_page():
    actual_system_today = datetime.now(timezone.utc).date()
    sector_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG
    context = {
        'sector_options': list(sector_config.keys()),
        'news_source_options': ["Local Database (Scraped)"], 
        'system_actual_today': actual_system_today.strftime('%Y-%m-%d'),
        'default_end_date': actual_system_today.strftime('%Y-%m-%d'),
        'sector_stock_config_json': json.dumps({
            sector: list(details.get("stocks", {}).keys()) 
            for sector, details in sector_config.items()
        })
    }
    return render_template('index.html', **context)

@app.route('/api/update-api-keys', methods=['POST'])
def update_api_keys_route():
    data = request.json
    log_updates = []
    if 'gemini_key' in data and data['gemini_key'].strip():
        flask_session['gemini_key_sess'] = data['gemini_key']
        log_updates.append("Gemini key updated in session.")
    # if 'newsapi_key' in data and data['newsapi_key'].strip(): # If using NewsAPI fallback
    #     flask_session['newsapi_key_sess'] = data['newsapi_key']
    #     log_updates.append("NewsAPI key updated in session.")
    
    if not log_updates:
        return jsonify({"message": "No API keys provided to update."})
    logger.info(f"API Keys updated: {'; '.join(log_updates)}")
    return jsonify({"message": "Session API keys processed."})


def process_articles_for_llm(db_articles_list, target_name_for_log, db_session_for_vader_update: Session):
    processed_list = []
    if not db_articles_list:
        return processed_list
    
    for db_art in db_articles_list:
        if not db_art.article_text:
            logger.warning(f"Skipping article for LLM (no text): {db_art.url} for {target_name_for_log}")
            continue

        vader_s = db_art.vader_score
        if vader_s is None: # Calculate and store if not already present
            vader_s = sentiment_analyzer.get_vader_sentiment_score(db_art.article_text)
            # Update the DB with the calculated VADER score
            db_crud.update_article_sentiment_scores(db_session_for_vader_update, article_url=db_art.url, vader_score=vader_s)
        
        processed_list.append({
            'content': db_art.article_text,
            'date': db_art.publication_date.strftime('%Y-%m-%d') if db_art.publication_date else 'N/A',
            'uri': db_art.url,
            'source': db_art.source_domain or 'DB Scraped',
            'vader_score': vader_s, # Now this will be populated
            'db_id': db_art.id 
        })
    return processed_list


@app.route('/api/sector-analysis', methods=['POST'])
def perform_sector_analysis_route():
    form_data = request.json
    logger.info(f"Sector Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db()) # Get DB session
    current_api_keys = get_api_keys_from_session_or_config()
    results_payload = []
    user_facing_errors = []

    selected_sectors_from_form = form_data.get('selected_sectors')
    if not selected_sectors_from_form or not isinstance(selected_sectors_from_form, list) or not selected_sectors_from_form:
        user_facing_errors.append("Please select at least one sector.")
    if not current_api_keys.get('gemini') or current_api_keys['gemini'] == "YOUR_GEMINI_API_KEY_HERE": # Check config.py placeholder
        user_facing_errors.append("Gemini API key is not configured properly.")
    if user_facing_errors:
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    actual_today_server = datetime.now(timezone.utc).date()
    ui_end_date_obj = robust_date_parse(form_data.get('end_date')) or actual_today_server
    lookback = int(form_data.get('sector_lookback', 7))
    max_articles_llm_sector = int(form_data.get('sector_max_articles', 5))
    custom_prompt = form_data.get('sector_custom_prompt', '')

    query_end_date = min(ui_end_date_obj, actual_today_server)
    query_start_date = query_end_date - timedelta(days=lookback - 1) # lookback days inclusive of end_date
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Sector Analysis - Dates: {llm_context_range_str}, Max articles/sector for LLM: {max_articles_llm_sector}", "INFO")

    for sector_name in selected_sectors_from_form:
        append_log_local(f"--- Processing SECTOR: {sector_name} ---", "INFO")
        sector_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
        db_query_keywords_sector = [sector_name] + sector_config.get("newsapi_keywords", [])[:3] # Use newsapi_keywords for DB search
        
        append_log_local(f"Querying DB for sector '{sector_name}' with keywords: {db_query_keywords_sector}", "DEBUG")
        db_sector_articles_raw = db_crud.get_articles_for_analysis(
            db, query_start_date, query_end_date, 
            target_keywords=db_query_keywords_sector,
            limit=max_articles_llm_sector * 3 # Fetch more from DB to have enough for VADER even if LLM count is small
        )

        articles_for_sector_llm_input = process_articles_for_llm(db_sector_articles_raw, sector_name, db)
        
        # Apply VADER to all fetched, then select top N for LLM based on some criteria if needed, or just take first N
        # For now, just trim for LLM
        articles_trimmed_for_llm = articles_for_sector_llm_input[:max_articles_llm_sector]

        current_sector_error = None
        if not articles_trimmed_for_llm: # If even after processing, no articles for LLM
            current_sector_error = f"No relevant articles with text found in DB for sector '{sector_name}' for the period to send to LLM."
            append_log_local(current_sector_error, "WARNING")
        
        sector_gemini_result = None
        # VADER scores are calculated within process_articles_for_llm and attached to items
        # We need an overall VADER score for the articles considered for this sector (could be more than sent to LLM)
        all_vader_scores_for_sector = [art['vader_score'] for art in articles_for_sector_llm_input if art.get('vader_score') is not None]


        if articles_trimmed_for_llm and not current_sector_error: # Only send to LLM if we have articles
            append_log_local(f"Sending {len(articles_trimmed_for_llm)} articles to Gemini for sector '{sector_name}'.", "INFO")
            sector_gemini_result, gemini_err = gemini_utils.analyze_news_with_gemini(
                current_api_keys['gemini'], 
                [art['content'] for art in articles_trimmed_for_llm], 
                sector_name, llm_context_range_str, custom_prompt, append_log_local, target_type="sector"
            )
            if gemini_err: current_sector_error = gemini_err
            
            # Storing overall LLM analysis for the sector (not per article from this sector-level call)
            # Individual article LLM scores would be if each article was analyzed independently by LLM.

        avg_vader_score_for_this_sector_batch = sentiment_analyzer.get_average_vader_score(all_vader_scores_for_sector)
        vader_label_for_this_sector_batch = sentiment_analyzer.get_sentiment_label_from_score(avg_vader_score_for_this_sector_batch)

        results_payload.append({
            'sector_name': sector_name,
            'llm_context_date_range': llm_context_range_str,
            'num_articles_for_llm_sector': len(articles_trimmed_for_llm),
            'gemini_analysis_sector': sector_gemini_result,
            'error_message_sector': current_sector_error,
            'avg_vader_score_sector': avg_vader_score_for_this_sector_batch,
            'vader_sentiment_label_sector': vader_label_for_this_sector_batch,
            'constituent_stocks': list(sector_config.get("stocks", {}).keys())
        })
    
    append_log_local("--- Sector analysis processing finished. ---", "INFO")
    return jsonify({'error': False, 'messages': ["Sector analysis complete."], 'results': results_payload, 'logs': ui_log_messages})


@app.route('/api/stock-analysis', methods=['POST'])
def perform_stock_analysis_route():
    form_data = request.json
    logger.info(f"Stock Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    stock_analysis_results_payload = []
    user_facing_errors = []

    sector_name = form_data.get('sector_name')
    selected_stocks_from_form = form_data.get('selected_stocks')
    
    if not sector_name or not selected_stocks_from_form or not isinstance(selected_stocks_from_form, list) or not selected_stocks_from_form:
        user_facing_errors.append("Sector name and at least one stock must be provided.")
    if not current_api_keys.get('gemini') or current_api_keys['gemini'] == "YOUR_GEMINI_API_KEY_HERE":
        user_facing_errors.append("Gemini API key is not configured properly.")
    if user_facing_errors:
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    actual_today_server = datetime.now(timezone.utc).date()
    ui_end_date_obj = robust_date_parse(form_data.get('end_date')) or actual_today_server
    lookback = int(form_data.get('lookback_days', 7)) 
    max_articles_llm_stock = int(form_data.get('stock_max_articles', 3))
    custom_prompt = form_data.get('custom_prompt', '')

    query_end_date = min(ui_end_date_obj, actual_today_server)
    query_start_date = query_end_date - timedelta(days=lookback-1)
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Stock analysis for {llm_context_range_str}, Max articles/stock for LLM: {max_articles_llm_stock}", "INFO")
    
    sector_full_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
    stocks_config_for_sector = sector_full_config.get("stocks", {})

    for stock_name in selected_stocks_from_form:
        append_log_local(f"--- Processing STOCK: {stock_name} (Sector: {sector_name}) ---", "INFO")
        stock_db_query_keywords = stocks_config_for_sector.get(stock_name, [stock_name]) 

        db_stock_articles_raw = db_crud.get_articles_for_analysis(
            db, query_start_date, query_end_date,
            target_keywords=stock_db_query_keywords, 
            limit=max_articles_llm_stock * 3 
        )

        articles_for_stock_llm_input = process_articles_for_llm(db_stock_articles_raw, stock_name, db)
        articles_trimmed_for_llm_stock = articles_for_stock_llm_input[:max_articles_llm_stock]

        current_stock_error = None
        if not articles_trimmed_for_llm_stock:
            current_stock_error = f"No relevant articles with text found in DB for stock '{stock_name}' for LLM."
            append_log_local(current_stock_error, "WARNING")
        
        stock_gemini_result = None
        all_vader_scores_for_stock = [art['vader_score'] for art in articles_for_stock_llm_input if art.get('vader_score') is not None]


        if articles_trimmed_for_llm_stock and not current_stock_error:
            append_log_local(f"Sending {len(articles_trimmed_for_llm_stock)} articles to Gemini for stock '{stock_name}'.", "INFO")
            stock_gemini_result, gemini_err = gemini_utils.analyze_news_with_gemini(
                current_api_keys['gemini'], 
                [art['content'] for art in articles_trimmed_for_llm_stock], 
                stock_name, llm_context_range_str, custom_prompt, append_log_local, target_type="stock"
            )
            if gemini_err: current_stock_error = gemini_err
            
            # Update DB with LLM results for these specific articles
            if stock_gemini_result:
                for art_input_item in articles_trimmed_for_llm_stock: # Only for those sent to LLM
                    db_crud.update_article_sentiment_scores(
                        db, article_url=art_input_item['uri'],
                        # vader_score is already set in process_articles_for_llm
                        llm_sentiment_score=stock_gemini_result.get('sentiment_score_llm'),
                        llm_sentiment_label=stock_gemini_result.get('overall_sentiment'),
                        llm_analysis_json=json.dumps(stock_gemini_result), # Store the whole LLM JSON for the stock
                        related_sector=sector_name, # Ensure sector context is stored
                        related_stock=stock_name
                    )
        
        avg_vader_score_for_this_stock_batch = sentiment_analyzer.get_average_vader_score(all_vader_scores_for_stock)
        vader_label_for_this_stock_batch = sentiment_analyzer.get_sentiment_label_from_score(avg_vader_score_for_this_stock_batch)

        stock_analysis_results_payload.append({
            'stock_name': stock_name,
            'llm_context_date_range': llm_context_range_str,
            'num_articles_for_llm_stock': len(articles_trimmed_for_llm_stock),
            'gemini_analysis_stock': stock_gemini_result,
            'error_message_stock': current_stock_error,
            'avg_vader_score_stock': avg_vader_score_for_this_stock_batch,
            'vader_sentiment_label_stock': vader_label_for_this_stock_batch
        })

    append_log_local(f"--- Stock analysis for sector '{sector_name}' finished. ---", "INFO")
    return jsonify({
        'error': False, 
        'messages': [f"Stock analysis for '{sector_name}' complete."], 
        'results_stocks': stock_analysis_results_payload, 
        'sector_name': sector_name,
        'logs': ui_log_messages
    })

if __name__ == '__main__':
    logger.info(f"Sentiment Analysis Dashboard (Flask + news-fetch DB) starting...")
    # Ensure tables are created if they don't exist (safe to call multiple times)
    try:
        create_db_and_tables()
        logger.info("Database tables checked/created successfully.")
    except Exception as e_db_create:
        logger.error(f"CRITICAL: Failed to create/check database tables on startup: {e_db_create}")
        # Optionally, exit if DB is essential and cannot be created
        # exit(1)

    port = int(os.environ.get("PORT", 5003)) 
    logger.info(f"Flask app running on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port)