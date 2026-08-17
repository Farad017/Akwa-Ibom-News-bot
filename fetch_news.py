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


# Places and entities that are strongly associated with Akwa Ibom.
# These are deliberately more specific than simply searching for
# the words "akwa" or "ibom".
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
    "ibom tropical park",
    "ibom plaza",
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
    "ini lga",
    "isiala mbano",
    "mbo",
    "okobo",
    "udung uko",
    "urue offong/oruko",
    "urue offong",
    "uyo lga",
]


# Nigerian locations that should make us cautious when they dominate
# the story. The article can still be relevant to Akwa Ibom, but a
# story clearly about another location should not pass just because
# Akwa Ibom appears once.
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


def parse_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

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
    Download the article and extract its main visible text.

    If a website blocks access, return an empty string. The scraper
    will then be conservative rather than assuming the story is
    relevant.
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


def count_terms(text, terms):
    count = 0

    for term in terms:
        count += text.count(term)

    return count


def has_strong_headline_connection(title):
    """
    Headline-level connection is the strongest signal.

    This allows legitimate stories such as:
    - Uyo flooding
    - Ibom Air expansion
    - Akwa Ibom police operations
    - Governor Eno announcements
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

    return any(term in title for term in strong_headline_terms)


def relevance_score(title, description, article_text):
    """
    Calculate a conservative relevance score.

    Headline = strongest evidence.
    Description = medium evidence.
    Body = supporting evidence.

    A single incidental mention of Akwa Ibom should not be enough.
    """

    title = clean_text(title)
    description = clean_text(description)
    article_text = clean_text(article_text)

    score = 0

    headline_hits = count_terms(title, AKWA_IBOM_TERMS)
    description_hits = count_terms(description, AKWA_IBOM_TERMS)
    body_hits = count_terms(article_text, AKWA_IBOM_TERMS)

    # Headline evidence is very strong.
    score += headline_hits * 12

    # Search-result description is useful but less reliable.
    score += min(description_hits * 4, 12)

    # Body evidence is supporting evidence only.
    score += min(body_hits * 2, 14)

    # Specific entities receive additional weight.
    if "ibom air" in title:
        score += 10

    if "ibom air" in description:
        score += 5

    if "ibom air" in article_text:
        score += 3

    if "governor umo eno" in title or "umo eno" in title:
        score += 8

    if "akwa ibom government" in title:
        score += 8

    # If the headline contains another Nigerian location and does
    # not contain an Akwa-Ibom signal, apply a strong penalty.
    other_locations_in_title = count_terms(
        title,
        OTHER_LOCATION_TERMS,
    )

    if other_locations_in_title > 0 and headline_hits == 0:
        score -= 15

    # If another location dominates the article and Akwa Ibom is
    # mentioned only a few times, apply another penalty.
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


def is_relevant(title, description, article_text):
    """
    Conservative relevance decision.

    We intentionally prefer publishing fewer genuine stories rather
    than filling the feed with loosely related stories.
    """

    title = clean_text(title)
    description = clean_text(description)
    article_text = clean_text(article_text)

    # If the headline itself clearly identifies Akwa Ibom/Uyo/etc.,
    # accept it.
    if has_strong_headline_connection(title):
        score = relevance_score(
            title,
            description,
            article_text,
        )
        return True, score

    # Without a strong headline connection, we need the article body
    # to provide meaningful evidence.
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

    # Require stronger evidence when Akwa Ibom is NOT in the headline.
    #
    # This prevents articles about Abuja, Osun, Katsina, etc. from
    # slipping through because they happen to mention Akwa Ibom.
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
    if strong_entity_mentions >= 2 and score >= 8:
        return True, score

    # Several independent Akwa-Ibom references.
    if akwa_body_mentions >= 4 and score >= 10:
        return True, score

    # Uyo/local-government connection can qualify if it is repeated
    # meaningfully in the article.
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

    # URL deduplication.
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

    for index, item in enumerate(
        unique_candidates,
        start=1,
    ):

        print()
        print(
            f"Checking relevance "
            f"{index}/{len(unique_candidates)}:"
        )

        print(f"  {item['title']}")

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
                    "published": item["published"],
                    "score": score,
                }
            )

        else:
            print(
                f"  ✗ REJECTED "
                f"(score {score})"
            )

    # Title deduplication.
    final_stories = []
    seen_signatures = set()

    for item in qualifying:

        title_key = clean_text(
            item["title"]
        )

        words = [
            word
            for word in re.findall(
                r"[a-z0-9]+",
                title_key,
            )
            if len(word) > 3
        ]

        signature = " ".join(
            sorted(words)
        )

        if signature in seen_signatures:
            continue

        seen_signatures.add(signature)

        final_stories.append(
            {
                "title": item["title"],
                "url": item["url"],
            }
        )

        # Maximum 10 stories.
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
