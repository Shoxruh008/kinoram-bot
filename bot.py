import logging
import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ===================== SOZLAMALAR =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8794449146:AAGCp00RHcUuCJpPRZ0ESTEC-yzKcai7ajg")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "5371043130").split(",")))

DB_FILE = "database.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ===================== DATABASE =====================

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                code INTEGER PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL,
                file_type TEXT NOT NULL DEFAULT 'video',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL
            )
        """)
        conn.commit()
    logger.info("Database tayyor.")

# --- Video operatsiyalari ---

def db_add_video(file_id: str, file_unique_id: str, file_type: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(code) as max_code FROM videos").fetchone()
        next_code = (row["max_code"] or 0) + 1
        conn.execute(
            "INSERT INTO videos (code, file_id, file_unique_id, file_type) VALUES (?, ?, ?, ?)",
            (next_code, file_id, file_unique_id, file_type)
        )
        conn.commit()
    return next_code

def db_get_video(code: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM videos WHERE code = ?", (code,)).fetchone()

def db_all_videos():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM videos ORDER BY code").fetchall()

def db_delete_video(code: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM videos WHERE code = ?", (code,))
        conn.commit()
        return cur.rowcount > 0

# --- Kanal operatsiyalari ---

def db_add_channel(username: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO channels (username) VALUES (?)", (username,))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def db_remove_channel(username: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM channels WHERE username = ?", (username,))
        conn.commit()
        return cur.rowcount > 0

def db_all_channels() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT username FROM channels").fetchall()
        return [r["username"] for r in rows]

# ===================== YORDAMCHI FUNKSIYALAR =====================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    channels = db_all_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed

def build_sub_keyboard(not_subscribed: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in not_subscribed:
        link = f"https://t.me/{ch.lstrip('@')}"
        buttons.append([InlineKeyboardButton(f"📢 {ch}", url=link)])
    buttons.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

async def send_video_to_chat(chat_id: int, code: int, context: ContextTypes.DEFAULT_TYPE):
    video = db_get_video(code)
    if not video:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ <b>{code}</b> kodli kino mavjud emas.",
            parse_mode="HTML"
        )
        return

    caption = f"🎬 Kino kodi: <b>{code}</b>"
    try:
        if video["file_type"] == "video":
            await context.bot.send_video(chat_id=chat_id, video=video["file_id"], caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_document(chat_id=chat_id, document=video["file_id"], caption=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Video yuborishda xato: {e}")
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Video yuborishda xatolik. Admin bilan bog'laning.")

# ===================== HANDLERLAR =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 <b>Kino botga xush kelibsiz!</b>\n\n"
        "Kino kodini yuboring va filmni oling.\n"
        "Masalan: <code>1</code>",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        text = (
            "📖 <b>Admin buyruqlari:</b>\n\n"
            "🎬 Video yuboring → avtomatik kod beriladi\n"
            "/listvideos — barcha videolar\n"
            "/deletevideo [kod] — videoni o'chirish\n\n"
            "📢 <b>Kanal boshqaruvi:</b>\n"
            "/channelsetting — kanallar menyusi\n"
            "/addchannel @kanal — kanal qo'shish\n"
            "/removechannel @kanal — kanal o'chirish\n"
            "/listchannels — kanallar ro'yxati\n"
        )
    else:
        text = (
            "📖 <b>Foydalanish:</b>\n\n"
            "Kino kodini yuboring (masalan: <code>1</code>)\n"
            "Bot sizga filmni yuboradi! 🎬"
        )
    await update.message.reply_text(text, parse_mode="HTML")

# --- Admin: video qabul ---

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    video = update.message.video
    document = update.message.document

    if video:
        file_id = video.file_id
        file_unique_id = video.file_unique_id
        file_type = "video"
    elif document:
        file_id = document.file_id
        file_unique_id = document.file_unique_id
        file_type = "document"
    else:
        return

    code = db_add_video(file_id, file_unique_id, file_type)
    await update.message.reply_text(
        f"✅ Video saqlandi!\n"
        f"🎬 Kino kodi: <b>{code}</b>\n\n"
        f"Userlar <code>{code}</code> deb yozsa bu filmni oladi.",
        parse_mode="HTML"
    )

# --- Admin: video ro'yxati ---

async def list_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    videos = db_all_videos()
    if not videos:
        await update.message.reply_text("📭 Hozircha hech qanday video yo'q.")
        return

    lines = ["🎬 <b>Saqlangan videolar:</b>\n"]
    for v in videos:
        lines.append(f"🔹 Kod: <code>{v['code']}</code> | {v['created_at'][:10]}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# --- Admin: video o'chirish ---

async def delete_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❗ Ishlatish: /deletevideo [kod]\nMasalan: /deletevideo 3")
        return

    code = int(context.args[0])
    if db_delete_video(code):
        await update.message.reply_text(f"🗑 <b>{code}</b> kodli video o'chirildi.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ <b>{code}</b> kodli video topilmadi.", parse_mode="HTML")

# --- Admin: kanal sozlamalari ---

async def channel_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    channels = db_all_channels()
    text = "📢 <b>Majburiy obuna kanallari:</b>\n"
    if channels:
        for ch in channels:
            text += f"  • {ch}\n"
    else:
        text += "  (hozircha yo'q)\n"

    text += (
        "\n➕ Kanal qo'shish: /addchannel @username\n"
        "➖ Kanal o'chirish: /removechannel @username\n"
        "📋 Ro'yxat: /listchannels"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("❗ Ishlatish: /addchannel @kanalUsername")
        return

    ch = context.args[0]
    if not ch.startswith("@"):
        ch = "@" + ch

    if db_add_channel(ch):
        await update.message.reply_text(f"✅ <b>{ch}</b> majburiy obunaga qo'shildi.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"⚠️ <b>{ch}</b> allaqachon ro'yxatda bor.", parse_mode="HTML")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("❗ Ishlatish: /removechannel @kanalUsername")
        return

    ch = context.args[0]
    if not ch.startswith("@"):
        ch = "@" + ch

    if db_remove_channel(ch):
        await update.message.reply_text(f"🗑 <b>{ch}</b> ro'yxatdan o'chirildi.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ <b>{ch}</b> topilmadi.", parse_mode="HTML")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    channels = db_all_channels()
    if not channels:
        await update.message.reply_text("📭 Majburiy obuna kanallari yo'q.")
        return

    text = "📢 <b>Majburiy obuna kanallari:</b>\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch}\n"
    await update.message.reply_text(text, parse_mode="HTML")

# --- User: kod kiritish ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❓ Kino kodini raqam ko'rinishida yuboring.\nMasalan: <code>1</code>",
            parse_mode="HTML"
        )
        return

    code = int(text)

    not_subscribed = await check_subscription(user.id, context)
    if not_subscribed:
        context.user_data["pending_code"] = code
        kb = build_sub_keyboard(not_subscribed)
        await update.message.reply_text(
            "⚠️ Filmni ko'rish uchun avval quyidagi kanallarga obuna bo'ling:",
            reply_markup=kb
        )
        return

    await send_video_to_chat(user.id, code, context)

# --- Callback: obuna tekshirish ---

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    not_subscribed = await check_subscription(user.id, context)
    if not_subscribed:
        kb = build_sub_keyboard(not_subscribed)
        await query.message.edit_text(
            "❌ Hali ham quyidagi kanallarga obuna bo'lmagansiz:",
            reply_markup=kb
        )
        return

    await query.message.delete()

    code = context.user_data.pop("pending_code", None)
    if code:
        await send_video_to_chat(user.id, code, context)
    else:
        await context.bot.send_message(
            chat_id=user.id,
            text="✅ Obuna tasdiqlandi! Endi kino kodini yuboring."
        )

# ===================== MAIN =====================

def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listvideos", list_videos))
    app.add_handler(CommandHandler("deletevideo", delete_video))
    app.add_handler(CommandHandler("channelsetting", channel_setting))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("removechannel", remove_channel))
    app.add_handler(CommandHandler("listchannels", list_channels))

    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))

    logger.info("✅ Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
