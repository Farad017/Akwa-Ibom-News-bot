import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


QUERY = "akwa ibom"
MAX_STORIES = 10
LOOKBACK_HOURS = 24
MAX_CANDIDATES = 40

OUTPUT_FILE = "news.json"

# Two headlines with a similarity of 0.75 or more are considered
# likely to be reporting the same story.
DUPLICATE_SIMILARITY = 0.75

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


# Strong Akwa Ibom-related terms.
AKWA_IBOM_TERMS = [
    "akwa ibom",
    "akwa-ibom",
    "a'ibom",
    "a/ibom",
    "akwaibom",
    "uyo",
    "ibom air",
    "ibom airport",
    "uyo airport",
    "ibom power",
    "akwa ibom government",
    "akwa-ibom government",
    "akwa ibom governor",
    "akwa-ibom governor",
    "governor umo eno",
    "umo eno",
    "akwa ibom house of assembly",
    "akwa ibom state house of assembly",
    "akwa ibom state university",
    "university of uyo",
    "akwa ibom state university teaching hospital",
    "aksth",
    "ikot ekpene",
    "eket",
    "etinan",
    "oron",
    "ikot abasi",
    "itu",
    "nsit ubium",
    "nsit atai",
    "mkpat enin",
    "essien udim",
    "oruk anam",
    "eastern obolo",
    "esit eket",
    "ibiono ibom",
    "ibiono",
    "okobo",
    "mbo",
    "udung uko",
    "urue offong",
    "uyo lga",
]


# Other Nigerian locations. These help us reject stories that are
# primarily about another part of Nigeria.
OTHER_LOCATION_TERMS = [
    "abuja",
    "lagos",
    "kano",
    "kaduna",
    "katsina",
    "osun",
    "oyo",
    "ogun",
    "ondo",
    "ekiti",
    "enugu",
    "anambra",
    "imo",
    "rivers",
    "bayelsa",
    "delta",
    "edo",
    "cross river",
    "plateau",
    "benue",
    "nasarawa",
    "kwara",
    "niger",
    "sokoto",
    "zamfara",
    "jigawa",
    "bauchi",
    "gombe",
    "borno",
    "yobe",
    "adamawa",
]


def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def normalize_url(url):
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        return clean.rstrip("/")

    except Exception:
        return url


def normalize_title(title):
    """
    Normalize a headline so that punctuation, capitalization and
    common filler words don't interfere with duplicate detection.
    """

    title = clean_text(title)

    # Remove punctuation.
    title = re.sub(r"[^a-z0-9\s]", " ", title)

    # Common words that add little value when comparing headlines.
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "as",
        "at",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "its",
        "this",
        "that",
        "after",
        "over",
        "into",
        "says",
        "say",
        "report",
        "reports",
        "news",
    }

    words = [
        word
        for word in title.split()
        if word not in stop_words
    ]

    return " ".join(words)


def title_similarity(title1, title2):
    """
    Compare two normalized headlines.
    """

    a = normalize_title(title1)
    b = normalize_title(title2)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def parse_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

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
    Download article text.

    If the website blocks access, return an empty string.
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

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # Remove non-content elements.
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

        article = soup.find("article")

        if article:
            text = article.get_text(
                " ",
                strip=True,
            )
        else:
            main = soup.find("main")

            if main:
                text = main.get_text(
                    " ",
                    strip=True,
                )
            else:
                text = soup.get_text(
                    " ",
                    strip=True,
                )

        return clean_text(text)

    except Exception as e:
        print(
            f"    Could not read article: {e}"
        )
        return ""


def count_terms(text, terms):
    count = 0

    for term in terms:
        count += text.count(term)

    return count


def has_strong_headline_connection(title):
    """
    Determine whether the headline itself clearly identifies
    Akwa Ibom or a strongly associated local entity.
    """

    title = clean_text(title)

    strong_headline_terms = [
        "akwa ibom",
        "akwa-ibom",
        "a'ibom",
        "a/ibom",
        "akwaibom",
        "uyo",
        "ibom air",
        "ibom airport",
        "uyo airport",
        "ibom power",
        "governor umo eno",
        "umo eno",
        "akwa ibom government",
        "akwa-ibom government",
        "akwa ibom governor",
        "akwa-ibom governor",
        "akwa ibom house of assembly",
        "akwa ibom state university",
        "university of uyo",
        "ikot ekpene",
        "eket",
        "etinan",
        "oron",
        "ikot abasi",
        "itu",
        "nsit ubium",
        "nsit atai",
        "mkpat enin",
        "essien udim",
        "oruk anam",
        "eastern obolo",
        "esit eket",
        "ibiono ibom",
        "okobo",
        "mbo",
        "udung uko",
    ]

    return any(
        term in title
        for term in strong_headline_terms
    )


def relevance_score(
    title,
    description,
    article_text,
):
    """
    Calculate a conservative relevance score.
    """

    title = clean_text(title)
    description = clean_text(description)
    article_text = clean_text(article_text)

    score = 0

    headline_hits = count_terms(
        title,
        AKWA_IBOM_TERMS,
    )

    description_hits = count_terms(
        description,
        AKWA_IBOM_TERMS,
    )

    body_hits = count_terms(
        article_text,
        AKWA_IBOM_TERMS,
    )

    # Headline evidence is strongest.
    score += headline_hits * 12

    # Search result description is secondary evidence.
    score += min(
        description_hits * 4,
        12,
    )

    # Body evidence supports the connection.
    score += min(
        body_hits * 2,
        14,
    )

    # Specific entities get extra weight.
    if "ibom air" in title:
        score += 10

    if "ibom air" in description:
        score += 5

    if "ibom air" in article_text:
        score += 3

    if (
        "governor umo eno" in title
        or "umo eno" in title
    ):
        score += 8

    if "akwa ibom government" in title:
        score += 8

    # Penalize headlines clearly about another Nigerian location.
    other_locations_in_title = count_terms(
        title,
        OTHER_LOCATION_TERMS,
    )

    if (
        other_locations_in_title > 0
        and headline_hits == 0
    ):
        score -= 15

    # Penalize articles dominated by another location.
    other_location_mentions = count_terms(
        article_text,
        OTHER_LOCATION_TERMS,
    )

    akwa_mentions = count_terms(
        article_text,
        [
            "akwa ibom",
            "akwa-ibom",
            "a'ibom",
            "a/ibom",
            "ibom air",
        ],
    )

    if (
        other_location_mentions >= 5
        and akwa_mentions <= 2
        and headline_hits == 0
    ):
        score -= 15

    return score


def is_relevant(
    title,
    description,
    article_text,
):
    """
    Conservative relevance decision.

    Fewer genuine stories are preferable to filling the feed
    with unrelated stories.
    """

    title = clean_text(title)
    description = clean_text(description)
    article_text = clean_text(article_text)

    # A strong headline connection is enough.
    if has_strong_headline_connection(title):

        score = relevance_score(
            title,
            description,
            article_text,
        )

        return True, score

    # Without article text, we cannot confidently establish
    # relevance.
    if not article_text:

        score = relevance_score(
            title,
            description,
            article_text,
        )

        return False, score

    score = relevance_score(
        title,
        description,
        article_text,
    )

    akwa_body_mentions = count_terms(
        article_text,
        [
            "akwa ibom",
            "akwa-ibom",
            "a'ibom",
            "a/ibom",
            "ibom air",
        ],
    )

    strong_entity_mentions = count_terms(
        article_text,
        [
            "ibom air",
            "akwa ibom government",
            "governor umo eno",
            "umo eno",
            "university of uyo",
            "akwa ibom house of assembly",
        ],
    )

    # Strong direct connection.
    if (
        strong_entity_mentions >= 2
        and score >= 8
    ):
        return True, score

    # Several direct Akwa Ibom references.
    if (
        akwa_body_mentions >= 4
        and score >= 10
    ):
        return True, score

    # Several references to an Akwa Ibom locality plus
    # explicit Akwa Ibom references.
    local_place_mentions = count_terms(
        article_text,
        [
            "uyo",
            "etinan",
            "eket",
            "oron",
            "ikot ekpene",
            "ikot abasi",
        ],
    )

    if (
        local_place_mentions >= 3
        and akwa_body_mentions >= 2
        and score >= 10
    ):
        return True, score

    return False, score


def fetch_news():
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=LOOKBACK_HOURS)
    )

    print(
        f"Searching DuckDuckGo News for: {QUERY}"
    )

    candidates = []

    try:
        with DDGS() as ddgs:

            results = ddgs.news(
                QUERY,
                timelimit="d",
                max_results=MAX_CANDIDATES,
            )

            for result in results:

                title = (
                    result.get("title")
                    or ""
                ).strip()

                url = (
                    result.get("url")
                    or ""
                ).strip()

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

                published = parse_date(
                    date_value
                )

                if (
                    published
                    and published < cutoff
                ):
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
            "Could not retrieve DuckDuckGo "
            f"News results: {e}"
        )

    print(
        f"DuckDuckGo returned "
        f"{len(candidates)} candidates."
    )

    # ---------------------------------------------------------
    # STEP 1: Remove exact duplicate URLs.
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # STEP 2: Relevance filtering.
    # ---------------------------------------------------------

    qualifying = []

    for index, item in enumerate(
        unique_candidates,
        start=1,
    ):

        print()

        print(
            f"Checking relevance "
            f"{index}/"
            f"{len(unique_candidates)}:"
        )

        print(
            f"  {item['title']}"
        )

        article_text = extract_article_text(
            item["url"]
        )

        relevant, score = is_relevant(
            item["title"],
            item["description"],
            article_text,
        )

        if relevant:

            print(
                f"  ✓ ACCEPTED "
                f"(score {score})"
            )

            qualifying.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "published": item[
                        "published"
                    ],
                    "score": score,
                }
            )

        else:

            print(
                f"  ✗ REJECTED "
                f"(score {score})"
            )

    # ---------------------------------------------------------
    # STEP 3: Remove duplicate stories from different websites.
    # ---------------------------------------------------------

    print()
    print(
        "Checking for duplicate stories "
        "across different news sources..."
    )

    unique_stories = []

    for item in qualifying:

        duplicate_found = False

        for existing in unique_stories:

            similarity = title_similarity(
                item["title"],
                existing["title"],
            )

            if similarity >= DUPLICATE_SIMILARITY:

                print()
                print(
                    "  Duplicate story removed:"
                )

                print(
                    f"    {item['title']}"
                )

                print(
                    f"    Similar to: "
                    f"{existing['title']}"
                )

                print(
                    f"    Similarity: "
                    f"{similarity:.2f}"
                )

                duplicate_found = True

                break

        if not duplicate_found:

            unique_stories.append(item)

    # ---------------------------------------------------------
    # STEP 4: Maximum of 10 stories.
    # ---------------------------------------------------------

    final_stories = []

    for item in unique_stories:

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
        f"{len(final_stories)} "
        f"unique relevant news stories."
    )

    for number, story in enumerate(
        final_stories,
        start=1,
    ):

        print()

        print(
            f"{number}. "
            f"{story['title']}"
        )

        print(
            f"   {story['url']}"
        )

    return final_stories


def main():

    stories = fetch_news()

    output = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),
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

    print(
        f"Saved {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
