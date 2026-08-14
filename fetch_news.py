import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from difflib import SequenceMatcher

from ddgs import DDGS


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

SEARCH_QUERY = "akwa ibom"

OUTPUT_FILE = Path("news.json")

# Maximum number of stories in the final result.
MAX_STORIES = 10

# Search for news from the last day.
TIME_LIMIT = "d"

# Ask DuckDuckGo for more candidates than we finally need.
# This gives us room to remove duplicates.
CANDIDATE_STORIES = 40

REGION = "ng-en"


# ------------------------------------------------------------
# TEXT CLEANING
# ------------------------------------------------------------

def normalize_text(text):
    """
    Convert text to a simplified form for duplicate detection.
    """

    if not text:
        return ""

    text = text.lower()

    # Remove punctuation.
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Collapse repeated spaces.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def title_words(text):
    """
    Return useful words from a title.

    Very common words are ignored because they don't help
    determine whether two headlines describe the same story.
    """

    stop_words = {
        "the", "a", "an", "and", "or", "of", "to", "in",
        "on", "for", "with", "from", "by", "as", "at",
        "is", "are", "was", "were", "be", "been", "this",
        "that", "these", "those", "after", "before", "over",
        "into", "against", "their", "his", "her", "its",
        "new", "news"
    }

    words = normalize_text(text).split()

    return {
        word
        for word in words
        if word not in stop_words and len(word) > 2
    }


# ------------------------------------------------------------
# DUPLICATE DETECTION
# ------------------------------------------------------------

def stories_are_duplicates(story_a, story_b):
    """
    Decide whether two news results appear to report
    the same underlying story.

    We use both headline similarity and snippet similarity.
    This is deliberately conservative so unrelated stories
    aren't accidentally removed.
    """

    title_a = normalize_text(story_a.get("title", ""))
    title_b = normalize_text(story_b.get("title", ""))

    body_a = normalize_text(story_a.get("body", ""))
    body_b = normalize_text(story_b.get("body", ""))

    if not title_a or not title_b:
        return False

    # Very similar headlines.
    title_similarity = SequenceMatcher(
        None,
        title_a,
        title_b
    ).ratio()

    # Compare meaningful words in the headlines.
    words_a = title_words(title_a)
    words_b = title_words(title_b)

    if words_a and words_b:

        shared_words = words_a.intersection(words_b)

        smaller_set = min(
            len(words_a),
            len(words_b)
        )

        word_overlap = (
            len(shared_words) / smaller_set
            if smaller_set
            else 0
        )

    else:
        word_overlap = 0

    # Compare the news snippets supplied by DuckDuckGo.
    body_similarity = 0

    if body_a and body_b:

        body_similarity = SequenceMatcher(
            None,
            body_a,
            body_b
        ).ratio()

    # Rule 1:
    # Nearly identical headlines.
    if title_similarity >= 0.78:
        return True

    # Rule 2:
    # Different wording but most important headline words
    # are shared.
    if word_overlap >= 0.70 and title_similarity >= 0.50:
        return True

    # Rule 3:
    # Headlines may differ substantially while the
    # accompanying snippets are almost identical.
    if body_similarity >= 0.82:
        return True

    return False


# ------------------------------------------------------------
# URL NORMALIZATION
# ------------------------------------------------------------

def normalize_url(url):

    if not url:
        return ""

    parsed = urlparse(url)

    # Remove query strings and fragments, which often contain
    # tracking parameters.
    clean_url = parsed._replace(
        query="",
        fragment=""
    ).geturl()

    return clean_url.rstrip("/")


# ------------------------------------------------------------
# FETCH NEWS
# ------------------------------------------------------------

def fetch_news():

    print(
        f"Searching DuckDuckGo News for: {SEARCH_QUERY}"
    )

    candidates = []

    with DDGS(timeout=20) as ddgs:

        results = ddgs.news(
            SEARCH_QUERY,
            region=REGION,
            safesearch="moderate",
            timelimit=TIME_LIMIT,
            max_results=CANDIDATE_STORIES,
        )

        for item in results:

            title = item.get("title", "")
            url = item.get("url", "")
            body = item.get("body", "")
            date = item.get("date", "")
            source = item.get("source", "")

            if not title or not url:
                continue

            clean_url = normalize_url(url)

            if not clean_url:
                continue

            candidates.append({
                "title": title.strip(),
                "url": clean_url,
                "body": body.strip() if body else "",
                "date": date,
                "source": source,
            })

    print(
        f"DuckDuckGo returned {len(candidates)} candidates."
    )

    return candidates


# ------------------------------------------------------------
# REMOVE DUPLICATES
# ------------------------------------------------------------

def remove_duplicates(candidates):

    unique_stories = []

    seen_urls = set()

    for story in candidates:

        url = story["url"]

        # --------------------------------------------
        # Exact URL duplicate
        # --------------------------------------------

        if url in seen_urls:
            continue

        seen_urls.add(url)

        # --------------------------------------------
        # Same story from another publisher
        # --------------------------------------------

        duplicate = False

        for existing_story in unique_stories:

            if stories_are_duplicates(
                story,
                existing_story
            ):
                duplicate = True
                break

        if duplicate:
            print(
                "Duplicate removed:"
                f" {story['title']}"
            )
            continue

        unique_stories.append(story)

        # We can stop once we have the required maximum.
        if len(unique_stories) >= MAX_STORIES:
            break

    return unique_stories


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

def save_results(stories):

    # Keep the output simple.
    # RSS will later use only title and URL.

    output = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),

        "query": SEARCH_QUERY,

        "stories": [
            {
                "title": story["title"],
                "url": story["url"],
            }

            for story in stories
        ]
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

    candidates = fetch_news()

    stories = remove_duplicates(
        candidates
    )

    save_results(stories)

    print()
    print(
        f"Final result: {len(stories)} "
        f"unique news stories."
    )
    print()

    if not stories:

        print(
            "No qualifying news stories were found."
        )

        return

    for number, story in enumerate(
        stories,
        start=1
    ):

        print(
            f"{number}. {story['title']}"
        )

        print(
            f"   {story['url']}"
        )


if __name__ == "__main__":
    main()
