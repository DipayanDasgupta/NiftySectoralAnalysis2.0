# ~/CombinedNiftyNewsApp/app.py
import os
import logging
from flask import Flask, render_template, request, jsonify, session as flask_session
from datetime import datetime, timedelta, timezone
import json
import time
from sqlalchemy.orm import Session
import pandas as pd
import yfinance as yf

# Project-specific utils
from utils import gemini_utils, sentiment_analyzer, db_crud, newsapi_helpers
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle
from utils.newsfetch_lib.google import GoogleSearchNewsURLExtractor
from utils.newsfetch_lib.news import Newspaper

import config

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d (%(funcName)s)] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "app.log"))
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("nltk").setLevel(logging.INFO)
logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(logging.WARNING)
logging.getLogger("undetected_chromedriver").setLevel(logging.WARNING)
logging.getLogger("utils.newsfetch_lib.google").setLevel(logging.INFO)
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("newsplease").setLevel(logging.INFO) # For news-please if it's verbose

# --- Database ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Key Management ---
def get_api_keys_from_session_or_config():
    gemini_key = flask_session.get('gemini_key_sess', config.GEMINI_API_KEY)
    newsapi_key = flask_session.get('newsapi_key_sess', config.NEWSAPI_ORG_API_KEY)

    is_gemini_valid = bool(gemini_key and gemini_key != config.GEMINI_API_KEY_PLACEHOLDER)
    is_newsapi_valid = bool(newsapi_key and newsapi_key != config.NEWSAPI_ORG_API_KEY_PLACEHOLDER)

    logger.debug(
        f"API Keys - Gemini Valid: {is_gemini_valid} (Key ending: ...{gemini_key[-5:] if gemini_key and len(gemini_key) > 5 else 'N/A'}), "
        f"NewsAPI Valid: {is_newsapi_valid} (Key ending: ...{newsapi_key[-5:] if newsapi_key and len(newsapi_key) > 5 else 'N/A'})"
    )
    
    return {
        'gemini': gemini_key,
        'newsapi': newsapi_key,
        'gemini_is_valid': is_gemini_valid,
        'newsapi_is_valid': is_newsapi_valid
    }

# --- UI Log Helper ---
def setup_local_logger(ui_log_list):
    def append_log_local(message, level='INFO'):
         timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3] # Use UTC for consistency
         level_upper = level.upper()
         entry = {'timestamp': timestamp, 'message': str(message), 'level': level_upper}
         ui_log_list.append(entry)
         # Also log to main server log for backend debugging
         if level_upper == 'ERROR': logger.error(f"UI_LOG_RELAY: {message}")
         elif level_upper == 'WARNING': logger.warning(f"UI_LOG_RELAY: {message}")
         else: logger.info(f"UI_LOG_RELAY: {message}")
    return append_log_local

# --- Date Parsing Helper ---
def robust_date_parse(date_str):
     if not date_str: return None
     for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'):
         try: return datetime.strptime(date_str, fmt).date()
         except ValueError: continue
     logger.warning(f"Could not parse date string from UI: {date_str}")
     return None

def parse_date_for_newsfetch(date_obj): # For GoogleSearchNewsURLExtractor
    if not date_obj: return None
    return date_obj.strftime('%m/%d/%Y')

# === ROUTES ===
@app.route('/')
def index_page():
    actual_system_today = datetime.now(timezone.utc).date()
    one_month_ago = actual_system_today - timedelta(days=29) # For a 30 day range inclusive of today
    sector_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG
    context = {
        'sector_options': list(sector_config.keys()),
        'system_actual_today': actual_system_today.strftime('%Y-%m-%d'),
        'default_end_date': actual_system_today.strftime('%Y-%m-%d'),
        'one_month_ago_date': one_month_ago.strftime('%Y-%m-%d'),
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
    if 'newsapi_key' in data and data['newsapi_key'].strip():
        flask_session['newsapi_key_sess'] = data['newsapi_key']
        log_updates.append("NewsAPI key updated in session.")
    
    if not log_updates:
        return jsonify({"message": "No API keys provided to update."}), 400 # Return 400 if nothing to do
    logger.info(f"Session API Keys updated: {'; '.join(log_updates)}")
    return jsonify({"message": "Session API keys processed."})

def process_articles_for_llm(articles_list, target_name_for_log, db_session_for_vader_update: Session, source_type="db"):
    """ Processes articles from DB or NewsAPI for LLM input. """
    processed_list = []
    if not articles_list: return processed_list
    
    for art_data in articles_list:
        if source_type == "db": # art_data is a ScrapedArticle object
            if not art_data.article_text:
                logger.warning(f"Skipping DB article for LLM (no text): {art_data.url} for {target_name_for_log}")
                continue
            content_to_analyze = art_data.article_text
            vader_s = art_data.vader_score
            if vader_s is None:
                vader_s = sentiment_analyzer.get_vader_sentiment_score(content_to_analyze)
                db_crud.update_article_sentiment_scores(db_session_for_vader_update, article_url=art_data.url, vader_score=vader_s)
            
            processed_list.append({
                'content': content_to_analyze,
                'date': art_data.publication_date.strftime('%Y-%m-%d') if art_data.publication_date else 'N/A',
                'uri': art_data.url,
                'source': art_data.source_domain or 'DB Scraped',
                'vader_score': vader_s,
                'db_id': art_data.id
            })
        elif source_type == "newsapi": # art_data is a dict from newsapi_helpers
            if not art_data.get('content'):
                logger.warning(f"Skipping NewsAPI article for LLM (no content): {art_data.get('uri')} for {target_name_for_log}")
                continue
            # vader_score should already be in newsapi article dict from newsapi_helpers
            processed_list.append(art_data) 
            
    return processed_list

@app.route('/api/sector-analysis', methods=['POST'])
def perform_sector_analysis_route():
    form_data = request.json
    logger.info(f"Batch Sector Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    results_payload = []
    user_facing_errors = []

    selected_sectors_from_form = form_data.get('selected_sectors')
    if not selected_sectors_from_form or not isinstance(selected_sectors_from_form, list) or not selected_sectors_from_form:
        user_facing_errors.append("Please select at least one sector for batch analysis.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is a placeholder.")
    
    raw_start_date_str = form_data.get('start_date') # Expecting start_date from JS
    raw_end_date_str = form_data.get('end_date')
    if not raw_start_date_str or not raw_end_date_str:
        user_facing_errors.append("Start and End dates are required for batch analysis.")

    if user_facing_errors:
        logger.warning(f"Batch Sector Analysis validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    actual_today_server = datetime.now(timezone.utc).date()
    query_start_date = robust_date_parse(raw_start_date_str)
    query_end_date = robust_date_parse(raw_end_date_str)
    
    if not query_start_date or not query_end_date : # Double check parse success
        user_facing_errors.append("Invalid Start or End date format.")
        logger.warning(f"Batch Sector Analysis date parsing failed.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    query_end_date = min(query_end_date, actual_today_server)
    if query_start_date > query_end_date:
        user_facing_errors.append("Start date cannot be after end date.")
        logger.warning(f"Batch Sector Analysis date logic error: start > end.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    try:
        max_articles_llm_sector = int(form_data.get('sector_max_articles', 5)) # Mapped from 'max_articles_llm' in JS
        if max_articles_llm_sector < 1 : max_articles_llm_sector = 1
    except ValueError:
        user_facing_errors.append("Invalid number for Max Articles (Sector).")
        logger.warning(f"Batch Sector Analysis max articles parsing error.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400
        
    custom_prompt = form_data.get('sector_custom_prompt', '') # Mapped from 'custom_prompt_llm' in JS
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Batch Sector Analysis - Dates: {llm_context_range_str}, Max articles/sector for LLM: {max_articles_llm_sector}", "INFO")

    for sector_name in selected_sectors_from_form:
        append_log_local(f"--- Processing SECTOR: {sector_name} ---", "INFO")
        sector_config_details = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
        db_query_keywords_sector = [sector_name] + sector_config_details.get("newsapi_keywords", [])[:3]

        append_log_local(f"Querying DB for sector '{sector_name}' with keywords: {db_query_keywords_sector}", "DEBUG")
        db_sector_articles_raw = db_crud.get_articles_for_analysis(
            db, query_start_date, query_end_date,
            target_keywords=list(set(db_query_keywords_sector)),
            limit=max_articles_llm_sector * 3
        )
        articles_for_sector_llm_input = process_articles_for_llm(db_sector_articles_raw, sector_name, db, source_type="db")
        articles_trimmed_for_llm = articles_for_sector_llm_input[:max_articles_llm_sector]
        # (Rest of your logic for sector_gemini_result, VADER, and appending to results_payload)
        # ... (This part seems mostly fine from previous version)
        current_sector_error = None
        if not articles_trimmed_for_llm:
            current_sector_error = f"No relevant articles with text found in DB for sector '{sector_name}' for the period to send to LLM."
            append_log_local(current_sector_error, "WARNING")
        
        sector_gemini_result = None
        all_vader_scores_for_sector = [art['vader_score'] for art in articles_for_sector_llm_input if art.get('vader_score') is not None]

        if articles_trimmed_for_llm and not current_sector_error:
            append_log_local(f"Sending {len(articles_trimmed_for_llm)} articles to Gemini for sector '{sector_name}'.", "INFO")
            sector_gemini_result, gemini_err = gemini_utils.analyze_news_with_gemini(
                current_api_keys['gemini'],
                [art['content'] for art in articles_trimmed_for_llm],
                sector_name, llm_context_range_str, custom_prompt, append_log_local, target_type="sector"
            )
            if gemini_err: current_sector_error = gemini_err
        
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
            'constituent_stocks': list(sector_config_details.get("stocks", {}).keys())
        })

    append_log_local("--- Batch Sector analysis processing finished. ---", "INFO")
    return jsonify({'error': False, 'messages': ["Batch Sector analysis complete."], 'results': results_payload, 'logs': ui_log_messages})


@app.route('/api/stock-analysis', methods=['POST']) # This is for sub-stock analysis from batch sector results
def perform_sub_stock_analysis_route():
    form_data = request.json # Payload from JS `handleRunSubStockAnalysis`
    logger.info(f"Sub-Stock Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    stock_analysis_results_payload = []
    user_facing_errors = []

    sector_name = form_data.get('sector_name')
    selected_stocks_from_form = form_data.get('selected_stocks')
    if not sector_name or not selected_stocks_from_form or not isinstance(selected_stocks_from_form, list):
        user_facing_errors.append("Sector name and stocks are required.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is a placeholder.")

    raw_end_date_str = form_data.get('end_date') # From main form
    lookback_days = int(form_data.get('lookback_days', 7)) # Calculated in JS
    if not raw_end_date_str :
        user_facing_errors.append("End date is required.")
    
    if user_facing_errors:
        logger.warning(f"Sub-Stock Analysis validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    actual_today_server = datetime.now(timezone.utc).date()
    query_end_date = robust_date_parse(raw_end_date_str)
    if not query_end_date:
        user_facing_errors.append("Invalid End date format for sub-stock analysis.")
        logger.warning(f"Sub-Stock Analysis date parsing failed.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400
        
    query_end_date = min(query_end_date, actual_today_server)
    query_start_date = query_end_date - timedelta(days=lookback_days - 1)
    
    try:
        max_articles_llm_stock = int(form_data.get('stock_max_articles', 3)) # From main form via JS
        if max_articles_llm_stock < 1: max_articles_llm_stock = 1
    except ValueError:
        user_facing_errors.append("Invalid number for Max Articles (Stock).")
        logger.warning(f"Sub-Stock Analysis max articles parsing error.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    custom_prompt = form_data.get('custom_prompt', '') # From main form via JS
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Sub-Stock analysis for '{sector_name}' stocks. Dates: {llm_context_range_str}, Max articles/stock: {max_articles_llm_stock}", "INFO")

    sector_full_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
    stocks_config_for_sector = sector_full_config.get("stocks", {})

    for stock_name in selected_stocks_from_form:
        append_log_local(f"--- Processing STOCK: {stock_name} (Sector: {sector_name}) ---", "INFO")
        stock_db_query_keywords = stocks_config_for_sector.get(stock_name, [stock_name])
        db_stock_articles_raw = db_crud.get_articles_for_analysis(
            db, query_start_date, query_end_date,
            target_keywords=list(set(stock_db_query_keywords)),
            limit=max_articles_llm_stock * 3
        )
        articles_for_stock_llm_input = process_articles_for_llm(db_stock_articles_raw, stock_name, db, source_type="db")
        articles_trimmed_for_llm_stock = articles_for_stock_llm_input[:max_articles_llm_stock]
        # (Rest of your logic for stock_gemini_result, VADER, and appending to stock_analysis_results_payload)
        # ... (This part seems mostly fine from previous version)
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
            if stock_gemini_result: # Update DB with LLM results if successful
                for art_input_item in articles_trimmed_for_llm_stock:
                    if art_input_item.get('db_id'): # Only if it's a DB article
                        db_crud.update_article_sentiment_scores(
                            db, article_url=art_input_item['uri'], # URL is more unique
                            llm_sentiment_score=stock_gemini_result.get('sentiment_score_llm'),
                            llm_sentiment_label=stock_gemini_result.get('overall_sentiment'),
                            llm_analysis_json=json.dumps(stock_gemini_result),
                            related_sector=sector_name, related_stock=stock_name
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

    append_log_local(f"--- Sub-Stock analysis for sector '{sector_name}' finished. ---", "INFO")
    return jsonify({'error': False, 'messages': [f"Stock analysis for '{sector_name}' complete."], 'results_stocks': stock_analysis_results_payload, 'sector_name': sector_name, 'logs': ui_log_messages})


# --- NEW: Ad-hoc Analysis and Scraping Route ---
@app.route('/api/adhoc-analysis-scrape', methods=['POST'])
def adhoc_analysis_scrape_route():
    form_data = request.json
    logger.info(f"Ad-hoc Analysis/Scrape Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    user_facing_errors = []

    target_name = form_data.get('target_name', '').strip()
    target_type = form_data.get('target_type', 'stock')
    start_date_str = form_data.get('start_date')
    end_date_str = form_data.get('end_date')
    news_source_priority = form_data.get('news_source_priority', 'local_db_then_newsapi')
    trigger_scrape = form_data.get('trigger_scrape', False) # JS sends boolean
    scrape_domains_raw = form_data.get('scrape_domains', []) # JS sends array
    scrape_domains = [d.strip() for d in scrape_domains_raw if isinstance(d, str) and d.strip()] if isinstance(scrape_domains_raw, list) else []

    custom_prompt = form_data.get('custom_prompt_llm', '')

    # Validation
    if not target_name: user_facing_errors.append("Target name/ticker is required.")
    if not start_date_str or not end_date_str: user_facing_errors.append("Start and End dates are required.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is a placeholder.")
    if ('newsapi' in news_source_priority or news_source_priority == 'newsapi_only') and \
       (not current_api_keys.get('newsapi_is_valid')):
        user_facing_errors.append("NewsAPI key is not configured properly (or is placeholder) but selected as a source.")
    if trigger_scrape and not scrape_domains:
        user_facing_errors.append("If triggering scrape, at least one domain must be provided.")

    try:
        max_articles_llm = int(form_data.get('max_articles_llm', 5))
        if max_articles_llm < 1: max_articles_llm = 1
    except ValueError:
        user_facing_errors.append("Invalid value for Max articles for LLM.")
        max_articles_llm = 5 # Default

    if user_facing_errors:
        logger.warning(f"Ad-hoc request validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages}), 400

    query_start_date_obj = robust_date_parse(start_date_str)
    query_end_date_obj = robust_date_parse(end_date_str)
    actual_today_server = datetime.now(timezone.utc).date()

    if not query_start_date_obj or not query_end_date_obj:
        user_facing_errors.append("Invalid Start or End date format.")
        logger.warning(f"Ad-hoc date parsing failed.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages}), 400
        
    query_end_date_obj = min(query_end_date_obj, actual_today_server)
    if query_start_date_obj > query_end_date_obj:
        user_facing_errors.append("Start date cannot be after end date.")
        logger.warning(f"Ad-hoc date logic error: start > end.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages}), 400
    
    llm_context_range_str = f"{query_start_date_obj.strftime('%Y-%m-%d')} to {query_end_date_obj.strftime('%Y-%m-%d')}"
    append_log_local(f"Ad-hoc analysis for '{target_name}' ({target_type}). Dates: {llm_context_range_str}", "INFO")

    if trigger_scrape: # trigger_scrape is already a boolean from JS
        append_log_local(f"Triggering on-demand scrape for '{target_name}' on domains: {scrape_domains}", "INFO")
        run_on_demand_scrape(target_name, target_type, query_start_date_obj, query_end_date_obj, scrape_domains, db, append_log_local)
        append_log_local("On-demand scrape attempt finished. Proceeding with analysis.", "INFO")
    
    articles_for_analysis = [] # This will hold dicts like {'content': ..., 'date': ..., 'uri': ..., 'source': ..., 'vader_score': ...}
    
    if news_source_priority in ['local_db_then_newsapi', 'local_db_only']:
        append_log_local(f"Fetching from Local DB for '{target_name}'", "INFO")
        db_query_keywords = [target_name]
        # Add more specific keywords for DB query if possible
        if target_type == "sector":
            sector_cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(target_name, {})
            db_query_keywords.extend(sector_cfg.get("newsapi_keywords", [])[:2]) # Use newsapi_keywords as they are general
        elif target_type == "stock":
            for sector_data_val in gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.values():
                if target_name in sector_data_val.get("stocks", {}):
                    db_query_keywords.extend(sector_data_val["stocks"][target_name][:2])
                    break
        
        db_articles_raw = db_crud.get_articles_for_analysis(
            db, query_start_date_obj, query_end_date_obj,
            target_keywords=list(set(db_query_keywords)),
            limit=max_articles_llm * 3 # Fetch more for VADER even if LLM count is small
        )
        articles_for_analysis.extend(process_articles_for_llm(db_articles_raw, target_name, db, source_type="db"))
        append_log_local(f"Found {len(articles_for_analysis)} articles from DB for '{target_name}'.", "INFO")

    newsapi_err_msg = None
    if news_source_priority == 'newsapi_only' or \
       (news_source_priority == 'local_db_then_newsapi' and len(articles_for_analysis) < max_articles_llm):
        
        needed_from_newsapi = max_articles_llm - len(articles_for_analysis) if news_source_priority == 'local_db_then_newsapi' else max_articles_llm
        
        if needed_from_newsapi > 0 and current_api_keys.get('newsapi_is_valid'):
            append_log_local(f"Fetching from NewsAPI.org for '{target_name}' (need ~{needed_from_newsapi} more).", "INFO")
            newsapi_client, client_err = newsapi_helpers.get_newsapi_org_client(current_api_keys['newsapi'], append_log_local)
            if newsapi_client:
                api_keywords = [target_name] # Base keyword
                if target_type == "stock":
                    # Try to find more specific keywords for the stock from config
                    found_stock_keywords = False
                    for sector_data_val in gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.values():
                        if target_name in sector_data_val.get("stocks", {}):
                            api_keywords.extend(sector_data_val["stocks"][target_name][:3]) # Add a few specific ones
                            found_stock_keywords = True
                            break
                    if not found_stock_keywords: # Generic stock terms if not in config
                        api_keywords.extend([f"{target_name} stock", f"{target_name} share price"])
                elif target_type == "sector":
                     sector_cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(target_name, {})
                     api_keywords.extend(sector_cfg.get("newsapi_keywords", [])[:3]) # More general for sector

                newsapi_fetched_data, newsapi_err_msg_local = newsapi_helpers.fetch_newsapi_articles(
                    newsapi_client, target_name, list(set(api_keywords)), gemini_utils.NEWSAPI_INDIA_MARKET_KEYWORDS,
                    query_start_date_obj, query_end_date_obj, 
                    max_articles_to_fetch=needed_from_newsapi, # Fetch only what's needed
                    append_log_func=append_log_local
                )
                if newsapi_err_msg_local: newsapi_err_msg = newsapi_err_msg_local
                
                # Combine and deduplicate (NewsAPI articles already have 'vader_score')
                existing_uris = {art['uri'] for art in articles_for_analysis}
                for napi_art in newsapi_fetched_data:
                    if napi_art['uri'] not in existing_uris:
                        articles_for_analysis.append(napi_art)
                        existing_uris.add(napi_art['uri'])
                append_log_local(f"Total articles after NewsAPI check: {len(articles_for_analysis)} for '{target_name}'.", "INFO")
            elif client_err: # Failed to init client
                newsapi_err_msg = client_err
                append_log_local(newsapi_err_msg, "ERROR")
        elif needed_from_newsapi > 0 and not current_api_keys.get('newsapi_is_valid'):
             append_log_local("Skipping NewsAPI fetch as key is not valid, though articles are needed.", "WARNING")
             newsapi_err_msg = "NewsAPI key not valid, so supplemental fetch skipped."


    articles_for_analysis.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
    articles_trimmed_for_llm = articles_for_analysis[:max_articles_llm]

    llm_analysis_result = None
    current_target_error = newsapi_err_msg
    
    if not articles_trimmed_for_llm:
        msg = f"No relevant articles found for '{target_name}' from any source to send to LLM."
        append_log_local(msg, "WARNING")
        current_target_error = (current_target_error + "; " + msg) if current_target_error else msg
    elif not current_api_keys.get('gemini_is_valid'):
        msg = f"Gemini API key not valid. LLM analysis skipped for '{target_name}'."
        append_log_local(msg, "ERROR")
        current_target_error = (current_target_error + "; " + msg) if current_target_error else msg
    else:
        append_log_local(f"Sending {len(articles_trimmed_for_llm)} articles to Gemini for '{target_name}'.", "INFO")
        llm_analysis_result, gemini_err = gemini_utils.analyze_news_with_gemini(
            current_api_keys['gemini'],
            [art['content'] for art in articles_trimmed_for_llm],
            target_name, llm_context_range_str, custom_prompt, append_log_local, target_type=target_type
        )
        if gemini_err:
            current_target_error = (current_target_error + "; " + gemini_err) if current_target_error else gemini_err
            append_log_local(f"Gemini error for {target_name}: {gemini_err}", "ERROR")

    # Prepare data for daily rolling sentiment (VADER based on all fetched articles)
    daily_sentiment_data = []
    if articles_for_analysis:
        df_articles = pd.DataFrame(articles_for_analysis)
        if not df_articles.empty and 'date' in df_articles.columns and 'vader_score' in df_articles.columns:
            df_articles['date_obj'] = pd.to_datetime(df_articles['date'], errors='coerce')
            df_articles = df_articles.dropna(subset=['date_obj', 'vader_score'])
            if not df_articles.empty:
                daily_avg_sentiment = df_articles.groupby(df_articles['date_obj'].dt.date)['vader_score'].mean().reset_index()
                daily_avg_sentiment.rename(columns={'vader_score': 'avg_sentiment_score', 'date_obj': 'date'}, inplace=True)
                daily_avg_sentiment['date'] = daily_avg_sentiment['date'].astype(str)
                daily_sentiment_data = daily_avg_sentiment.to_dict('records')
    append_log_local(f"Prepared {len(daily_sentiment_data)} daily sentiment data points for chart.", "DEBUG")

    price_data_for_chart = []
    if target_type == "stock":
        price_data_for_chart = get_yfinance_prices(target_name, query_start_date_obj.strftime('%Y-%m-%d'), query_end_date_obj.strftime('%Y-%m-%d'), append_log_local)

    return jsonify({
        'error': bool(current_target_error),
        'messages': [current_target_error] if current_target_error else [f"Ad-hoc analysis for '{target_name}' complete."],
        'target_name': target_name,
        'target_type': target_type,
        'llm_analysis': llm_analysis_result,
        'articles_analyzed': articles_trimmed_for_llm, # Articles sent to LLM
        'all_articles_fetched_count': len(articles_for_analysis), # Total articles considered
        'daily_sentiment_data': daily_sentiment_data,
        'price_data': price_data_for_chart,
        'logs': ui_log_messages
    })

def get_yfinance_prices(ticker, start_date_str, end_date_str, append_log_local):
    """Fetches historical price data using yfinance."""
    if not ticker:
        append_log_local(f"No ticker provided for yfinance.", "ERROR")
        return []

    ticker_yf = ticker.upper()
    if '.' not in ticker_yf: # If no exchange suffix, default to .NS
        ticker_yf = f"{ticker_yf}.NS"
    
    append_log_local(f"Fetching yfinance data for {ticker_yf} from {start_date_str} to {end_date_str}", "INFO")
    
    try:
        yf_end_date_dt = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
        yf_end_date_str_inclusive = yf_end_date_dt.strftime("%Y-%m-%d")

        stock_data_df = yf.download(
            ticker_yf, 
            start=start_date_str, 
            end=yf_end_date_str_inclusive, 
            progress=False, 
            auto_adjust=True
        )
        
        if stock_data_df.empty:
            append_log_local(f"No price data found for {ticker_yf} (attempt 1) for period {start_date_str} to {end_date_str}.", "WARNING")
            if ticker_yf.endswith(".NS"):
                ticker_plain = ticker_yf[:-3]
                append_log_local(f"Retrying yfinance for {ticker_plain} without .NS suffix.", "INFO")
                stock_data_df = yf.download(ticker_plain, start=start_date_str, end=yf_end_date_str_inclusive, progress=False, auto_adjust=True)
                if stock_data_df.empty:
                    append_log_local(f"Still no price data for {ticker_plain} (attempt 2).", "WARNING")
                    return []
            else:
                return []
        
        stock_data_df_reset = stock_data_df.reset_index()
        
        price_list = []
        for index, row_data in stock_data_df_reset.iterrows(): # row_data is a Pandas Series for each row
            date_scalar = None
            close_price_scalar = None

            # --- CRITICAL FIX: Ensure we are working with SCALAR values ---
            try:
                # Attempt to get the scalar value. If row_data['Date'] is already scalar, this is fine.
                # If it's a Series with one item, .item() extracts it.
                # If it's a Series with multiple items (unexpected here), .item() would raise an error.
                date_value_from_row = row_data['Date']
                if isinstance(date_value_from_row, pd.Series):
                    if len(date_value_from_row) == 1:
                        date_scalar = date_value_from_row.item()
                    else:
                        append_log_local(f"Row {index} 'Date' is a Series with multiple values: {date_value_from_row}. Skipping.", "ERROR")
                        continue
                else: # Assume it's already a scalar (Timestamp, datetime, or other)
                    date_scalar = date_value_from_row

                close_price_from_row = row_data['Close']
                if isinstance(close_price_from_row, pd.Series):
                    if len(close_price_from_row) == 1:
                        close_price_scalar = close_price_from_row.item()
                    else:
                        append_log_local(f"Row {index} 'Close' is a Series with multiple values: {close_price_from_row}. Skipping.", "ERROR")
                        continue
                else: # Assume it's already a scalar
                    close_price_scalar = close_price_from_row

            except KeyError as ke:
                append_log_local(f"KeyError accessing 'Date' or 'Close' for row {index}: {ke}. Row data: {row_data.to_dict()}", "ERROR")
                continue
            except ValueError as ve: # Handles .item() error if Series has more than one element
                append_log_local(f"ValueError extracting scalar for row {index} (likely multi-value Series): {ve}. Row Date: {row_data.get('Date')}, Row Close: {row_data.get('Close')}. Skipping.", "ERROR")
                continue


            # Now date_scalar and close_price_scalar should be actual scalar values or None
            if pd.isna(date_scalar) or pd.isna(close_price_scalar):
                append_log_local(f"Skipping row {index} due to NaN date or price. Date: {date_scalar}, Price: {close_price_scalar}", "DEBUG")
                continue

            formatted_date = ""
            if isinstance(date_scalar, pd.Timestamp):
                formatted_date = date_scalar.strftime('%Y-%m-%d')
            elif isinstance(date_scalar, datetime): # datetime.datetime object
                formatted_date = date_scalar.strftime('%Y-%m-%d')
            else: # Fallback for other types, like strings if data was odd
                append_log_local(f"Unexpected date type for {ticker_yf} at row {index}: {type(date_scalar)}. Value: {date_scalar}. Attempting string conversion and parsing.", "WARNING")
                try:
                    formatted_date = pd.to_datetime(str(date_scalar)).strftime('%Y-%m-%d')
                except Exception as e_conv:
                    append_log_local(f"Could not format date '{date_scalar}' at row {index}: {e_conv}. Skipping point.", "ERROR")
                    continue
            
            try:
                numeric_close_price = float(close_price_scalar)
            except (ValueError, TypeError) as e_price_conv:
                append_log_local(f"Could not convert close price '{close_price_scalar}' to float at row {index}: {e_price_conv}. Skipping point.", "ERROR")
                continue

            price_list.append({
                "date": formatted_date,
                "close_price": numeric_close_price
            })
            
        append_log_local(f"Successfully processed {len(price_list)} price points for {ticker_yf}.", "INFO")
        return price_list
        
    except Exception as e:
        append_log_local(f"General error fetching or processing yfinance data for {ticker_yf}: {e}", "ERROR")
        logger.error(f"Full yfinance error details for {ticker_yf}:", exc_info=True)
        return []

def run_on_demand_scrape(target_name, target_type, start_date_obj, end_date_obj, domains_to_scrape, db_session, append_log_local):
    """
    Performs a small, synchronous scrape for the given target and date range.
    Adds new articles to the database.
    """
    append_log_local(f"Starting on-demand scrape for {target_type} '{target_name}', Dates: {start_date_obj} to {end_date_obj}", "INFO")
    articles_saved_count = 0
    
    google_start_date_param = parse_date_for_newsfetch(start_date_obj)
    google_end_date_param = parse_date_for_newsfetch(end_date_obj)
    target_year_str = str(start_date_obj.year) # Could also use end_date_obj.year if range spans years

    keywords_to_search_google = []
    if target_type == "stock":
        keywords_to_search_google = [f"'{target_name}' news {target_year_str}", f"'{target_name}' financial results {target_year_str}"]
    elif target_type == "sector":
        keywords_to_search_google = [f"'{target_name}' India {target_year_str}", f"'{target_name}' sector outlook {target_year_str}"]
    else:
        append_log_local(f"Invalid target_type for scraping: {target_type}", "ERROR")
        return 0

    # Load existing URLs from DB at the start of this scrape function to avoid re-querying in loop
    existing_db_urls = {res[0] for res in db_session.query(ScrapedArticle.url).all()}
    append_log_local(f"On-demand scrape: Found {len(existing_db_urls)} existing URLs in DB initially.", "DEBUG")

    for keyword_g in keywords_to_search_google:
        for domain in domains_to_scrape:
            append_log_local(f"  Scraping Google: '{keyword_g}' on domain '{domain}'", "DEBUG")
            try:
                # Instantiate the extractor
                google_tool = GoogleSearchNewsURLExtractor(
                    keyword=keyword_g, 
                    news_domain=domain,
                    start_date_str=google_start_date_param, 
                    end_date_str=google_end_date_param,
                    lang="en", 
                    country_code="IN", 
                    num_pages=1 # For on-demand, usually 1 page is enough
                    # proxy_config=get_random_proxy() # If you implement proxy rotation
                )
                # Call the method that fetches URLs and manages the driver
                found_urls = google_tool.fetch_all_urls() 
                
                append_log_local(f"    Google found {len(found_urls)} URLs for '{keyword_g}' on {domain}.", "DEBUG")

                for url_idx, url in enumerate(found_urls):
                    if url in existing_db_urls:
                        append_log_local(f"      URL {url_idx+1}/{len(found_urls)}: Skipping (already in DB): {url}", "VERBOSE")
                        continue
                    
                    append_log_local(f"      URL {url_idx+1}/{len(found_urls)}: Fetching & Parsing: {url}", "DEBUG")
                    time.sleep(config.SCRAPER_ARTICLE_FETCH_DELAY / 2) # Shorter delay for on-demand, but still exist
                    
                    try:
                        news_article = Newspaper(url=url) # This initializes and fetches/parses
                        
                        # Use the datetime object directly from news.py for consistency
                        pub_date_dt_utc_naive = news_article.date_publish_datetime_utc 
                        
                        if not pub_date_dt_utc_naive:
                            append_log_local(f"        Could not parse date for {url}. Skipping.", "WARNING")
                            existing_db_urls.add(url)
                            continue
                        
                        if not (start_date_obj <= pub_date_dt_utc_naive.date() <= end_date_obj):
                            append_log_local(f"        Article date {pub_date_dt_utc_naive.date()} outside scrape range {start_date_obj}-{end_date_obj}. Skipping.", "INFO")
                            existing_db_urls.add(url)
                            continue

                        if news_article.article and news_article.headline:
                            db_entry = ScrapedArticle(
                                url=news_article.url, 
                                headline=news_article.headline,
                                article_text=news_article.article, 
                                publication_date=pub_date_dt_utc_naive, # Store as naive UTC datetime
                                download_date=datetime.now(timezone.utc).replace(tzinfo=None),
                                source_domain=news_article.source_domain, 
                                language=news_article.language,
                                authors=json.dumps(news_article.authors) if news_article.authors else None,
                                keywords_extracted=json.dumps(news_article.keywords) if news_article.keywords else None,
                                summary_generated=news_article.summary,
                                related_sector=target_name if target_type == "sector" else None,
                                related_stock=target_name if target_type == "stock" else None
                            )
                            db_session.add(db_entry)
                            db_session.commit() # Commit each article to make it available sooner
                            existing_db_urls.add(url) # Add to set after successful save
                            articles_saved_count += 1
                            append_log_local(f"        SAVED to DB: {url}", "INFO")
                        else:
                            append_log_local(f"        No usable content/headline for {url}. Skipping.", "WARNING")
                            existing_db_urls.add(url) # Still mark as processed to avoid retrying this specific URL soon
                    except Exception as e_art:
                        append_log_local(f"        Error processing article {url}: {str(e_art)[:150]}", "ERROR")
                        if db_session.is_active: db_session.rollback()
                        existing_db_urls.add(url)
                    finally:
                        # Make sure to close the selenium driver if GoogleSearchNewsURLExtractor created one internally and doesn't auto-close
                        if hasattr(google_tool, 'driver') and google_tool.driver:
                           pass # The driver management should be within GoogleSearchNewsURLExtractor
                                # If it's not, this function becomes more complex.
                                # For now, assume google_tool handles its driver lifecycle per call to .urls or a close method.

            except Exception as e_google_search_instance: # Catch errors from GoogleSearchNewsURLExtractor instantiation or fetch
                append_log_local(f"    Critical Error with Google Search for '{keyword_g}' on {domain}: {str(e_google_search_instance)[:150]}", "ERROR")
                logger.error(f"Critical Error instantiating or running GoogleSearchNewsURLExtractor: {e_google_search_instance}", exc_info=True)
            finally:
                # Ensure the driver used by GoogleSearchNewsURLExtractor is quit if it was created inside the loop
                if 'google_tool' in locals() and hasattr(google_tool, 'driver') and google_tool.driver:
                    try:
                        google_tool.close_driver() # Add a close_driver() method to your GoogleSearchNewsURLExtractor
                        append_log_local(f"Closed Selenium driver for {domain} query.", "DEBUG")
                    except Exception as e_close_driver:
                        append_log_local(f"Error closing driver for {domain}: {e_close_driver}", "WARNING")
            time.sleep(config.SCRAPER_SEARCH_DELAY / 2) # Shorter delay for on-demand
            
    append_log_local(f"On-demand scrape finished. Saved {articles_saved_count} new articles.", "INFO")
    return articles_saved_count


if __name__ == '__main__':
    logger.info(f"Nifty News Sentiment Analyzer starting...")
    try:
        create_db_and_tables()
        logger.info("Database tables checked/created successfully.")
    except Exception as e_db_create:
        logger.error(f"CRITICAL: Failed to create/check database tables on startup: {e_db_create}")

    port = int(os.environ.get("PORT", 5003))
    logger.info(f"Flask app running on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=True) # use_reloader=True for dev