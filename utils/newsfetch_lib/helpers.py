import re
from collections import Counter

from unidecode import unidecode


def unicode(text: str) -> str:
    # Add a check for None in unicode as well, as it's called by headline property too
    if text is None:
        print("[helpers.py DEBUG] unicode received None, returning empty string.") # DEBUG
        return ""
    return unidecode(text).strip()


def clean_text(article):
    """Clean the article text by removing extra whitespace and newlines."""
    if article is None: # Added this check
        print("[helpers.py DEBUG] clean_text received None, returning empty string.") # DEBUG
        return "" # Return empty string; ensures re.sub doesn't get None
    # Remove extra whitespace and newlines
    cleaned_article = re.sub(r'\s+', ' ', article).strip()
    return cleaned_article


def extract_keywords(article):
    """Extract keywords from the article."""
    if not article: # Handle empty string or None from clean_text
        return []
    # Split the article into words
    words = re.findall(r'\b\w+\b', article.lower())
    # Count frequency of each word
    word_counts = Counter(words)
    # Filter out common stopwords (you can expand this list)
    stopwords = {'and', 'the', 'is', 'in', 'of', 'to', 'a', 'for', 'was', 'that', 'on', 'as', 'with', 'it', 'this',
                 'are', 'by', 'an'}
    keywords = {word: count for word, count in word_counts.items() if word not in stopwords}

    # Return keywords sorted by frequency
    return sorted(keywords.items(), key=lambda x: x[1], reverse=True)


def summarize_article(article, max_sentences=3):
    """Summarize the article by extracting the first few sentences."""
    if not article: # Handle empty string or None
        return ""
    sentences = re.split(r'(?<=[.!?]) +', article)
    summary = ' '.join(sentences[:max_sentences])  # Take the first few sentences
    return summary