import os
import json
import httpx
import asyncio
import feedparser
import hashlib
from pathlib import Path
from datetime import datetime

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@trendy_ne_dlya_vsex")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
POSTS_PER_DAY = int(os.getenv("POSTS_PER_DAY", "6"))

POSTED_FILE = "posted.json"

RSS_FEEDS = [
    "https://www.vogue.com/feed/rss",
    "https://wwd.com/feed/",
    "https://www.harpersbazaar.com/feed/rss",
    "https://www.elle.com/feed/rss",
]

UNSPLASH_KEYWORDS = {
    "gucci": "Gucci fashion",
    "prada": "Prada fashion",
    "chanel": "Chanel fashion luxury",
    "dior": "Dior fashion",
    "louis vuitton": "Louis Vuitton luxury",
    "versace": "Versace fashion",
    "balenciaga": "Balenciaga fashion",
    "zara": "Zara fashion style",
    "runway": "runway fashion show",
    "spring": "spring fashion outfit",
    "summer": "summer fashion style",
    "fall": "fall fashion autumn",
    "winter": "winter fashion style",
    "trend": "fashion trend style",
    "collection": "fashion collection runway",
    "beauty": "beauty makeup cosmetics",
    "jewelry": "jewelry luxury accessories",
    "shoes": "fashion shoes luxury",
    "bag": "luxury handbag fashion",
}

def get_unsplash_query(text: str) -> str:
    text_lower = text.lower()
    for keyword, query in UNSPLASH_KEYWORDS.items():
        if keyword in text_lower:
            return query
    return "fashion style luxury"

def load_posted():
    if not Path(POSTED_FILE).exists():
        return set()
    with open(POSTED_FILE) as f:
        return set(json.load(f))

def save_posted(posted: set):
    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted)[-500:], f)

def get_item_id(item) -> str:
    return hashlib.md5((item.get("link", "") + item.get("title", "")).encode()).hexdigest()

async def fetch_rss_items() -> list:
    items = []
    posted = load_posted()
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                item_id = get_item_id(entry)
                if item_id not in posted:
                    items.append({
                        "id": item_id,
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", ""))[:1000],
                        "link": entry.get("link", ""),
                        "source": feed.feed.get("title", url),
                    })
        except Exception as e:
            print(f"[rss] error {url}: {e}")
    return items

async def generate_post(item: dict) -> str | None:
    prompt = f"""Ты редактор модного Telegram канала "Тренды не для всех" для русскоязычной аудитории.

Вот новость из издания {item['source']}:
Заголовок: {item['title']}
Описание: {item['summary']}

Напиши пост на русском языке по этой новости. Требования:
- 500-900 символов
- Начни с самого интересного факта или детали — сразу цепляй
- Упомяни бренд/дизайнера/тренд конкретно
- Живой язык, как будто рассказываешь подруге
- Без воды и шаблонных фраз
- В конце — короткий вывод или мнение

Верни только текст поста, без заголовка."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
            )
            data = resp.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[claude] error: {e}")
        return None

async def get_image_url(query: str) -> str | None:
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.unsplash.com/photos/random",
                params={"query": query, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
            )
            data = resp.json()
            return data.get("urls", {}).get("regular")
    except Exception as e:
        print(f"[unsplash] error: {e}")
        return None

async def send_telegram(text: str, image_url: str = None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if image_url:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    json={
                        "chat_id": TELEGRAM_CHANNEL,
                        "photo": image_url,
                        "caption": text,
                        "parse_mode": "HTML"
                    }
                )
            else:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": TELEGRAM_CHANNEL,
                        "text": text,
                        "parse_mode": "HTML"
                    }
                )
    except Exception as e:
        print(f"[telegram] error: {e}")

async def get_posts_today() -> int:
    counter_file = Path("counter.json")
    if not counter_file.exists():
        return 0
    with open(counter_file) as f:
        data = json.load(f)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if data.get("date") != today:
        return 0
    return data.get("count", 0)

async def increment_counter():
    counter_file = Path("counter.json")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    count = await get_posts_today() + 1
    with open(counter_file, "w") as f:
        json.dump({"date": today, "count": count}, f)

async def run():
    print(f"[{datetime.utcnow()}] Starting fashion bot run...")
    
    posts_today = await get_posts_today()
    if posts_today >= POSTS_PER_DAY:
        print(f"Daily limit reached ({posts_today}/{POSTS_PER_DAY})")
        return

    items = await fetch_rss_items()
    if not items:
        print("No new RSS items found")
        return

    item = items[0]
    print(f"Processing: {item['title']}")

    post_text = await generate_post(item)
    if not post_text:
        print("Failed to generate post")
        return

    unsplash_query = get_unsplash_query(item["title"] + " " + item["summary"])
    image_url = await get_image_url(unsplash_query)

    await send_telegram(post_text, image_url)

    posted = load_posted()
    posted.add(item["id"])
    save_posted(posted)
    await increment_counter()

    print(f"✓ Posted: {item['title'][:50]}...")

if __name__ == "__main__":
    asyncio.run(run())
