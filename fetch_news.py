import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ddgs import DDGS


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

SEARCH_QUERY = "akwa ibom"

OUTPUT_FILE = Path("news.json")

# We only want the 10 most recent stories.
MAX_STORIES = 10

# Nigeria / English search region.
REGION = "ng-en"


# ------------------------------------------------------------
# NORMALIZE URL
# ------------------------------------------------------------

def normalize_url(url):
    """
    Remove query strings and fragments so that tracking
    URLs don't create duplicate stories.
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
# FETCH DUCKDUCKGO NEWS
# ------------------------------------------------------------

def fetch_news():

    print("Searching DuckDuckGo News for:", SEARCH_QUERY)

    stories = []

    seen_urls = set()

    with DDGS(timeout=20) as ddgs:

        results = ddgs.news(
            SEARCH_QUERY,
            region=REGION,
            safesearch="moderate",
            timelimit="d",
            max_results=MAX_STORIES * 3,
        )

        for item in results:

            title = clean_title(
                item.get("title", "")
            )

            url = item.get("url", "")

            if not title or not url:
                continue

            url = normalize_url(url)

            # Remove duplicate stories.
            if url in seen_urls:
                continue

            seen_urls.add(url)

            stories.append({
                "title": title,
                "url": url,
            })

            # Stop once we have the 10 newest
            # unique stories.
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

    stories = fetch_news()

    if not stories:

        raise RuntimeError(
            "No news stories were returned by DuckDuckGo."
        )

    save_results(stories)

    print(
        f"\nSuccessfully collected "
        f"{len(stories)} unique news stories.\n"
    )

    for number, story in enumerate(
        stories,
        start=1,
    ):

        print(
            f"{number}. {story['title']}"
        )

        print(
            f"   {story['url']}"
        )


if __name__ == "__main__":
    main()
