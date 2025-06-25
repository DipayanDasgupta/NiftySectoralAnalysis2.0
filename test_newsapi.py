# test_newsapi.py
from newsapi import NewsApiClient
from datetime import datetime, timedelta

# --- REPLACE WITH YOUR ACTUAL API KEY ---
NEWSAPI_KEY = "87de43db6453481c965b10abc58375b6"
# --- --------------------------------- ---

if NEWSAPI_KEY == "YOUR_NEWS_API_KEY_HERE" or not NEWSAPI_KEY:
    print("ERROR: Please replace 'YOUR_NEWS_API_KEY_HERE' with your actual NewsAPI.org key.")
else:
    print(f"Attempting to initialize NewsAPI client with key ending: ...{NEWSAPI_KEY[-4:]}")
    try:
        newsapi = NewsApiClient(api_key=NEWSAPI_KEY)

        # Make a simple test call to fetch top headlines from India
        print("\nFetching top headlines from India (IN)...")
        top_headlines = newsapi.get_top_headlines(
            # q='business', # Optional: add a keyword
            country='in',
            language='en',
            page_size=5  # Request a small number of articles
        )

        if top_headlines['status'] == 'ok':
            print(f"\nSUCCESS! API Key seems functional.")
            print(f"Total results available for this query: {top_headlines['totalResults']}")
            print(f"Fetched {len(top_headlines['articles'])} articles:")
            for i, article in enumerate(top_headlines['articles']):
                print(f"\n--- Article {i+1} ---")
                print(f"  Title: {article.get('title')}")
                print(f"  Source: {article.get('source', {}).get('name')}")
                print(f"  Published At: {article.get('publishedAt')}")
                # print(f"  Description: {article.get('description')}")
                # print(f"  URL: {article.get('url')}")
        else:
            print(f"\nAPI Error for get_top_headlines:")
            print(f"  Status: {top_headlines['status']}")
            print(f"  Code: {top_headlines.get('code')}")
            print(f"  Message: {top_headlines.get('message')}")
            if top_headlines.get('code') == 'apiKeyInvalid':
                print("  >>> Your API Key is INVALID. <<<")
            elif top_headlines.get('code') == 'apiKeyDisabled':
                print("  >>> Your API Key has been DISABLED. <<<")
            elif top_headlines.get('code') == 'rateLimited':
                print("  >>> You have been RATE LIMITED. Try again later. <<<")

        # Another test: Fetching everything for a keyword for yesterday
        # Note: /everything endpoint on free tier has limitations (e.g., news from last month only)
        print("\nFetching 'everything' for keyword 'India economy' for yesterday...")
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            all_articles = newsapi.get_everything(
                q='India economy',
                from_param=yesterday,
                to=yesterday,
                language='en',
                sort_by='relevancy',
                page_size=3
            )
            if all_articles['status'] == 'ok':
                print(f"\nSUCCESS! 'everything' endpoint also seems functional for recent dates.")
                print(f"Total results available for this query: {all_articles['totalResults']}")
                print(f"Fetched {len(all_articles['articles'])} articles:")
                for i, article in enumerate(all_articles['articles']):
                    print(f"  - {article.get('title')}")
            else:
                print(f"\nAPI Error for get_everything:")
                print(f"  Status: {all_articles['status']}")
                print(f"  Code: {all_articles.get('code')}")
                print(f"  Message: {all_articles.get('message')}")
                if 'dateInFuture' in all_articles.get('code',''):
                    print("  >>> The date might be considered in the future by the API or too far back.")
                elif 'sourcesMaximum' in all_articles.get('code',''):
                     print("  >>> Too many sources requested for free tier.")


        except Exception as e_everything:
            print(f"\nException during 'get_everything' call: {e_everything}")


    except Exception as e_client:
        print(f"\nFailed to initialize or use NewsAPI client: {e_client}")
        if "HTTP 401" in str(e_client) or "Unauthorised" in str(e_client) or "apiKeyInvalid" in str(e_client):
            print("  >>> This strongly suggests your API Key is INVALID or not properly authenticated. <<<")
        print("  Please double-check the API key and your NewsAPI.org account status.")