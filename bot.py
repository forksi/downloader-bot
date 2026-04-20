"""
Manzil Batch 2026 - Telegram Bot
Sends PDFs directly and downloads HLS videos via yt-dlp.

Requirements:
    pip install -r requirements.txt
"""

import os
import re
import tempfile
import subprocess
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

load_dotenv()

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TXT_FILE  = os.getenv("TXT_FILE", "content.txt")
MAX_TELEGRAM_FILE_MB = 50


def load_content(filepath: str) -> list[dict]:
    items = []
    with open(filepath, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(.+?):\s*(https?://\S+)$", line)
            if match:
                title = match.group(1).strip()
                url   = match.group(2).strip()
                kind  = "pdf" if url.lower().endswith(".pdf") else "video"
                items.append({"index": i, "title": title, "url": url, "type": kind})
    return items


CONTENT = load_content(TXT_FILE)
log.info(f"Loaded {len(CONTENT)} items — "
         f"{sum(1 for c in CONTENT if c['type']=='pdf')} PDFs, "
         f"{sum(1 for c in CONTENT if c['type']=='video')} videos")


def fmt_item(item: dict) -> str:
    icon = "📄" if item["type"] == "pdf" else "🎬"
    return f"{icon} [{item['index']}] {item['title']}"


def chunk_text(text: str, size: int = 4000):
    while text:
        yield text[:size]
        text = text[size:]


def search_items(query: str) -> list[dict]:
    q = query.lower()
    return [c for c in CONTENT if q in c["title"].lower()]


async def send_long(update: Update, text: str):
    for part in chunk_text(text):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def send_pdf(update: Update, item: dict):
    await update.message.reply_text(
        f"⬇️ Downloading PDF: <b>{item['title']}</b>…", parse_mode=ParseMode.HTML)
    try:
        r = requests.get(item["url"], timeout=60, stream=True)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in r.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = tmp.name
        safe_name = re.sub(r'[^\w\s-]', '', item['title'])[:60] + ".pdf"
        with open(tmp_path, "rb") as f:
            await update.message.reply_document(document=f, filename=safe_name,
                                                caption=f"📄 {item['title']}")
        os.unlink(tmp_path)
    except Exception as e:
        log.error(f"PDF error: {e}")
        await update.message.reply_text(f"❌ Failed to download PDF.\nDirect link: {item['url']}")


async def send_video(update: Update, item: dict):
    msg = await update.message.reply_text(
        f"🎬 Downloading: <b>{item['title']}</b>\n⏳ Please wait…", parse_mode=ParseMode.HTML)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "video.%(ext)s")
        cmd = ["yt-dlp", "--no-playlist", "--merge-output-format", "mp4",
               "--concurrent-fragments", "4", "-o", out_template, item["url"]]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(result.stderr[-800:] if result.stderr else "yt-dlp failed")
            files = list(Path(tmpdir).glob("*.mp4")) or list(Path(tmpdir).iterdir())
            if not files:
                raise FileNotFoundError("No output file found")
            video_path = files[0]
            size_mb = video_path.stat().st_size / (1024 * 1024)
            log.info(f"Downloaded '{item['title']}' → {size_mb:.1f} MB")
            await msg.edit_text(f"📤 Uploading ({size_mb:.1f} MB)…")
            with open(video_path, "rb") as vf:
                if size_mb > MAX_TELEGRAM_FILE_MB:
                    await update.message.reply_document(
                        document=vf,
                        filename=re.sub(r'[^\w\s-]', '', item['title'])[:60] + ".mp4",
                        caption=f"🎬 {item['title']}")
                else:
                    await update.message.reply_video(video=vf, caption=f"🎬 {item['title']}",
                                                     supports_streaming=True)
            await msg.delete()
        except subprocess.TimeoutExpired:
            await msg.edit_text(f"⏱️ Timed out: {item['title']}")
        except Exception as e:
            log.error(f"Video error: {e}")
            await msg.edit_text(f"❌ Failed: {str(e)[:300]}")


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pdfs   = sum(1 for c in CONTENT if c['type'] == 'pdf')
    videos = sum(1 for c in CONTENT if c['type'] == 'video')
    await update.message.reply_text(
        f"👋 <b>Manzil Batch 2026 Bot</b>\n\n"
        f"📦 Total: <b>{len(CONTENT)}</b> items — {pdfs} PDFs, {videos} videos\n\n"
        f"📚 <b>Commands:</b>\n"
        f"  /list — Browse all content\n"
        f"  /pdfs — List only PDFs\n"
        f"  /videos — List only videos\n"
        f"  /get &lt;number&gt; — Download by number\n"
        f"  /search &lt;keyword&gt; — Search by topic",
        parse_mode=ParseMode.HTML)


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [f"📋 <b>All Content ({len(CONTENT)} items)</b>\n"]
    for item in CONTENT:
        lines.append(fmt_item(item))
    lines.append("\n💡 Use /get &lt;number&gt; to download.")
    await send_long(update, "\n".join(lines))


async def cmd_pdfs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pdfs = [c for c in CONTENT if c["type"] == "pdf"]
    lines = [f"📄 <b>PDFs ({len(pdfs)} files)</b>\n"]
    for item in pdfs:
        lines.append(fmt_item(item))
    lines.append("\n💡 Use /get &lt;number&gt; to download.")
    await send_long(update, "\n".join(lines))


async def cmd_videos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    videos = [c for c in CONTENT if c["type"] == "video"]
    lines = [f"🎬 <b>Videos ({len(videos)} files)</b>\n"]
    for item in videos:
        lines.append(fmt_item(item))
    lines.append("\n💡 Use /get &lt;number&gt; to download.")
    await send_long(update, "\n".join(lines))


async def cmd_get(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: /get <number>\nExample: /get 10")
        return
    idx  = int(ctx.args[0])
    item = next((c for c in CONTENT if c["index"] == idx), None)
    if not item:
        await update.message.reply_text(f"❌ No item with number {idx}.")
        return
    if item["type"] == "pdf":
        await send_pdf(update, item)
    else:
        await send_video(update, item)


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /search <keyword>\nExample: /search pronoun")
        return
    query   = " ".join(ctx.args)
    results = search_items(query)
    if not results:
        await update.message.reply_text(f"🔍 No results for '<b>{query}</b>'.", parse_mode=ParseMode.HTML)
        return
    lines = [f"🔍 <b>Results for '{query}' ({len(results)} found)</b>\n"]
    for item in results:
        lines.append(fmt_item(item))
    lines.append("\n💡 Use /get &lt;number&gt; to download.")
    await send_long(update, "\n".join(lines))


def main():
    if not BOT_TOKEN:
        log.error("❌ BOT_TOKEN not set!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("pdfs",   cmd_pdfs))
    app.add_handler(CommandHandler("videos", cmd_videos))
    app.add_handler(CommandHandler("get",    cmd_get))
    app.add_handler(CommandHandler("search", cmd_search))
    log.info("🤖 Bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
