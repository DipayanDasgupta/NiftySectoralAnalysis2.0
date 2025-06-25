# ~/CombinedNiftyNewsApp/test_newspaper_direct.py
from newspaper import Article 
import newspaper # To print version and path

# Try a very stable, simple news URL from a major international source for testing the library itself
test_url = "https://www.bbc.com/news/world-us-canada-58084939" # Example BBC article (replace with a current one if old)
# Or try a very current one from a known working site for newspaper4k
# test_url = "YOUR_TEST_URL_HERE_FROM_A_RELIABLE_NEWS_SITE"

print(f"Newspaper library path: {newspaper.__file__}")
print(f"Newspaper library version: {newspaper.__version__ if hasattr(newspaper, '__version__') else 'N/A'}")
print(f"Attempting to process URL with newspaper library: {test_url}")
try:
    article = Article(url=test_url, fetch_images=False, memoize_articles=False, request_timeout=15) # Added timeout
    print("Article object initialized.")
    article.download()
    print(f"Download HTML (first 200): {article.html[:200] if article.html else 'No HTML'}")
    print(f"Download status code: {article.download_state} (0=ND, 1=FS, 2=SS) ") # FS=FETCH_SUCCESS, SS=SUCCESS
    print(f"Download exception message if any: {getattr(article, 'download_exception_msg', 'None')}")
    
    if article.download_state == 2 or (article.html and not getattr(article, 'download_exception_msg', None)): # Check if download looks okay
        article.parse()
        print(f"Parse attempted. is_parsed: {article.is_parsed}")
        if article.is_parsed:
            print(f"Title: {article.title}")
            print(f"Text (first 200 chars): {article.text[:200] if article.text else 'No text extracted'}")
        else:
            print("Article could not be parsed despite download attempt.")
    else:
        print(f"Skipping parse because download failed or did not complete. Status: {article.download_state}")

except Exception as e:
   print(f"An error occurred: {e}")
   import traceback
   traceback.print_exc()