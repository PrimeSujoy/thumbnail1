import logging
from io import BytesIO

from dotenv import load_dotenv
from pymongo import MongoClient
from bson.binary import Binary

from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import config

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("cover-bot")

# -------------------- DB --------------------
mongo = MongoClient(config.DB_URI)
db = mongo[config.MONGODB_DATABASE]
thumbs = db["thumbnails"]   # { _id: user_id, data: <bytes>, mime: "image/jpeg" }
users = db["users"]         # { _id: user_id, first: str, last: str, username: str }

# Simple state: who is currently setting thumbnail
WAITING_THUMB = set()


def kb_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Set Thumbnail", callback_data="setthumb")],
        [InlineKeyboardButton("🗑 Remove Thumbnail", callback_data="delthumb")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])


async def ensure_user(update: Update):
    u = update.effective_user
    if not u:
        return
    users.update_one(
        {"_id": u.id},
        {"$set": {"first": u.first_name, "last": u.last_name, "username": u.username}},
        upsert=True,
    )


async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Optional log to channel if LOG_CHANNEL_ID is set."""
    if not config.LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(chat_id=int(config.LOG_CHANNEL_ID), text=text)
    except Exception:
        pass


# -------------------- Commands --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    await update.message.reply_text(
        "👋 <b>Instant Video Thumbnail Bot</b>\n\n"
        "✅ Use:\n"
        "• /setthumb → then send a photo\n"
        "• Send any video → I resend it with your saved thumbnail\n"
        "• /delthumb → remove thumbnail\n",
        parse_mode="HTML",
        reply_markup=kb_home(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ <b>How to use</b>\n\n"
        "1) /setthumb\n"
        "2) Send a <b>photo</b>\n"
        "3) Send a <b>video</b> → I apply the saved photo as thumbnail\n\n"
        "Tip: Use a clear 16:9 image for best results.",
        parse_mode="HTML",
    )


async def setthumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    WAITING_THUMB.add(update.effective_user.id)
    await update.message.reply_text("🖼 Now send me the <b>photo</b> to save as thumbnail.", parse_mode="HTML")


async def delthumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    thumbs.delete_one({"_id": update.effective_user.id})
    WAITING_THUMB.discard(update.effective_user.id)
    await update.message.reply_text("🗑 Thumbnail removed.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Public stats; OWNER_ID is kept but not required to use the bot."""
    total_users = users.count_documents({})
    total_thumbs = thumbs.count_documents({})
    await update.message.reply_text(
        f"📊 <b>Bot Stats</b>\n\n"
        f"👥 Users: <b>{total_users}</b>\n"
        f"🖼 Thumbnails saved: <b>{total_thumbs}</b>",
        parse_mode="HTML",
    )


# -------------------- Callbacks --------------------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "setthumb":
        WAITING_THUMB.add(q.from_user.id)
        await q.message.edit_text("🖼 Send the thumbnail photo now.", parse_mode="HTML")
        return

    if q.data == "delthumb":
        thumbs.delete_one({"_id": q.from_user.id})
        WAITING_THUMB.discard(q.from_user.id)
        await q.message.edit_text("🗑 Thumbnail removed.", parse_mode="HTML", reply_markup=kb_home())
        return

    if q.data == "help":
        await q.message.edit_text(
            "✅ <b>How to use</b>\n\n"
            "• /setthumb → then send a photo\n"
            "• Send a video → I resend it with your saved thumbnail\n"
            "• /delthumb → remove thumbnail",
            parse_mode="HTML",
            reply_markup=kb_home(),
        )
        return


# -------------------- Media --------------------
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    user_id = update.effective_user.id

    if user_id not in WAITING_THUMB:
        await update.message.reply_text("Send <b>/setthumb</b> first, then send the photo.", parse_mode="HTML")
        return

    ph = update.message.photo[-1]  # highest quality
    tg_file = await context.bot.get_file(ph.file_id)

    bio = BytesIO()
    await tg_file.download_to_memory(out=bio)
    data = bio.getvalue()

    thumbs.update_one(
        {"_id": user_id},
        {"$set": {"data": Binary(data), "mime": "image/jpeg"}},
        upsert=True,
    )

    WAITING_THUMB.discard(user_id)
    await update.message.reply_text("✅ Thumbnail saved! Now send me any video.")


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    user_id = update.effective_user.id

    doc = thumbs.find_one({"_id": user_id})
    if not doc:
        await update.message.reply_text("⚠️ No thumbnail saved. Use <b>/setthumb</b> first.", parse_mode="HTML")
        return

    thumb_bytes = bytes(doc["data"])
    thumb_file = InputFile(BytesIO(thumb_bytes), filename="thumb.jpg")

    v = update.message.video
    caption = update.message.caption or ""

    # Fast: uses Telegram file_id (no re-upload of the video file)
    await update.message.reply_video(
        video=v.file_id,
        caption=caption,
        thumbnail=thumb_file,
        supports_streaming=True,
    )

    # optional log
    await send_log(context, f"✅ Thumb applied | user={user_id} | video={v.file_unique_id}")


# -------------------- Main --------------------
def main():
    token = config.BOT_TOKEN
    if not token or token == "your_bot_token_here":
        raise SystemExit("Set BOT_TOKEN in env or config.py")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setthumb", setthumb))
    app.add_handler(CommandHandler("delthumb", delthumb))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))

    log.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
