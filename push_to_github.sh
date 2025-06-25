#!/bin/bash

# Ensure you are in the project root directory
# cd ~/CombinedNiftyNewsApp # Uncomment if running from outside the directory

# --- Safety Check: Ensure this is not an existing unrelated git repo ---
if [ -d ".git" ]; then
    read -p "A .git directory already exists. Do you want to remove it and reinitialize? (y/N): " confirm_remove_git
    if [[ "$confirm_remove_git" == "y" || "$confirm_remove_git" == "Y" ]]; then
        echo "Removing existing .git directory..."
        rm -rf .git
    else
        echo "Aborting. Please handle the existing .git directory manually."
        exit 1
    fi
fi

# --- Initialize Git Repository ---
echo "Initializing new Git repository..."
git init -b main # Initialize with 'main' as the default branch

# --- Create/Update .gitignore ---
echo "Creating/Updating .gitignore file..."
cat > .gitignore << EOF
# Python
__pycache__/
*.py[cod]
*$py.class

# Virtual Environment
venv/
.venv/

# IDE / Editor specific
.vscode/
.idea/
*.swp
*.swo

# OS specific
.DS_Store
Thumbs.db

# Application specific
.env
app.log
# Logs from the scraper script (keep processed_google_queries.txt in repo if desired for tracking)
scraper_run_logs_and_processed_urls/*.log
scraper_run_logs_and_processed_urls/*.html 
news_data.db
news_data.db-journal

# Newsfetch specific (if egg-info was copied)
news_fetch.egg-info/

# Distribution / packaging
dist/
build/
*.egg-info/
*.egg

# Other temporary files
*.tmp
*.bak
EOF
echo ".gitignore created/updated."

# --- Create/Update README.md ---
echo "Creating/Updating README.md..."
# (Copy the full README.md content from above into the EOL block)
cat > README.md << 'EOL'
# Nifty News Sentiment Analyzer (Enhanced with Local Scraping & DB)

This web application performs sentiment analysis on news related to selected Nifty sectors and their constituent stocks. It now primarily utilizes a **custom web scraping pipeline** to build and maintain a local news database, reducing reliance on external APIs for data acquisition. Sentiment analysis is performed using NLTK's VADER and Google Gemini for Large Language Model (LLM) based insights.

## Core Features

-   **Local News Database:**
    -   Employs a Python script (`scrape_financial_news_db.py`) using an embedded `news-fetch`-style library (`utils/newsfetch_lib/`) for data acquisition.
    -   Uses Selenium (with `undetected-chromedriver` attempts) for Google Search to find article URLs based on Nifty sectors, stocks, and user-defined date ranges.
    -   Extracts article content using `news-please` and `newspaper4k`.
    -   Stores scraped articles in a local SQLite database (`news_data.db`) via SQLAlchemy.
-   **Sentiment Analysis:**
    -   **VADER:** Lexical sentiment scoring for individual articles.
    -   **Google Gemini LLM:** Contextual analysis on articles retrieved from the local database, providing:
        -   Overall sentiment scores and labels for sectors/stocks.
        -   Concise summaries.
        -   Sentiment reasoning.
        -   Key themes, potential impacts, companies in context, risks, and opportunities.
-   **Interactive Web Interface:**
    -   Built with Flask (backend) and vanilla JavaScript with Chart.js (frontend).
    -   Allows users to configure analysis parameters:
        -   Date range for news analysis.
        -   News lookback period.
        -   Nifty sectors and (subsequently) constituent stocks.
        -   Maximum articles per entity for LLM processing.
        -   Custom instructions for the LLM.
    -   Dynamically displays sentiment scores (charts) and detailed LLM insights based on data from the local database.
-   **Configuration & Logging:**
    -   API keys (Gemini) and Database URL managed via `.env` and `config.py`.
    -   Server-side session management for temporary API key updates via UI.
    -   Comprehensive backend logging for both the Flask app and the scraper script.
    -   UI logging for user feedback during processing.

## Project Goal Evolution

The project initially relied on NewsAPI.org. It has been significantly enhanced to build its own news corpus. This provides:
-   Access to a broader range of historical data (once scraped).
-   Reduced dependency on rate limits and data freshness constraints of free/paid news APIs.
-   Greater control over the data acquisition pipeline.
-   A richer dataset for potential future backtesting features.

## Project Structure (`CombinedNiftyNewsApp/`)

-   `app.py`: Main Flask application.
-   `scrape_financial_news_db.py`: Script for bulk scraping news into the database.
-   `config.py`: Loads configuration from `.env`.
-   `.env`: (User-created) Stores API keys, `DATABASE_URL`.
-   `requirements.txt`: Python dependencies.
-   `static/`: CSS and JavaScript files.
-   `templates/`: HTML templates.
-   `utils/`:
    -   `database_models.py`: SQLAlchemy models for the news database.
    -   `db_crud.py`: Functions for database interaction.
    -   `gemini_utils.py`: Gemini LLM interaction logic and `NIFTY_SECTORS_QUERY_CONFIG`.
    -   `sentiment_analyzer.py`: VADER sentiment calculation.
    -   `newsfetch_lib/`: Embedded library for news fetching and parsing.
        -   `google.py`: Selenium-based Google Search URL extractor.
        -   `news.py`: Core `Newspaper` class for article processing.
        -   (and other handlers/helpers)
-   `news_data.db`: SQLite database file (created by scripts).
-   `scraper_run_logs_and_processed_urls/`: Logs and tracking files for the scraper.

## Setup Instructions

1.  **Prerequisites:**
    *   Git
    *   Python 3.9+ & pip
    *   Google Chrome browser installed.
    *   `chromedriver` compatible with your Chrome version (ensure it's in your system's PATH, or configure `utils/newsfetch_lib/google.py` to use `webdriver-manager`).

2.  **Clone the Repository (if starting fresh):**
    ```bash
    git clone https://github.com/DipayanDasgupta/NiftySectoralAnalysis2.0.git
    cd NiftySectoralAnalysis2.0
    ```

3.  **Create and Activate Python Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Install Dependencies:**
    ```bash
    pip install --upgrade pip
    pip install -r requirements.txt
    # On first run, NLTK's VADER lexicon will be downloaded.
    # undetected-chromedriver might attempt to download a compatible chromedriver.
    ```

5.  **Configure API Keys and Database:**
    *   Create a file named `.env` in the project root.
    *   Add your API keys to the `.env` file in the following format:
        ```env
        GEMINI_API_KEY="your_actual_gemini_api_key"
        FLASK_SECRET_KEY="a_very_strong_random_secret_key_please_change_this"
        DATABASE_URL="sqlite:///./news_data.db" 
        # Optional: YOUR_CHOSEN_SEARCH_API_KEY_NAME_IN_ENV="your_paid_search_api_key" (if using a paid search API)
        ```
    *   Replace placeholders with your real API keys.
    *   **Important:** Change `FLASK_SECRET_KEY` to a unique, strong random string.

6.  **Initialize Database & Populate with News:**
    *   First, ensure the database schema is created:
        ```bash
        python utils/database_models.py
        ```
    *   Then, run the scraper to populate the database. This is a long-running process.
        ```bash
        python scrape_financial_news_db.py
        ```
        You will be prompted to enter a start and end date for the news articles you wish to scrape.

7.  **Run the Flask Application:**
    ```bash
    python app.py
    ```
    Access at `http://localhost:5003` (or your configured port).

## Using the Application

1.  **API Keys:** Ensure your Gemini API key is in `.env` or update it via the UI for the session.
2.  **Data Source:** The application primarily uses the locally scraped data from `news_data.db`.
3.  **Analysis:**
    *   Select "Sector Sentiment Analysis" mode.
    *   Choose the "End Date for Analysis" and "News Lookback (Days)" that fall within the range of data you have scraped into your database.
    *   Select sectors.
    *   Click "Run Sector Analysis".
    *   Once sector results are displayed, you can select constituent stocks for that sector and click the "Run Analysis for Selected Stocks" button that appears within that sector's results.
4.  **View Results:** Charts and detailed LLM/VADER insights will be displayed. The UI log shows processing steps.

## Key Challenges & Notes

-   **Google Search Scraping:** Directly scraping Google Search is challenging due to CAPTCHAs and bot detection. The integrated `GoogleSearchNewsURLExtractor` attempts mitigations but may still be blocked. For robust, high-volume URL acquisition, using a paid Google Search API is recommended as a future enhancement. Inspect `uc_google_captcha_page...html` files if created during scraping.
-   **Data Volume:** The effectiveness of the dashboard depends on the amount and relevance of data in `news_data.db`. Regular runs of `scrape_financial_news_db.py` are needed to keep it populated.
-   **LLM Costs:** Be mindful of Google Gemini API usage costs.

## Future Enhancements

-   Integration of a reliable paid Google Search API.
-   Implementation of a Nifty 50 Backtester module.
-   Asynchronous scraping tasks triggered from the Flask app for near real-time updates.
-   Advanced database querying and full-text search capabilities.
EOL
echo "README.md created/updated."

# --- Git Operations ---
echo "Adding files to Git..."
git add .gitignore
git add README.md
git add . # Add all other files

echo "Committing files..."
git commit -m "Initial commit of Combined Nifty News Sentiment Analyzer with integrated scraper"

echo "Adding remote origin..."
# IMPORTANT: Replace with your actual repository URL if different
# This assumes your GitHub username is DipayanDasgupta and repo is NiftySectoralAnalysis2.0
# If the repo NiftySectoralAnalysis2.0 doesn't exist yet on GitHub, create it first (empty).
# If it exists and has history, this push might fail or require a force push.
# For a clean new repo, this should be fine.
REPO_URL="https://github.com/DipayanDasgupta/NiftySectoralAnalysis2.0.git"
git remote add origin "$REPO_URL"

echo "Pushing to GitHub (main branch)..."
# If your default branch on GitHub is 'master', change 'main' to 'master'
# Using -u sets the upstream branch for future pushes
git push -u origin main 

echo ""
echo "---------------------------------------------------------------------"
echo "All files should now be pushed to your GitHub repository: $REPO_URL"
echo "Remember to create the .env file locally with your API keys - it's ignored by Git."
echo "---------------------------------------------------------------------"