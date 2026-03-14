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

def extract_images_from_entry(entry) -> list:
    """Извлекаем ВСЕ фото из RSS статьи (до 4 штук)"""
    images = []

    # 1. media:content
    for m in entry.get("media_content", []):
        url = m.get("url", "")
        if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            if url not in images:
                images.append(url)

    # 2. media:thumbnail
    for t in entry.get("media_thumbnail", []):
        url = t.get("url", "")
        if url and url not in images:
            images.append(url)

    # 3. enclosures
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", ""):
            url = enc.get("url", "")
            if url and url not in images:
                images.append(url)

    # 4. все img теги в контенте
    content = ""
    if entry.get("content"):
        content = entry["content"][0].get("value", "")
    if not content:
        content = entry.get("summary", "")

    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', content):
        url = match.group(1)
        if url.startswith("http") and url not in images:
            images.append(url)

    return images[:4]  # максимум 4 фото

def get_unsplash_query(text: str) -> str:
    text_lower = text.lower()
    brands = ["gucci", "prada", "chanel", "dior", "louis vuitton", "versace",
              "balenciaga", "valentino", "givenchy", "fendi", "burberry", "hermes",
              "saint laurent", "celine", "bottega", "loewe", "jacquemus", "miu miu"]
    for brand in brands:
        if brand in text_lower:
            return f"{brand} fashion collection"
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
    if any(w in text_lower for w in ["shoe", "heel", "boot"]):
        return "fashion shoes luxury"
    if any(w in text_lower for w in ["spring", "summer"]):
        return "spring summer fashion collection"
    if any(w in text_lower for w in ["fall", "autumn", "winter"]):
        return "fall winter fashion collection"
    if any(w in text_lower for w in ["beauty", "makeup", "skincare"]):
        return "beauty makeup luxury"
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
            source_name = feed.feed.get("title", url)
            for entry in feed.entries[:10]:
                item_id = get_item_id(entry)
                if item_id not in posted:
                    images = extract_images_from_entry(entry)
                    items.append({
                        "id": item_id,
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", ""))[:1000],
                        "link": entry.get("link", ""),
                        "source": source_name,
                        "images": images,
                    })
        except Exception as e:
            print(f"[rss] error {url}: {e}")
    return items

async def generate_post(item: dict) -> str | None:
    prompt = f"""Ты — редактор топового модного Telegram канала "Тренды не для всех".

Свежая новость из {item['source']}:
Заголовок: {item['title']}
Описание: {item['summary']}

Напиши пост на русском языке строго по этой структуре:

1. ПЕРВАЯ СТРОКА — самый яркий факт, цепляющий, без воды (1 предложение)
2. СУТЬ — 2-3 предложения о том что произошло, конкретно и интересно
3. ПРАКТИКА — 1-2 предложения: как этот тренд/образ применить в реальной жизни, что можно повторить
4. ВОПРОС или МНЕНИЕ — короткое, вовлекающее

Требования:
- Всего 400-600 символов
- Живой язык, как умная подруга которая разбирается в моде
- 1-2 эмодзи уместно
- Без хэштегов, без клише

Верни только текст поста."""

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

async def send_telegram_album(caption: str, images: list):
    """Отправляем альбом из нескольких фото"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if len(images) >= 2:
                media = []
                for i, url in enumerate(images[:4]):
                    item = {"type": "photo", "media": url}
                    if i == 0:
                        item["caption"] = caption
                        item["parse_mode"] = "HTML"
                    media.append(item)
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup",
                    json={"chat_id": TELEGRAM_CHANNEL, "media": media}
                )
                if resp.json().get("ok"):
                    return
            # одно фото или ошибка альбома
            if images:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    json={"chat_id": TELEGRAM_CHANNEL, "photo": images[0],
                          "caption": caption, "parse_mode": "HTML"}
                )
                if resp.json().get("ok"):
                    return
            # совсем без фото
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHANNEL, "text": caption, "parse_mode": "HTML"}
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
    print(f"RSS images found: {len(item['images'])}")

    post_text = await generate_post(item)
    if not post_text:
        print("Failed to generate post")
        return

    # Добавляем источник и ссылку
    source_line = f"\n\n📰 <a href='{item['link']}'>{item['source']}</a>"
    full_text = post_text + source_line

    # Фото: сначала из RSS, потом Unsplash
    images = item["images"]
    if not images:
        print("No RSS images, trying Unsplash...")
        query = get_unsplash_query(item["title"] + " " + item["summary"])
        fallback = await get_unsplash_image(query)
        if fallback:
            images = [fallback]

    await send_telegram_album(full_text, images)

    posted = load_posted()
    posted.add(item["id"])
    save_posted(posted)
    await increment_counter()

    print(f"✓ Posted: {item['title'][:50]}...")

if __name__ == "__main__":
    asyncio.run(run())
