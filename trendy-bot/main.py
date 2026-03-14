import os
import json
import httpx
import asyncio
import feedparser
import hashlib
import re
from pathlib import Path
from datetime import datetime

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip().lstrip("= ")
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
    "https://www.vogue.ru/feed/rss",
    "https://www.tatler.ru/feed/rss",
]

def extract_image_from_entry(entry) -> str | None:
    """Извлекаем фото прямо из RSS статьи"""
    # 1. media:content
    media = entry.get("media_content", [])
    if media:
        for m in media:
            url = m.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                return url

    # 2. media:thumbnail
    thumb = entry.get("media_thumbnail", [])
    if thumb:
        url = thumb[0].get("url", "")
        if url:
            return url

    # 3. enclosures
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", ""):
            return enc.get("url", "")

    # 4. img тег в content/summary
    content = ""
    if entry.get("content"):
        content = entry["content"][0].get("value", "")
    if not content:
        content = entry.get("summary", "")

    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
    if img_match:
        url = img_match.group(1)
        if url.startswith("http"):
            return url

    return None

def get_unsplash_query(text: str) -> str:
    text_lower = text.lower()
    brands = ["gucci", "prada", "chanel", "dior", "louis vuitton", "versace",
              "balenciaga", "valentino", "givenchy", "fendi", "burberry", "hermes",
              "saint laurent", "celine", "bottega", "loewe", "jacquemus"]
    for brand in brands:
        if brand in text_lower:
            return f"{brand} fashion runway"
    if any(w in text_lower for w in ["ball", "gala", "gown", "evening", "couture"]):
        return "elegant gala evening gown dress"
    if any(w in text_lower for w in ["runway", "show", "collection", "fashion week"]):
        return "fashion runway show model"
    if any(w in text_lower for w in ["street style", "street fashion"]):
        return "street style fashion outfit"
    if any(w in text_lower for w in ["jewelry", "jewel", "diamond", "necklace"]):
        return "luxury jewelry diamonds"
    if any(w in text_lower for w in ["bag", "handbag", "purse"]):
        return "luxury handbag fashion"
    if any(w in text_lower for w in ["shoe", "heel", "boot", "sneaker"]):
        return "fashion shoes luxury"
    if any(w in text_lower for w in ["spring", "summer", "ss2"]):
        return "spring summer fashion collection"
    if any(w in text_lower for w in ["fall", "autumn", "winter", "fw2"]):
        return "fall winter fashion collection"
    if any(w in text_lower for w in ["beauty", "makeup", "skincare"]):
        return "beauty makeup luxury cosmetics"
    return "fashion style luxury editorial"

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
                    image_url = extract_image_from_entry(entry)
                    items.append({
                        "id": item_id,
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", ""))[:1000],
                        "link": entry.get("link", ""),
                        "source": feed.feed.get("title", url),
                        "image_url": image_url,
                    })
        except Exception as e:
            print(f"[rss] error {url}: {e}")
    return items

async def generate_post(item: dict) -> str | None:
    prompt = f"""Ты — редактор топового модного Telegram канала "Тренды не для всех" для русскоязычной аудитории.

Вот свежая новость из издания {item['source']}:
Заголовок: {item['title']}
Описание: {item['summary']}

Напиши пост на русском языке. Требования:
- 400-700 символов — коротко и по делу
- Первое предложение — самый яркий факт или деталь, сразу цепляй
- Упомяни бренд/дизайнера/тренд конкретно и с уважением
- Тон: как умная подруга которая разбирается в моде — живо, с характером, без пафоса
- Добавь одну конкретную деталь которая делает это особенным
- Заверши коротким личным мнением или вопросом к читателям
- Используй 1-2 эмодзи уместно
- Никаких клише типа "в мире моды", "модные эксперты считают"

Верни только текст поста, без заголовка и без хэштегов."""

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
            if "content" not in data:
                print(f"[claude] unexpected response: {data}")
                return None
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[claude] error: {e}")
        return None

async def get_unsplash_image(query: str) -> str | None:
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.unsplash.com/photos/random",
                params={"query": query, "orientation": "portrait"},
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
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    json={
                        "chat_id": TELEGRAM_CHANNEL,
                        "photo": image_url,
                        "caption": text,
                        "parse_mode": "HTML"
                    }
                )
                # если фото не загрузилось — шлём без фото
                if resp.json().get("ok") is False:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
                    )
            else:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
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
    print(f"RSS image: {item.get('image_url', 'none')}")

    post_text = await generate_post(item)
    if not post_text:
        print("Failed to generate post")
        return

    # Приоритет: фото из RSS → Unsplash как запасной
    image_url = item.get("image_url")
    if not image_url:
        print("No RSS image, trying Unsplash...")
        query = get_unsplash_query(item["title"] + " " + item["summary"])
        image_url = await get_unsplash_image(query)

    await send_telegram(post_text, image_url)

    posted = load_posted()
    posted.add(item["id"])
    save_posted(posted)
    await increment_counter()

    print(f"✓ Posted: {item['title'][:50]}...")

if __name__ == "__main__":
    asyncio.run(run())
