# ~/CombinedNiftyNewsApp/scrape_financial_news_db.py
import os
import json
import time
from datetime import datetime, timezone, timedelta
import logging
import re

# Adjusted imports to reflect the new library location
from utils.newsfetch_lib.google import GoogleSearchNewsURLExtractor
from utils.newsfetch_lib.news import Newspaper
from utils.database_models import ScrapedArticle, SessionLocal, create_db_and_tables
from utils.gemini_utils import NIFTY_SECTORS_QUERY_CONFIG # Import your config

# --- Configuration for News Domains ---
NEWS_DOMAINS_TO_SCRAPE = [
    'economictimes.indiatimes.com',
    'livemint.com',
    'business-standard.com',
    'thehindubusinessline.com',
    'financialexpress.com',
    'moneycontrol.com',
    'reuters.com', # General Reuters can be good
    'bqprime.com',
    'cnbctv18.com',
    'thehindu.com/business/', # More specific path
    'ndtvprofit.com',
    # 'businessinsider.in', # Often harder to scrape consistently
    'zeebiz.com',
    'indiainfoline.com/news/', # More specific path
    # 'mintgenie.livemint.com', # Subdomain, might be covered by livemint.com
]

OUTPUT_DIR_LOGS = "scraper_run_logs_and_processed_urls"
os.makedirs(OUTPUT_DIR_LOGS, exist_ok=True)

SEARCH_DELAY = 15  # Seconds between Google searches for different keyword/domain combos
ARTICLE_FETCH_DELAY = 7 # Seconds between fetching individual articles
GOOGLE_PAGES_TO_SCRAPE = 1 # Number of Google search result pages to try per query

PROCESSED_GOOGLE_QUERIES_FILE = os.path.join(OUTPUT_DIR_LOGS, "processed_google_queries.txt")

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
                    handlers=[
                        logging.FileHandler(os.path.join(OUTPUT_DIR_LOGS, "financial_scraper.log")),
                        logging.StreamHandler()
                    ])
scraper_logger = logging.getLogger("SectorStockNewsScraperDB")
# Set newsfetch_lib's google logger to INFO as well if you want its logs in your file
logging.getLogger("utils.newsfetch_lib.google").setLevel(logging.INFO)


def load_processed_google_queries():
    processed = set()
    if os.path.exists(PROCESSED_GOOGLE_QUERIES_FILE):
        try:
            with open(PROCESSED_GOOGLE_QUERIES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    processed.add(line.strip())
            scraper_logger.info(f"Loaded {len(processed)} processed Google queries from {PROCESSED_GOOGLE_QUERIES_FILE}")
        except Exception as e:
            scraper_logger.error(f"Error loading processed Google queries file: {e}")
    return processed

def save_processed_google_query(query_key):
    try:
        with open(PROCESSED_GOOGLE_QUERIES_FILE, 'a', encoding='utf-8') as f:
            f.write(query_key + '\n')
    except Exception as e:
        scraper_logger.error(f"Error saving processed Google query key {query_key}: {e}")

def parse_date_robustly(date_str_or_dt):
    if isinstance(date_str_or_dt, datetime):
        if date_str_or_dt.tzinfo is not None:
            return date_str_or_dt.astimezone(timezone.utc).replace(tzinfo=None)
        return date_str_or_dt
    if not date_str_or_dt or str(date_str_or_dt).lower() == 'none': return None
    formats_to_try = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"
    ]
    for fmt in formats_to_try:
        try:
            dt_obj = datetime.strptime(str(date_str_or_dt), fmt)
            if dt_obj.tzinfo is not None:
                return dt_obj.astimezone(timezone.utc).replace(tzinfo=None)
            return dt_obj
        except (ValueError, TypeError): continue
    scraper_logger.debug(f"Could not parse date: {date_str_or_dt} with known formats.")
    return None

def get_db_session():
    return SessionLocal()

def generate_keyword_queries_from_config(config, target_year_str):
    """
    Generates a list of dictionaries, each representing a distinct Google query.
    Each dict: {'item_type': 'sector'/'stock', 'item_name': str, 'sector_context': str, 'google_keyword': str}
    """
    queries = []
    for sector_name, sector_details in config.items():
        # Sector-level keywords
        sector_base_keywords = sector_details.get("newsapi_keywords", []) # Use existing key
        if sector_base_keywords:
            # Create fewer, more potent Google queries for the sector.
            # Example: Combine sector name with a couple of its most general keywords.
            # Or use each keyword from newsapi_keywords individually with the year.
            for skw in sector_base_keywords[:3]: # Take top 3 general keywords for the sector
                 google_kw = f"{skw} {target_year_str}" if target_year_str not in skw else skw
                 queries.append({
                     'item_type': "sector", 'item_name': sector_name, 
                     'sector_context': sector_name, 'google_keyword': google_kw
                 })
            # Add a query for the sector name itself if not covered
            if not any(sector_name.lower() in q['google_keyword'].lower() for q in queries if q['item_name'] == sector_name):
                queries.append({
                     'item_type': "sector", 'item_name': sector_name, 
                     'sector_context': sector_name, 'google_keyword': f"{sector_name} news {target_year_str}"
                 })

        # Stock-level keywords
        if "stocks" in sector_details:
            for stock_name, stock_specific_keywords_list in sector_details["stocks"].items():
                # For each stock, generate a few targeted Google search queries
                # Query 1: Stock name + "news" + year
                queries.append({
                    'item_type': "stock", 'item_name': stock_name, 
                    'sector_context': sector_name, 'google_keyword': f"'{stock_name}' news {target_year_str}"
                })
                # Query 2 (optional): Top 1-2 specific keywords for that stock + year
                for sskw in stock_specific_keywords_list[:1]: # Take first specific keyword
                    google_kw_stock = f"'{stock_name}' {sskw} {target_year_str}"
                    queries.append({
                        'item_type': "stock", 'item_name': stock_name, 
                        'sector_context': sector_name, 'google_keyword': google_kw_stock
                    })
    
    # Deduplicate queries (based on google_keyword and item_name to avoid too many similar searches)
    # This basic deduplication might need refinement if google_keywords are very similar
    unique_queries_temp = {}
    for q in queries:
        key = (q['google_keyword'], q['item_name']) # Deduplicate based on the search term and target
        if key not in unique_queries_temp:
            unique_queries_temp[key] = q
    
    return list(unique_queries_temp.values())


if __name__ == "__main__":
    scraper_logger.info(f"--- Starting Sector/Stock News Scraping (to Database) ---")
    
    create_db_and_tables()
    db = get_db_session()

    processed_google_queries = load_processed_google_queries()
    db_urls = {res[0] for res in db.query(ScrapedArticle.url).all()}
    scraper_logger.info(f"Loaded {len(db_urls)} URLs already present in the database.")
    
    total_articles_saved_this_run = 0
    total_google_searches_performed_this_run = 0

    while True:
        start_date_input_str = input(f"Enter START date for article publication (YYYY-MM-DD): ").strip()
        end_date_input_str = input(f"Enter END date for article publication (YYYY-MM-DD): ").strip()
        try:
            SCRAPE_START_DATE_OBJ = datetime.strptime(start_date_input_str, "%Y-%m-%d").date()
            SCRAPE_END_DATE_OBJ = datetime.strptime(end_date_input_str, "%Y-%m-%d").date()
            if SCRAPE_START_DATE_OBJ > SCRAPE_END_DATE_OBJ:
                print("Start date cannot be after end date. Please try again.")
                continue
            GOOGLE_START_DATE_PARAM = SCRAPE_START_DATE_OBJ.strftime('%m/%d/%Y')
            GOOGLE_END_DATE_PARAM = SCRAPE_END_DATE_OBJ.strftime('%m/%d/%Y')
            TARGET_YEAR_STR = str(SCRAPE_START_DATE_OBJ.year) 
            scraper_logger.info(f"Targeting articles published between: {SCRAPE_START_DATE_OBJ} and {SCRAPE_END_DATE_OBJ}")
            scraper_logger.info(f"Google date filter params: {GOOGLE_START_DATE_PARAM} to {GOOGLE_END_DATE_PARAM}")
            break
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD. Try again.")

    keyword_queries_to_make = generate_keyword_queries_from_config(NIFTY_SECTORS_QUERY_CONFIG, TARGET_YEAR_STR)
    scraper_logger.info(f"Generated {len(keyword_queries_to_make)} unique Google queries to perform.")

    try:
        for query_idx, query_details in enumerate(keyword_queries_to_make):
            item_type = query_details['item_type']
            item_name = query_details['item_name']
            sector_context_for_db = query_details['sector_context']
            keyword_to_search_on_google = query_details['google_keyword']
            
            scraper_logger.info(f"\nProcessing Query {query_idx + 1}/{len(keyword_queries_to_make)}: "
                                f"Type: {item_type}, Name: {item_name}, Google Keyword: '{keyword_to_search_on_google}'")

            for domain in NEWS_DOMAINS_TO_SCRAPE:
                google_query_key = f"{domain}|{keyword_to_search_on_google}|{GOOGLE_START_DATE_PARAM}|{GOOGLE_END_DATE_PARAM}"
                if google_query_key in processed_google_queries:
                    scraper_logger.info(f"  Skipping Google search on {domain} (already processed query key).")
                    continue

                scraper_logger.info(f"  Searching Google: '{keyword_to_search_on_google}' on {domain}")
                total_google_searches_performed_this_run += 1

                try:
                    google_search_tool = GoogleSearchNewsURLExtractor(
                        keyword=keyword_to_search_on_google,
                        news_domain=domain,
                        start_date_str=GOOGLE_START_DATE_PARAM,
                        end_date_str=GOOGLE_END_DATE_PARAM,
                        lang="en",
                        country_code="IN",
                        num_pages=GOOGLE_PAGES_TO_SCRAPE 
                    )
                    article_urls_found = google_search_tool.urls
                    save_processed_google_query(google_query_key)
                    processed_google_queries.add(google_query_key)

                    if not article_urls_found:
                        scraper_logger.info(f"    No URLs found by Google for this query on {domain}.")
                    else:
                        scraper_logger.info(f"    Found {len(article_urls_found)} URLs from Google. Processing new ones for DB...")
                        for article_url in article_urls_found:
                            if article_url in db_urls:
                                scraper_logger.debug(f"      Skipping (already in DB): {article_url}")
                                continue
                            
                            scraper_logger.info(f"      Fetching & Processing: {article_url}")
                            try:
                                news_article_obj = Newspaper(url=article_url)
                                publish_date_dt = parse_date_robustly(news_article_obj.date_publish)
                                
                                if not publish_date_dt:
                                    scraper_logger.warning(f"        Could not parse publish date ({news_article_obj.date_publish}). Skipping {article_url}")
                                    db_urls.add(article_url); continue # Mark as processed even if date fails

                                if not (SCRAPE_START_DATE_OBJ <= publish_date_dt.date() <= SCRAPE_END_DATE_OBJ):
                                    scraper_logger.info(f"        Skipping (date {publish_date_dt.date()} outside range {SCRAPE_START_DATE_OBJ}-{SCRAPE_END_DATE_OBJ}): {article_url}")
                                    db_urls.add(article_url); continue
                                
                                if not news_article_obj.article and not news_article_obj.headline:
                                    scraper_logger.warning(f"        Skipping (no article text or headline by news-fetch): {article_url}")
                                    db_urls.add(article_url); continue

                                db_article_entry = ScrapedArticle(
                                    url=news_article_obj.url, headline=news_article_obj.headline,
                                    article_text=news_article_obj.article, publication_date=publish_date_dt,
                                    download_date=datetime.now(timezone.utc).replace(tzinfo=None),
                                    source_domain=news_article_obj.source_domain, language=news_article_obj.language,
                                    authors=json.dumps(news_article_obj.authors) if news_article_obj.authors else None,
                                    keywords_extracted=json.dumps(news_article_obj.keywords) if news_article_obj.keywords else None,
                                    summary_generated=news_article_obj.summary,
                                    related_sector=sector_context_for_db,
                                    related_stock=item_name if item_type == "stock" else None
                                )
                                db.add(db_article_entry)
                                db.commit()
                                db_urls.add(article_url)
                                total_articles_saved_this_run += 1
                                scraper_logger.info(f"        SAVED to DB: (Pub: {publish_date_dt.date()}) - {article_url}")

                            except ValueError as ve_nf: # From news-fetch Newspaper class validation
                                scraper_logger.error(f"        News-fetch validation error for {article_url}: {ve_nf}")
                                db_urls.add(article_url) 
                            except Exception as e_art:
                                scraper_logger.error(f"        Error processing article {article_url}: {e_art}", exc_info=False)
                                db_urls.add(article_url)
                                if db.is_active: db.rollback()
                            finally:
                                time.sleep(ARTICLE_FETCH_DELAY)
                except Exception as e_gs:
                    scraper_logger.error(f"    Error during Google Search on {domain} for '{keyword_to_search_on_google}': {e_gs}", exc_info=False)
                    save_processed_google_query(google_query_key) # Still mark query as attempted
                    processed_google_queries.add(google_query_key)
                finally:
                    scraper_logger.info(f"  Waiting {SEARCH_DELAY}s before next domain for this keyword OR next keyword query...")
                    time.sleep(SEARCH_DELAY)
    except KeyboardInterrupt:
        scraper_logger.info("\n--- Scraping interrupted by user (Ctrl+C) ---")
    finally:
        scraper_logger.info(f"\n--- Scraping Run Summary ---")
        scraper_logger.info(f"Total Google Searches performed this run: {total_google_searches_performed_this_run}")
        scraper_logger.info(f"Total articles saved to DB this run: {total_articles_saved_this_run}")
        scraper_logger.info(f"Total unique Google queries processed overall (from file): {len(processed_google_queries)}")
        scraper_logger.info(f"Total articles now in DB: {len(db_urls)}")
        scraper_logger.info(f"--- End of Script ---")
        if 'db' in locals() and db.is_active:
            db.close()