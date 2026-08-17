import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


QUERY = "akwa ibom"
MAX_STORIES = 10
LOOKBACK_HOURS = 24
MAX_CANDIDATES = 40

OUTPUT_FILE = "news.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


# Words/phrases that strongly indicate that the article is genuinely
# about Akwa Ibom rather than merely mentioning it.
STRONG_AKWA_IBOM_TERMS = [
    "akwa ibom state",
    "akwa-ibom state",
    "akwa ibom government",
    "akwa-ibom government",
    "akwa ibom governor",
    "governor umo eno",
    "umo eno",
    "akwa ibom house of assembly",
    "akwa ibom state house of assembly",
    "akwa ibom state university",
    "akwa ibom polytechnic",
    "university of uyo",
    "ibom air",
    "ibom power",
    "victor attah international airport",
    "uyo airport",
    "uyo",
    "ikot ekpene",
    "etinan",
    "eket",
    "ikot abasi",
    "oruk anam",
    "ibaka",
    "oron",
    "eastern obolo",
    "esit eket",
    "essien udim",
    "nsit atai",
    "nsit ubium",
    "mkpat enin",
    "itu",
    "uyo lga",
    "ab accompanied by",  # harmless placeholder to avoid accidental empty list
]

# These are useful because some legitimate Akwa Ibom stories may refer
# to a person/institution without using "Akwa Ibom" repeatedly.
AKWA_IBOM_IDENTIFIERS = [
    "ibom",
    "uyo",
    "a'ibom",
    "a/ibom",
    "a'ibom",
]

# Generic phrases that often indicate the article is actually about
# somewhere else and only mentions Akwa Ibom incidentally.
WEAK_CONTEXT_PHRASES = [
    "along with other states",
    "among other states",
    "one of the states",
    "other states including akwa ibom",
    "including akwa ibom",
    "akwa ibom was among",
    "akwa ibom is one of",
]


def clean_text(text):
    """Normalize text for easier matching."""
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def normalize_url(url):
    """Remove tracking parameters and trailing slash."""
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        return clean.rstrip("/")

    except Exception:
        return url


def parse_date(value):
    """Try to convert DuckDuckGo's date into a timezone-aware datetime."""
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    value = str(value).strip()

    # ISO format
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # Common date formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc)

        except Exception:
            continue

    return None


def extract_article_text(url):
    """
    Download the article page and extract visible text.

    If the site blocks us, return an empty string instead of failing
    the entire scraper.
    """

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
        )

        if response.status_code != 200:
            print(
                f"    Could not read article "
                f"(HTTP {response.status_code})"
            )
            return ""

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove things that are not article content.
        for tag in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "nav",
                "footer",
                "header",
                "form",
            ]
        ):
            tag.decompose()

        # Prefer article/main content where available.
        article = soup.find("article")

        if article:
            text = article.get_text(" ", strip=True)
        else:
            main = soup.find("main")

            if main:
                text = main.get_text(" ", strip=True)
            else:
                text = soup.get_text(" ", strip=True)

        return clean_text(text)

    except Exception as e:
        print(f"    Could not read article: {e}")
        return ""


def relevance_score(title, description, article_text):
    """
    Score how strongly the article is connected to Akwa Ibom.

    Higher score = stronger connection.
    """

    title_text = clean_text(title)
    description_text = clean_text(description)
    article_text = clean_text(article_text)

    # Give the headline much more importance than a random mention
    # somewhere deep in an article.
    score = 0

    # Strong Akwa Ibom phrase in headline.
    for term in STRONG_AKWA_IBOM_TERMS:
        if term in title_text:
            score += 8

    # Strong phrase in description.
    for term in STRONG_AKWA_IBOM_TERMS:
        if term in description_text:
            score += 4

    # Strong phrase in article body.
    for term in STRONG_AKWA_IBOM_TERMS:
        if term in article_text:
            score += 2

    # Generic Akwa Ibom mentions.
    akwa_mentions = 0

    for phrase in [
        "akwa ibom",
        "akwa-ibom",
        "a'ibom",
        "a/ibom",
    ]:
        akwa_mentions += title_text.count(phrase) * 5
        akwa_mentions += description_text.count(phrase) * 2
        akwa_mentions += article_text.count(phrase)

    score += min(akwa_mentions, 12)

    # Uyo is particularly useful because many genuinely local stories
    # mention Uyo rather than Akwa Ibom in the headline.
    if "uyo" in title_text:
        score += 7
    elif "uyo" in description_text:
        score += 4
    elif "uyo" in article_text:
        score += 2

    # Ibom Air is inherently Akwa Ibom-related.
    if "ibom air" in title_text:
        score += 10
    elif "ibom air" in description_text:
        score += 6
    elif "ibom air" in article_text:
        score += 4

    # Penalize obvious "passing mention" situations.
    for phrase in WEAK_CONTEXT_PHRASES:
        if phrase in title_text or phrase in description_text:
            score -= 8

    return score


def is_relevant(title, description, article_text):
    """
    Decide whether an article is genuinely relevant.

    The threshold intentionally allows stories such as Ibom Air
    or Uyo stories even if the exact words "Akwa Ibom" are absent
    from the headline.
    """

    title_text = clean_text(title)
    description_text = clean_text(description)
    article_text = clean_text(article_text)

    score = relevance_score(
        title_text,
        description_text,
        article_text,
    )

    # Very strong headline connections should always qualify.
    for term in STRONG_AKWA_IBOM_TERMS:
        if term in title_text:
            return True, score

    # Ibom Air is specifically Akwa Ibom-related.
    if "ibom air" in title_text or "ibom air" in description_text:
        return True, score

    # Uyo in the headline is a strong local signal.
    if "uyo" in title_text:
        return True, score

    # Otherwise require meaningful evidence in the body.
    if score >= 8:
        return True, score

    return False, score


def fetch_news():
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=LOOKBACK_HOURS
    )

    print(f"Searching DuckDuckGo News for: {QUERY}")

    candidates = []

    try:
        with DDGS() as ddgs:
            results = ddgs.news(
                QUERY,
                timelimit="d",
                max_results=MAX_CANDIDATES,
            )

            for result in results:
                title = (result.get("title") or "").strip()
                url = (result.get("url") or "").strip()
                description = (
                    result.get("body")
                    or result.get("description")
                    or ""
                ).strip()

                date_value = (
                    result.get("date")
                    or result.get("published")
                    or result.get("published_date")
                )

                if not title or not url:
                    continue

                published = parse_date(date_value)

                # If DuckDuckGo provides a date, enforce our
                # 24-hour window.
                if published and published < cutoff:
                    continue

                candidates.append(
                    {
                        "title": title,
                        "url": normalize_url(url),
                        "description": description,
                        "published": (
                            published.isoformat()
                            if published
                            else None
                        ),
                    }
                )

    except Exception as e:
        raise RuntimeError(
            f"Could not retrieve DuckDuckGo News results: {e}"
        )

    print(f"DuckDuckGo returned {len(candidates)} candidates.")

    # Remove duplicate URLs first.
    unique_candidates = []
    seen_urls = set()

    for item in candidates:
        url = item["url"]

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)
        unique_candidates.append(item)

    print(
        f"After URL deduplication: "
        f"{len(unique_candidates)} candidates."
    )

    qualifying = []

    for index, item in enumerate(unique_candidates, start=1):

        print()
        print(
            f"Checking relevance "
            f"{index}/{len(unique_candidates)}:"
        )
        print(f"  {item['title']}")

        article_text = extract_article_text(item["url"])

        relevant, score = is_relevant(
            item["title"],
            item["description"],
            article_text,
        )

        if relevant:
            print(f"  ✓ ACCEPTED (score {score})")

            qualifying.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "published": item["published"],
                    "score": score,
                }
            )

        else:
            print(f"  ✗ REJECTED (score {score})")

    # Remove duplicate/similar titles.
    final_stories = []
    seen_titles = set()

    for item in qualifying:

        title_key = clean_text(item["title"])

        # Basic duplicate detection using important words.
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", title_key)
            if len(word) > 3
        ]

        signature = " ".join(sorted(words))

        if signature in seen_titles:
            continue

        seen_titles.add(signature)

        final_stories.append(
            {
                "title": item["title"],
                "url": item["url"],
            }
        )

        if len(final_stories) >= MAX_STORIES:
            break

    print()
    print(
        f"Final result: "
        f"{len(final_stories)} unique relevant news stories."
    )

    for number, story in enumerate(final_stories, start=1):
        print()
        print(f"{number}. {story['title']}")
        print(f"   {story['url']}")

    return final_stories


def main():
    stories = fetch_news()

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "stories": stories,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
