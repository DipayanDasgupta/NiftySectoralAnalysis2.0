# config.py
import os
from dotenv import load_dotenv

load_dotenv() 

NEWSAPI_ORG_API_KEY = os.getenv("NEWSAPI_ORG_API_KEY", "542f055d1d884394a2966a2519516efa")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyANBOTpHkdlpISgG6BLWuUmoKiB8t6ugJo") # Keep placeholder
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "ICICIPRU")
