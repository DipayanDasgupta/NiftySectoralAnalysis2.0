# ~/CombinedNiftyNewsApp/utils/newsfetch_lib/google.py
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# from webdriver_manager.chrome import ChromeDriverManager # Optional
import time
import logging
import urllib.parse

# Use a logger that can be configured by the calling script
logger = logging.getLogger("utils.newsfetch_lib.google") # Matches the logger name in scraper

class GoogleSearchNewsURLExtractor:
    """Extracts news article URLs from Google search results based on a keyword and site."""

    def __init__(self, keyword, news_domain, start_date_str=None, end_date_str=None, lang="en", country_code="IN", num_pages=1):
        """
        Initialize with the search keyword, target newspaper URL, and optional date strings.
        start_date_str and end_date_str should be in 'MM/DD/YYYY' format for Google's tbs.
        lang: language for search results (e.g., 'en' for English)
        country_code: country for search results (e.g., 'US', 'IN') - affects gl= parameter
        num_pages: number of Google search result pages to attempt to scrape
        """
        self.keyword = keyword
        self.news_domain = news_domain
        self.start_date_str = start_date_str 
        self.end_date_str = end_date_str   
        self.lang = lang
        self.country_code = country_code
        self.num_pages = num_pages 
        self.urls = []
        self.raw_html_for_debug = ""

        logger.info(f"[GoogleSearch] Init - Keyword: '{keyword}', Domain: '{news_domain}', Dates: {start_date_str}-{end_date_str}, Pages: {num_pages}")
        self._fetch_urls() # Call the internal method to perform the search


    def _build_search_url(self, start_index=0):
        search_query_components = [f"'{self.keyword}'", f"site:{self.news_domain}"]
        search_term_for_q = " ".join(search_query_components)
        encoded_query = urllib.parse.quote_plus(search_term_for_q)
        
        search_url = f"https://www.google.com/search?q={encoded_query}&hl={self.lang}&gl={self.country_code}&lr=lang_{self.lang}"

        if self.start_date_str and self.end_date_str:
            date_filter_param = f"&tbs=cdr:1,cd_min:{self.start_date_str},cd_max:{self.end_date_str}"
            search_url += date_filter_param
        
        if start_index > 0:
            search_url += f"&start={start_index}"
            
        return search_url

    def _extract_links_from_page(self, driver):
        xpaths_to_try = [
            "//div[contains(@class,'MjjYud')]//h3/ancestor::a[@href]",        
            "//div[@class='yuRUbf']/a[@href]",                               
            "//div[contains(@class,'g ')]//div[contains(@class,'yuRUbf')]/a", 
            "//div[@id='search']//div[contains(@class,'g')]//a[@href and .//h3]", 
            "//a[.//h3]"                                                     
        ]
        
        page_urls = []
        for i, xpath in enumerate(xpaths_to_try):
            try:
                WebDriverWait(driver, 3).until( # Shorter wait for presence
                    EC.presence_of_element_located((By.XPATH, xpath.split('[')[0] if '[' in xpath else xpath)) 
                )
                link_elements = driver.find_elements(By.XPATH, xpath)
                if link_elements:
                    logger.debug(f"[GoogleSearch] Found {len(link_elements)} elements with XPath index {i}: {xpath}")
                    for link_element in link_elements:
                        href = link_element.get_attribute("href")
                        if href:
                            parsed_url = urllib.parse.urlparse(href)
                            if self.news_domain in parsed_url.netloc and \
                            not parsed_url.netloc.startswith("www.google.") and \
                            not parsed_url.netloc.startswith("google.") and \
                            not parsed_url.netloc.startswith("accounts.google."):
                                page_urls.append(href)
                            else:
                                logger.debug(f"[GoogleSearch] Skipping URL from different/Google service domain: {href}")
                    if page_urls: 
                        break 
            except Exception as e_xpath:
                logger.debug(f"[GoogleSearch] XPath index {i} ('{xpath}') failed or timed out: {e_xpath}")
        
        if not page_urls:
            logger.warning(f"[GoogleSearch] No link elements found with any common XPaths. Page title: '{driver.title}'.")
            # Save HTML only if it's the first page attempt and no URLs collected yet overall
            if not self.urls and hasattr(driver, 'page_source'): 
                self.raw_html_for_debug = driver.page_source
                try:
                    with open("google_search_debug_page.html", "w", encoding="utf-8") as f_debug:
                        f_debug.write(self.raw_html_for_debug)
                    logger.warning("[GoogleSearch] Saved page source to google_search_debug_page.html for review.")
                except Exception as e_file:
                    logger.error(f"[GoogleSearch] Error saving debug HTML: {e_file}")

        return list(dict.fromkeys(page_urls))

    def _fetch_urls(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1200")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument(f"--lang={self.lang}") # Pass lang to Chrome options

        driver = None
        try:
            # For explicit chromedriver path:
            # service = ChromeService(executable_path='/path/to/your/chromedriver')
            # driver = webdriver.Chrome(service=service, options=options)
            driver = webdriver.Chrome(options=options) # Assumes chromedriver is in PATH
            
            # This script might not always work or could be detected
            # driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            all_found_urls_this_instance = []
            for page_num in range(self.num_pages):
                start_index = page_num * 10
                current_search_url = self._build_search_url(start_index)
                logger.info(f"[GoogleSearch] Fetching page {page_num + 1}/{self.num_pages}: {current_search_url}")
                
                driver.get(current_search_url)
                # Dynamic wait based on page content - wait for search results container or a known element
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, "search")) # Common ID for search results area
                    )
                except Exception as e_wait:
                    logger.warning(f"[GoogleSearch] Timed out waiting for search results container: {e_wait}. Page title: {driver.title}")
                    # Check for CAPTCHA if main content not found
                
                # Basic CAPTCHA check
                page_title_lower = driver.title.lower()
                page_source_lower = driver.page_source.lower()
                if "recaptcha" in page_source_lower or "требуется ввести символы" in page_source_lower \
                   or "unusual traffic" in page_title_lower or "访问验证" in page_title_lower:
                    logger.error(f"[GoogleSearch] CAPTCHA or unusual traffic page detected at URL: {driver.current_url}. Title: {driver.title}. Aborting this query.")
                    try:
                        with open(f"google_captcha_page_kwd_{self.keyword.replace(' ','_')}_dom_{self.news_domain.replace('.','_')}_{page_num}.html", "w", encoding="utf-8") as f_capt:
                            f_capt.write(driver.page_source)
                        logger.error(f"Saved CAPTCHA page source for debugging.")
                    except Exception as e_file_capt:
                         logger.error(f"Error saving CAPTCHA page HTML: {e_file_capt}")
                    break 

                page_specific_urls = self._extract_links_from_page(driver)
                all_found_urls_this_instance.extend(page_specific_urls)
                
                if not page_specific_urls:
                    logger.warning(f"[GoogleSearch] Page {page_num + 1} yielded no processable results. Not trying further pages for this query.")
                    break 
                
                if page_num < self.num_pages - 1 and len(page_specific_urls) > 0 : # Only sleep if we got results and expect more pages
                    time.sleep(2 + page_num) # Small increasing delay before fetching next page
                elif not page_specific_urls: # if this page had no urls, no need to wait long for next (which wont be fetched)
                    break


            if all_found_urls_this_instance:
                self.urls = [url for url in list(dict.fromkeys(all_found_urls_this_instance)) if url and ".pdf" not in url.lower() and ".xml" not in url.lower()]
            
            logger.info(f"[GoogleSearch] Final filtered to {len(self.urls)} unique, valid URLs after attempting {self.num_pages} page(s).")

        except Exception as e:
            logger.error(f"[GoogleSearch] Critical error during URL fetching: {e}", exc_info=True)
            if driver and hasattr(driver, 'page_source'):
                try:
                    with open(f"google_critical_error_page_kwd_{self.keyword.replace(' ','_')}_dom_{self.news_domain.replace('.','_')}.html", "w", encoding="utf-8") as f_err_debug:
                        f_err_debug.write(driver.page_source)
                    logger.error("[GoogleSearch] Saved page source on critical error for debugging.")
                except Exception as e_file_crit:
                    logger.error(f"Error saving critical error page HTML: {e_file_crit}")
        finally:
            if driver:
                driver.quit()
                logger.debug("[GoogleSearch] WebDriver quit.")