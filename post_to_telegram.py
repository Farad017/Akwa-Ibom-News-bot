#!/usr/bin/env python3

import json
import os
import urllib.parse
import urllib.request


NEWS_FILE = "news.json"
POSTED_FILE = "posted_news.json"


def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram_message(bot_token, chat_id, title, url):
    message = f"{title}\n{url}"

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(request) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel = os.environ.get("TELEGRAM_CHANNEL")

    if not bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN secret is missing."
        )

    if not channel:
        raise RuntimeError(
            "TELEGRAM_CHANNEL secret is missing."
        )

    news_data = load_json(NEWS_FILE, {})
    stories = news_data.get("stories", [])

    posted_urls = load_json(POSTED_FILE, [])

    posted_urls = set(posted_urls)

    print(f"Stories found in news.json: {len(stories)}")
    print(f"Previously posted stories: {len(posted_urls)}")

    new_count = 0

    for story in stories:
        title = story.get("title", "").strip()
        url = story.get("url", "").strip()

        if not title or not url:
            continue

        if url in posted_urls:
            print(f"Already posted: {title}")
            continue

        print(f"Posting: {title}")

        send_telegram_message(
            bot_token,
            channel,
            title,
            url
        )

        posted_urls.add(url)
        new_count += 1

        # Save immediately after each successful post.
        # This helps prevent reposting if a later story fails.
        save_json(
            POSTED_FILE,
            sorted(posted_urls)
        )

    print(f"New stories posted to Telegram: {new_count}")


if __name__ == "__main__":
    main()
