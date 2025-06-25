# utils/newsapi_helpers.py
import logging
from newsapi import NewsApiClient
import time
from datetime import timedelta
from .sentiment_analyzer import get_vader_sentiment_score # Assuming sentiment_analyzer.py is in the same utils directory

logger = logging.getLogger(__name__)

def get_newsapi_org_client(api_key, append_log_func=None):
    log_msg_prefix = "[NewsAPIHelper]"
    
    def _log(message, level='info'):
        full_message = f"{log_msg_prefix} {message}"
        if level.lower() == 'error': logger.error(full_message)
        elif level.lower() == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())

    if not api_key or api_key == "YOUR_NEWSAPI_ORG_API_KEY_HERE":
        msg = "NewsAPI.org key is missing or a placeholder. Client not initialized."
        _log(msg, 'warning')
        return None, msg
    try:
        client = NewsApiClient(api_key=api_key)
        _log("NewsAPI.org client initialized successfully.")
        return client, None
    except Exception as e:
        err_msg = f"Failed to initialize NewsAPI.org client: {e}"
        _log(err_msg, 'error')
        return None, str(e)


def _process_newsapi_response(
    response_articles,
    max_articles_to_return,
    from_date_str_for_fallback, 
    log_func # Pass the _log function for contextual logging
):
    """Helper function to process articles from NewsAPI response."""
    articles_data = []
    unique_urls = set()
    for article in response_articles:
        if len(articles_data) >= max_articles_to_return:
            if log_func: log_func(f"Reached max_articles_to_return limit ({max_articles_to_return}).", "INFO")
            break
        
        url = article.get('url')
        if url in unique_urls:
            if log_func: log_func(f"Skipping duplicate URL: {url}", "DEBUG")
            continue
        if url: unique_urls.add(url)

        title = article.get('title', "") or ""
        description = article.get('description', "") or ""
        
        content_for_llm = title
        if description:
            if title and not title.endswith(('.', '!', '?')):
                content_for_llm += ". " + description
            else:
                content_for_llm += " " + description
        
        content_for_llm_stripped = content_for_llm.strip()
        
        if content_for_llm_stripped and content_for_llm_stripped != ".":
            vader_score = get_vader_sentiment_score(content_for_llm_stripped)
            articles_data.append({
                'content': content_for_llm_stripped,
                'date': article.get('publishedAt', from_date_str_for_fallback).split('T')[0],
                'uri': url or '',
                'source': article.get('source', {}).get('name', 'N/A'),
                'vader_score': vader_score
            })
    return articles_data


def fetch_sector_news_newsapi(
    newsapi_client,
    sector_name, 
    sector_keywords_list, 
    country_keywords_list, 
    from_date_obj,
    to_date_obj,
    max_articles_to_fetch=20, 
    append_log_func=None
):
    log_msg_prefix_local = f"[NewsAPIHelper][Sector: {sector_name}]"

    # Define a local _log to pass to _process_newsapi_response for better context
    def _local_log(message, level='info'):
        full_message = f"{log_msg_prefix_local} {message}"
        if level.lower() == 'error': logger.error(full_message)
        elif level.lower() == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())


    if not newsapi_client:
        msg = "NewsAPI client not available for fetching sector news."
        _local_log(msg, 'warning')
        return [], msg

    sector_query_part = f"({' OR '.join(f'\"{k.strip()}\"' for k in sector_keywords_list if k.strip())})"
    country_query_part = f"({' OR '.join(f'\"{k.strip()}\"' for k in country_keywords_list if k.strip())})"
    
    query_string = f"{sector_query_part} AND {country_query_part}" if sector_query_part != "()" and country_query_part != "()" else sector_query_part if country_query_part == "()" else country_query_part
    
    if query_string == "()" or query_string == " AND " or not query_string.strip():
        _local_log("No valid keywords for sector query construction.", "warning")
        return [], "No valid keywords provided for NewsAPI sector query."

    from_date_str = from_date_obj.strftime('%Y-%m-%d')
    to_date_str = to_date_obj.strftime('%Y-%m-%d')
    
    articles_data = []
    error_message_user = None
    page_size_for_api = min(max_articles_to_fetch, 100)

    _local_log(f"Fetching SECTOR news with query: '{query_string}', From: {from_date_str}, To: {to_date_str}, PageSize: {page_size_for_api}", "debug")

    try:
        all_articles_response = newsapi_client.get_everything(
            q=query_string,
            from_param=from_date_str,
            to=to_date_str,
            language='en',
            sort_by='relevancy', 
            page_size=page_size_for_api
        )

        if all_articles_response['status'] == 'ok':
            fetched_api_articles = all_articles_response['articles']
            _local_log(f"API returned {all_articles_response['totalResults']} total results, received {len(fetched_api_articles)} articles in this call for sector.", "info")
            
            articles_data = _process_newsapi_response(
                fetched_api_articles, 
                max_articles_to_fetch, 
                from_date_str, 
                _local_log 
            )
            _local_log(f"Processed and returning {len(articles_data)} unique articles for LLM for sector '{sector_name}'.", "info")
        else:
            api_err_code = all_articles_response.get('code', 'N/A')
            api_err_msg = all_articles_response.get('message', 'Unknown NewsAPI error')
            error_message_user = f"NewsAPI.org Error for sector '{sector_name}': {api_err_msg} (Code: {api_err_code})"
            _local_log(error_message_user, 'error')
            if api_err_code == 'rateLimited':
                _local_log("Rate limited by NewsAPI. Consider pausing or reducing request frequency.", 'warning')
            elif 'too far in the past' in api_err_msg.lower() or 'maximumAllowedDate' in api_err_code: # Corrected key
                _local_log("Query date range might be too old for NewsAPI free/developer tier.", 'warning')
                error_message_user = f"NewsAPI: Date range too old ({from_date_str} to {to_date_str}). Max is usually ~30 days back for free tier."

    except Exception as e:
        err_msg = f"An exception occurred during NewsAPI fetch for sector '{sector_name}': {str(e)[:150]}"
        _local_log(err_msg, 'error')
        logger.exception(f"{log_msg_prefix_local} Full NewsAPI Fetch Exception for Sector")
        error_message_user = f"NewsAPI.org fetch exception for sector '{sector_name}': {str(e)[:100]}"
    
    time.sleep(1.2) 
    return articles_data, error_message_user


def fetch_stock_news_newsapi(
    newsapi_client,
    stock_name, 
    stock_specific_keywords, 
    country_keywords_list, 
    from_date_obj,
    to_date_obj,
    max_articles_to_fetch=5, 
    append_log_func=None
):
    log_msg_prefix_local = f"[NewsAPIHelper][Stock: {stock_name}]"

    def _local_log(message, level='info'): # Local log function for this scope
        full_message = f"{log_msg_prefix_local} {message}"
        if level.lower() == 'error': logger.error(full_message)
        elif level.lower() == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())


    if not newsapi_client:
        msg = f"NewsAPI client not available for fetching news for stock '{stock_name}'."
        _local_log(msg, 'warning')
        return [], msg

    stock_query_part = f"({' OR '.join(f'\"{k.strip()}\"' for k in stock_specific_keywords if k.strip())})"
    country_query_part = f"({' OR '.join(f'\"{k.strip()}\"' for k in country_keywords_list if k.strip())})"

    query_string = f"{stock_query_part} AND {country_query_part}" if stock_query_part != "()" and country_query_part != "()" else stock_query_part if country_query_part == "()" else country_query_part

    if query_string == "()" or query_string == " AND " or not query_string.strip(): 
        _local_log(f"No valid keywords for stock query construction for '{stock_name}'.", "warning")
        return [], f"No valid keywords provided for NewsAPI query for stock '{stock_name}'."

    from_date_str = from_date_obj.strftime('%Y-%m-%d')
    to_date_str = to_date_obj.strftime('%Y-%m-%d')
    
    articles_data = []
    error_message_user = None
    page_size_for_api = min(max_articles_to_fetch, 100) 

    _local_log(f"Fetching STOCK news with query: '{query_string}', From: {from_date_str}, To: {to_date_str}, PageSize: {page_size_for_api}", "debug")
    
    try:
        all_articles_response = newsapi_client.get_everything(
            q=query_string,
            from_param=from_date_str,
            to=to_date_str,
            language='en',
            sort_by='relevancy', 
            page_size=page_size_for_api
        )

        if all_articles_response['status'] == 'ok':
            fetched_api_articles = all_articles_response['articles']
            _local_log(f"API returned {all_articles_response['totalResults']} total results, received {len(fetched_api_articles)} articles in this call for stock '{stock_name}'.", "info")
            
            articles_data = _process_newsapi_response(
                fetched_api_articles,
                max_articles_to_fetch,
                from_date_str,
                _local_log 
            )
            _local_log(f"Processed and returning {len(articles_data)} unique articles for LLM for stock '{stock_name}'.", "info")
        else:
            api_err_code = all_articles_response.get('code', 'N/A')
            api_err_msg = all_articles_response.get('message', 'Unknown NewsAPI error')
            error_message_user = f"NewsAPI.org Error for stock '{stock_name}': {api_err_msg} (Code: {api_err_code})"
            _local_log(error_message_user, 'error')
            if api_err_code == 'rateLimited':
                _local_log("Rate limited by NewsAPI. Consider pausing or reducing request frequency.", 'warning')
            elif 'too far in the past' in api_err_msg.lower() or 'maximumAllowedDate' in api_err_code:
                _local_log("Query date range might be too old for NewsAPI free/developer tier.", 'warning')
                error_message_user = f"NewsAPI: Date range too old ({from_date_str} to {to_date_str}). Max is usually ~30 days back for free tier."


    except Exception as e:
        err_msg = f"An exception occurred during NewsAPI fetch for stock '{stock_name}': {str(e)[:150]}"
        _local_log(err_msg, 'error')
        logger.exception(f"{log_msg_prefix_local} Full NewsAPI Fetch Exception for Stock")
        error_message_user = f"NewsAPI.org fetch exception for stock '{stock_name}': {str(e)[:100]}"
    
    time.sleep(1.2) 
    return articles_data, error_message_user