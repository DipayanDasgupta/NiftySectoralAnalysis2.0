# Nifty News Sentiment Analyzer (Enhanced with Local Scraping & DB)

This web application performs sentiment analysis on news related to selected Nifty sectors and their constituent stocks. It now primarily utilizes a **custom web scraping pipeline** to build and maintain a local news database, reducing reliance on external APIs for data acquisition. Sentiment analysis is performed using NLTK's VADER and Google Gemini for Large Language Model (LLM) based insights.

## Core Features

-   **Local News Database:**
    -   Employs a Python script (`scrape_financial_news_db.py`) using an embedded `news-fetch`-style library (`utils/newsfetch_lib/`) for data acquisition.
    -   Uses Selenium (with `undetected-chromedriver`) for Google Search to find article URLs based on Nifty sectors, stocks, and user-defined date ranges.
    -   Extracts article content using `news-please` and `newspaper4k`.
    -   Stores scraped articles in a local SQLite database (`news_data.db`) via SQLAlchemy.
-   **Sentiment Analysis:**
    -   **VADER:** Lexical sentiment scoring for individual articles.
    -   **Google Gemini LLM:** Contextual analysis on articles retrieved from the local database (or NewsAPI as a fallback in ad-hoc mode), providing:
        -   Overall sentiment scores and labels for sectors/stocks.
        -   Concise summaries.
        -   Sentiment reasoning.
        -   Key themes, potential impacts, companies in context, risks, and opportunities.
-   **Interactive Web Interface:**
    -   Built with Flask (backend) and vanilla JavaScript with Chart.js (frontend).
    -   **Operation Modes:**
        -   **Batch Sector Analysis:** Analyzes multiple selected Nifty sectors using data from the local DB. Allows drill-down for stock-specific analysis within displayed sector results.
        -   **Ad-hoc Stock/Sector Analysis (+Scrape):** Focuses on a single user-defined stock or sector. Can optionally trigger a fresh, targeted scrape for the specified date range and domains, or use NewsAPI as a fallback. Displays rolling daily sentiment and (for stocks) price charts.
    -   Users can configure:
        -   Date range for news analysis/scraping.
        -   News source priority for ad-hoc mode.
        -   Maximum articles per entity for LLM processing.
        -   Custom instructions for the LLM.
-   **Configuration & Logging:**
    -   API keys (Gemini, NewsAPI) and Database URL managed via `.env` and `config.py`.
    -   Server-side session management for temporary API key updates via UI.
    -   Comprehensive backend logging for both the Flask app and the scraper script.
    -   UI logging for user feedback during processing.

## Project Goal Evolution

The project initially relied solely on NewsAPI.org. It has been significantly enhanced to build and utilize its own news corpus. This provides:
-   Access to a broader range of historical data (once scraped).
-   Reduced dependency on rate limits and data freshness constraints of free/paid news APIs for primary analysis.
-   Greater control over the data acquisition pipeline.
-   A richer dataset for potential future backtesting features.

## Project Structure (`CombinedNiftyNewsApp/`)

-   `app.py`: Main Flask application.
-   `scrape_financial_news_db.py`: Script for bulk scraping news into the database.
-   `config.py`: Loads configuration from `.env`.
-   `.env.example`: Example environment file. (User creates `.env`)
-   `requirements.txt`: Python dependencies.
-   `static/`: CSS (`style.css`) and JavaScript (`main.js`).
-   `templates/`: HTML template (`index.html`).
-   `utils/`:
    -   `database_models.py`: SQLAlchemy models for the news database.
    -   `db_crud.py`: Functions for database interaction.
    -   `gemini_utils.py`: Gemini LLM interaction logic and `NIFTY_SECTORS_QUERY_CONFIG`.
    -   `newsapi_helpers.py`: Logic for fetching news from NewsAPI.org (used as fallback).
    -   `sentiment_analyzer.py`: VADER sentiment calculation.
    -   `newsfetch_lib/`: Embedded library for news fetching and parsing.
        -   `google.py`: Selenium-based Google Search URL extractor (uses `undetected-chromedriver`).
        -   `news.py`: Core `Newspaper` class for article processing (orchestrates `news-please`, `newspaper4k`).
        -   (and other handlers/helpers)
-   `news_data.db`: SQLite database file (created by scripts/app on first run).
-   `scraper_run_logs_and_processed_urls/`: Logs and tracking files for the bulk scraper.
-   `google_captcha_pages/`: Directory where HTML of CAPTCHA/block pages encountered by `google.py` are saved.

## Setup Instructions

1.  **Prerequisites:**
    *   Git
    *   Python 3.9+ & pip
    *   Google Chrome browser installed (ensure it's reasonably up-to-date).
    *   `undetected-chromedriver` will attempt to download a compatible `chromedriver`. Ensure you have permissions for it to write to its cache directory (usually `~/.local/share/undetected_chromedriver/`).

2.  **Clone the Repository (if starting fresh):**
    ```bash
    git clone https://github.com/DipayanDasgupta/NiftySectoralAnalysis2.0.git # Or your repo URL
    cd NiftySectoralAnalysis2.0 
    ```

3.  **Create and Activate Python Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

4.  **Install Dependencies:**
    ```bash
    pip install --upgrade pip
    pip install -r requirements.txt
    # On first run, NLTK's VADER lexicon and other resources might be downloaded.
    ```

5.  **Configure API Keys and Database:**
    *   Copy `.env.example` to `.env` (if an example file is provided) or create a new file named `.env` in the project root.
    *   Add your API keys and other settings to the `.env` file:
        ```env
        GEMINI_API_KEY="your_actual_gemini_api_key"
        NEWSAPI_ORG_API_KEY="your_actual_newsapi_key" # Required for NewsAPI fallback in ad-hoc mode
        FLASK_SECRET_KEY="a_very_strong_random_secret_key_please_change_this_immediately"
        DATABASE_URL="sqlite:///./news_data.db" # Default SQLite in project root
        # Optional: For overriding default scraper delays in config.py
        # APP_SCRAPER_SEARCH_DELAY_GOOGLE=5
        # APP_SCRAPER_ARTICLE_FETCH_DELAY=2 
        ```
    *   Replace placeholders with your real API keys.
    *   **Important:** Change `FLASK_SECRET_KEY` to a unique, strong random string.

6.  **Initialize Database & Populate with News (Optional but Recommended for Batch Mode):**
    *   The database schema (`news_data.db`) will be created automatically when `scrape_financial_news_db.py` or `app.py` is run for the first time if the DB file doesn't exist.
    *   To populate the database with a significant amount of news for the "Batch Sector Analysis" mode, run the bulk scraper:
        ```bash
        python scrape_financial_news_db.py
        ```
        You will be prompted to enter a start and end date for the news articles you wish to scrape. This can be a long-running process depending on the date range and number of keywords.

7.  **Run the Flask Application:**
    ```bash
    python app.py
    ```
    Access at `http://localhost:5003` (or your configured port).

## Using the Application

1.  **API Keys:** Ensure your Gemini and NewsAPI.org API keys are correctly set in your `.env` file. You can also temporarily update them for your current browser session via the UI.
2.  **Operation Modes:**
    *   **Batch Sector Analysis:**
        *   Select this mode.
        *   Choose a "Start Date" and "End Date" for analysis (ensure data exists in your `news_data.db` for this range if you've run the bulk scraper).
        *   Select one or more Nifty sectors.
        *   Set LLM parameters (max articles, custom prompt).
        *   Click "Run Operation". Sector-level sentiment charts and LLM analysis will appear.
        *   Within each sector's result, you can select constituent stocks and click "Analyze Selected Stocks" for a more granular analysis using the same date range and LLM parameters.
    *   **Ad-hoc Stock/Sector Analysis (+Scrape):**
        *   Select this mode.
        *   Choose "Target Type" (Stock or Sector).
        *   Enter the "Target Name/Ticker".
        *   Select "Start Date" and "End Date".
        *   Choose "News Source Priority":
            *   `Local DB first, then NewsAPI`: Recommended.
            *   `Local DB Only`: Only uses your scraped data.
            *   `NewsAPI.org Only`: Directly queries NewsAPI (useful for very recent news if DB isn't fresh).
        *   Optionally, check "Trigger Fresh Scrape..." and provide domains if you want the app to attempt a *small, quick scrape* for the target and date range before analysis. **Use with caution for short date ranges due to potential CAPTCHAs.**
        *   Set LLM parameters.
        *   Click "Run Operation". Results will include an LLM analysis, a table of articles used, and a chart showing daily VADER sentiment (and stock price if applicable).

## Key Challenges & Notes

-   **Google Search Scraping (for `scrape_financial_news_db.py` and ad-hoc scrape):** Directly scraping Google Search is highly prone to CAPTCHAs and IP blocks. The integrated `GoogleSearchNewsURLExtractor` uses `undetected-chromedriver` and various techniques to mitigate this, but success is not guaranteed and can vary.
    -   Inspect files in the `google_captcha_pages/` directory if scraping yields no URLs; these HTML files show what Google returned (e.g., a CAPTCHA page).
    -   For robust, high-volume URL acquisition for the bulk scraper, a paid Google Search API (like SerpApi) or a commercial scraping service that handles CAPTCHAs would be a more reliable long-term solution.
-   **Data Volume & Quality:** The effectiveness of the "Batch Sector Analysis" mode heavily depends on the amount and relevance of data populated into `news_data.db` by `scrape_financial_news_db.py`. Regular runs of the bulk scraper are needed to build and maintain this corpus.
-   **LLM & NewsAPI Costs:** Be mindful of API usage costs for Google Gemini and NewsAPI.org (if used frequently as a fallback or primary source in ad-hoc mode).
-   **Synchronous On-Demand Scrape:** The "Trigger Fresh Scrape" feature in the ad-hoc mode runs synchronously within the Flask request. It's intended for very small, targeted scrapes (e.g., 1-2 domains, short date range). Longer scrapes will cause the UI to hang.

## Future Enhancements

-   Integration of a reliable paid Search API for the bulk scraper.
-   Implementation of a Nifty 50 Backtester module using historical sentiment and price data.
-   Asynchronous task queue (e.g., Celery with Redis/RabbitMQ) for on-demand scraping from the Flask app to prevent UI blocking.
-   More sophisticated data visualization and dashboarding features.
-   User account management and saved preferences.