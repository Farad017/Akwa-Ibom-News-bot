import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

SEARCH_QUERY = "akwa ibom"

DUCKDUCKGO_URL = (
    "https://duckduckgo.com/news.js"
    "?q=" + quote_plus(SEARCH_QUERY)
    "&o=json"
    "&noamp=1"
)

OUTPUT_FILE = Path("news.json")

MAX_STORIES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ------------------------------------------------------------
# DOWNLOAD DUCKDUCKGO NEWS
# ------------------------------------------------------------

def fetch_news():
    print("Fetching DuckDuckGo News...")

    response = requests.get(
        DUCKDUCKGO_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


# ------------------------------------------------------------
# NORMALIZE URL
# ------------------------------------------------------------

def normalize_url(url):
    """
    Remove tracking parameters so that the same article
    isn't treated as different stories because of tracking URLs.
    """

    parsed = urlparse(url)

    clean_url = parsed._replace(
        query="",
        fragment="",
    ).geturl()

    return clean_url.rstrip("/")


# ------------------------------------------------------------
# CLEAN TITLE
# ------------------------------------------------------------

def clean_title(title):
    if not title:
        return ""

    title = re.sub(r"\s+", " ", title)

    return title.strip()


# ------------------------------------------------------------
# EXTRACT STORIES
# ------------------------------------------------------------

def extract_stories(data):

    stories = []

    # DuckDuckGo's response can contain the news results
    # under different structures, so check the expected
    # news-results locations.

    possible_results = []

    if isinstance(data, dict):

        if isinstance(data.get("results"), list):
            possible_results.extend(data["results"])

        if isinstance(data.get("news"), list):
            possible_results.extend(data["news"])

        if isinstance(data.get("news_results"), list):
            possible_results.extend(data["news_results"])

    seen_urls = set()

    for item in possible_results:

        if not isinstance(item, dict):
            continue

        title = (
            item.get("title")
            or item.get("heading")
            or ""
        )

        url = (
            item.get("url")
            or item.get("link")
            or ""
        )

        title = clean_title(title)

        if not title or not url:
            continue

        url = normalize_url(url)

        if not url:
            continue

        # Remove duplicate stories.
        if url in seen_urls:
            continue

        seen_urls.add(url)

        stories.append({
            "title": title,
            "url": url,
        })

        # We only need the 10 most recent results.
        if len(stories) >= MAX_STORIES:
            break

    return stories


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

def save_results(stories):

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "query": SEARCH_QUERY,
        "stories": stories,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    data = fetch_news()

    stories = extract_stories(data)

    if not stories:
        raise RuntimeError(
            "No news stories were found in DuckDuckGo's response."
        )

    save_results(stories)

    print(
        f"Successfully collected {len(stories)} news stories."
    )

    for number, story in enumerate(stories, start=1):

        print(
            f"{number}. {story['title']}"
        )

        print(
            f"   {story['url']}"
        )


if __name__ == "__main__":
    main()
