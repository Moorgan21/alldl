import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import yt_dlp

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from json2netscape import convert as convert_json_cookies

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")

MAX_TELEGRAM_UPLOAD = 50 * 1024 * 1024  # 50MB bot API limit

COOKIES_DIR = "/root/alldl/cookies"
COOKIE_FILES = {
    "instagram": os.path.join(COOKIES_DIR, "instagram.txt"),
    "tiktok": os.path.join(COOKIES_DIR, "tiktok.txt"),
    "pinterest": os.path.join(COOKIES_DIR, "pinterest.txt"),
}


def detect_platform(url: str) -> str:
    host = url.lower()
    if "tiktok.com" in host:
        return "tiktok"
    if "instagram.com" in host:
        return "instagram"
    if "pinterest." in host or "pin.it" in host:
        return "pinterest"
    return "unknown"


def download_with_ytdlp(url: str, outdir: str, platform: str) -> str:
    outtmpl = os.path.join(outdir, "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_TELEGRAM_UPLOAD,
        "postprocessor_args": {
            "merger": ["-movflags", "+faststart"],
        },
    }
    cookie_file = COOKIE_FILES.get(platform)
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        if not os.path.exists(filepath):
            base, _ = os.path.splitext(filepath)
            for f in os.listdir(outdir):
                if f.startswith(os.path.basename(base)):
                    filepath = os.path.join(outdir, f)
                    break
        return filepath


def probe_video(filepath: str):
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", filepath,
            ],
            capture_output=True, text=True, timeout=20,
        )
        data = json.loads(result.stdout)
        duration = int(float(data.get("format", {}).get("duration", 0)))
        width = height = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                break
        return duration, width, height
    except Exception:
        logger.exception("ffprobe failed for %s", filepath)
        return 0, 0, 0


def make_thumbnail(filepath: str, outdir: str):
    thumb_path = os.path.join(outdir, f"thumb_{uuid.uuid4().hex}.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", filepath, "-vframes", "1", "-vf", "scale=320:-1", thumb_path],
            capture_output=True, timeout=20,
        )
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception:
        logger.exception("thumbnail generation failed for %s", filepath)
    return None


def download_pinterest_image_fallback(url: str, outdir: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    media_url = None
    video_tag = soup.find("meta", property="og:video")
    if video_tag and video_tag.get("content"):
        media_url = video_tag["content"]
    else:
        img_tag = soup.find("meta", property="og:image")
        if img_tag and img_tag.get("content"):
            media_url = img_tag["content"]

    if not media_url:
        raise ValueError("رسانه‌ای در این لینک پیدا نشد.")

    ext = os.path.splitext(media_url.split("?")[0])[1] or ".jpg"
    filepath = os.path.join(outdir, f"pin_{uuid.uuid4().hex}{ext}")

    with requests.get(media_url, headers=headers, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(filepath, "wb") as f:
            shutil.copyfileobj(r.raw, f)

    return filepath


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 <b>ربات دانلودر شبکه‌های اجتماعی</b>\n\n"
        "📥 لینک پست از این شبکه‌ها رو برام بفرست تا فایلش رو برات دانلود کنم:\n"
        "• اینستاگرام (پست، ریلز، استوری)\n"
        "• تیک‌تاک (ویدیو، عکس)\n"
        "• پینترست (ویدیو، عکس)\n\n"
        "🔗 <b>چطور استفاده کنم؟</b>\n"
        "فقط کافیه لینک پست رو برام بفرستی، من ویدیو یا عکس رو استخراج می‌کنم و برات می‌فرستم.\n\n"
        "⚡ <b>ویژگی‌ها:</b>\n"
        "• دانلود با کیفیت اصلی\n"
        "• بدون واترمارک (اکثر سکوها)\n"
        "• پشتیبانی از استوری اینستاگرام\n"
        "• سرعت بالا\n\n"
        "📌 <b>مثال:</b>\n"
        "<code>https://www.instagram.com/p/CxYz123Abc/</code>\n"
        "<code>https://www.tiktok.com/@user/video/123456789</code>\n"
        "<code>https://pin.it/xyz123</code>\n\n"
        "---\n"
        "✨ <b>Created By D.L</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        await update.message.reply_text("لطفاً یه لینک معتبر از تیک‌تاک، اینستاگرام یا پینترست بفرست.")
        return

    url = match.group(0)
    platform = detect_platform(url)
    if platform == "unknown":
        await update.message.reply_text("این لینک پشتیبانی نمی‌شه. فقط تیک‌تاک، اینستاگرام و پینترست.")
        return

    status_msg = await update.message.reply_text("در حال دانلود... ⏳")

    tmpdir = tempfile.mkdtemp(prefix="alldl_", dir="/root/alldl/downloads")
    filepath = None
    try:
        try:
            filepath = download_with_ytdlp(url, tmpdir, platform)
        except Exception as e:
            if platform == "pinterest":
                logger.info("yt-dlp failed for pinterest, trying fallback: %s", e)
                filepath = download_pinterest_image_fallback(url, tmpdir)
            else:
                raise

        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("فایل دانلود نشد.")

        size = os.path.getsize(filepath)
        if size > MAX_TELEGRAM_UPLOAD:
            await status_msg.edit_text("فایل بزرگ‌تر از حد مجاز تلگرام (۵۰ مگابایت) هست و قابل ارسال نیست.")
            return

        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".mp4", ".mov", ".mkv", ".webm"):
            duration, width, height = probe_video(filepath)
            thumb_path = make_thumbnail(filepath, tmpdir)
            thumb_file = open(thumb_path, "rb") if thumb_path else None
            with open(filepath, "rb") as f:
                await update.message.reply_video(
                    f,
                    caption="✅ دانلود شد",
                    duration=duration or None,
                    width=width or None,
                    height=height or None,
                    thumbnail=thumb_file,
                    supports_streaming=True,
                )
            if thumb_file:
                thumb_file.close()
        else:
            with open(filepath, "rb") as f:
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    await update.message.reply_photo(f, caption="✅ دانلود شد")
                else:
                    await update.message.reply_document(f, caption="✅ دانلود شد")

        await status_msg.delete()

    except Exception as e:
        logger.exception("Download failed for %s", url)
        err_text = str(e)
        low = err_text.lower()

        auth_signals = (
            "cookies",
            "empty media response",
            "login required",
            "log in",
            "rate-limit reached",
            "checkpoint_required",
            "401",
        )
        is_auth_error = any(s in low for s in auth_signals)

        cookie_file = COOKIE_FILES.get(platform)
        has_cookie = bool(cookie_file and os.path.exists(cookie_file))

        if is_auth_error and has_cookie:
            await status_msg.edit_text(
                "⚠️ کوکی حساب اینستاگرام منقضی یا نامعتبر شده (یا اکانت لاگ‌اوت/چالش امنیتی خورده).\n"
                "لطفاً دوباره لاگین کن، کوکی جدید export کن و برام بفرست."
            )
        elif is_auth_error:
            await status_msg.edit_text(
                "❌ اینستاگرام بدون لاگین این پست رو نمی‌ده.\n"
                "باید فایل کوکی حساب اینستاگرام رو تنظیم کنیم تا این مشکل حل بشه."
            )
        else:
            await status_msg.edit_text(f"❌ دانلود ناموفق بود.\n{err_text}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def auto_convert_cookie_jsons():
    for platform, txt_path in COOKIE_FILES.items():
        json_path = os.path.splitext(txt_path)[0] + ".json"
        if not os.path.exists(json_path):
            continue
        needs_convert = (
            not os.path.exists(txt_path)
            or os.path.getmtime(json_path) > os.path.getmtime(txt_path)
        )
        if needs_convert:
            try:
                convert_json_cookies(json_path, txt_path)
                logger.info("Converted cookie JSON for %s", platform)
            except Exception:
                logger.exception("Failed converting cookie JSON for %s", platform)


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده. فایل .env رو چک کن.")

    os.makedirs(COOKIES_DIR, exist_ok=True)
    auto_convert_cookie_jsons()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
