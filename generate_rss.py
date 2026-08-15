import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape


INPUT_FILE = Path("news.json")
OUTPUT_FILE = Path("feed.xml")

FEED_TITLE = "Akwa Ibom News"
FEED_DESCRIPTION = (
    "Latest Akwa Ibom-related news from DuckDuckGo News."
)

FEED_URL = (
    "https://farad017.github.io/Akwa-Ibom-News-bot/feed.xml"
)


def load_news():

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "news.json was not found."
        )

    data = json.loads(
        INPUT_FILE.read_text(
            encoding="utf-8"
        )
    )

    return data.get("stories", [])


def build_rss(stories):

    now = datetime.now(timezone.utc)

    rss = []

    rss.append(
        '<?xml version="1.0" encoding="UTF-8"?>'
    )

    rss.append(
        '<rss version="2.0">'
    )

    rss.append(
        "<channel>"
    )

    rss.append(
        f"<title>{escape(FEED_TITLE)}</title>"
    )

    rss.append(
        f"<link>{escape(FEED_URL)}</link>"
    )

    rss.append(
        f"<description>{escape(FEED_DESCRIPTION)}</description>"
    )

    rss.append(
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
    )

    for story in stories:

        title = escape(
            story.get("title", "")
        )

        url = escape(
            story.get("url", "")
        )

        if not title or not url:
            continue

        rss.append("<item>")

        rss.append(
            f"<title>{title}</title>"
        )

        rss.append(
            f"<link>{url}</link>"
        )

        rss.append("</item>")

    rss.append("</channel>")
    rss.append("</rss>")

    return "\n".join(rss)


def main():

    stories = load_news()

    rss = build_rss(stories)

    OUTPUT_FILE.write_text(
        rss,
        encoding="utf-8"
    )

    print(
        f"Generated RSS feed with "
        f"{len(stories)} stories."
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
