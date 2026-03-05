"""
🎵 Telegram Music Bot
Функции: загрузка треков, поиск, скачивание, топ популярных
Требования: pip install python-telegram-bot==20.7 aiosqlite
"""

import logging
import asyncio
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ─── Настройки ────────────────────────────────────────────────────────────────
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"   # ← вставьте токен от @BotFather
DB_PATH   = "music_bot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── База данных ──────────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     TEXT NOT NULL,
                title       TEXT NOT NULL,
                artist      TEXT,
                duration    INTEGER DEFAULT 0,
                uploaded_by INTEGER NOT NULL,
                plays       INTEGER DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id     INTEGER PRIMARY KEY,
                state       TEXT,
                data        TEXT,
                menu_msg_id INTEGER
            )
        """)
        await db.commit()


async def set_state(user_id: int, state: str, data: str = "", menu_msg_id: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_state (user_id, state, data, menu_msg_id) VALUES (?,?,?,?)",
            (user_id, state, data, menu_msg_id)
        )
        await db.commit()


async def get_state(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT state, data, menu_msg_id FROM user_state WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return (row[0], row[1], row[2]) if row else (None, "", 0)


async def clear_state(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))
        await db.commit()


# ─── Удаление сообщений ───────────────────────────────────────────────────────
async def delete_message_safe(bot, chat_id: int, msg_id: int):
    if not msg_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


# ─── Универсальная отправка меню ─────────────────────────────────────────────
async def send_menu(bot, chat_id: int, user_id: int, text: str, keyboard: InlineKeyboardMarkup):
    """Удаляет предыдущее меню бота и отправляет новое."""
    _, __, old_msg_id = await get_state(user_id)
    if old_msg_id:
        await delete_message_safe(bot, chat_id, old_msg_id)
    new_msg = await bot.send_message(
        chat_id      = chat_id,
        text         = text,
        parse_mode   = "Markdown",
        reply_markup = keyboard
    )
    await set_state(user_id, "", "", new_msg.message_id)
    return new_msg


# ─── Главное меню ─────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Поиск трека",   callback_data="search")],
        [InlineKeyboardButton("🎵 Мои треки",      callback_data="my_tracks")],
        [InlineKeyboardButton("🔥 Топ популярных", callback_data="top")],
        [InlineKeyboardButton("⬆️ Загрузить трек", callback_data="upload_info")],
    ])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass
    await send_menu(ctx.bot, chat_id, user_id,
        "🎵 *Музыкальный бот*\n\nДобро пожаловать! Выберите действие:",
        main_menu_keyboard()
    )


async def menu_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass
    await send_menu(ctx.bot, chat_id, user_id, "🎵 Главное меню:", main_menu_keyboard())


# ─── Обработка кнопок ─────────────────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    async def show(text, keyboard):
        await send_menu(ctx.bot, chat_id, user_id, text, keyboard)

    if data == "main_menu":
        await show("🎵 Главное меню:", main_menu_keyboard())

    elif data == "search":
        _, __, old = await get_state(user_id)
        if old:
            await delete_message_safe(ctx.bot, chat_id, old)
        new_msg = await ctx.bot.send_message(
            chat_id      = chat_id,
            text         = "🔍 Введите название трека или исполнителя:",
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="main_menu")
            ]])
        )
        await set_state(user_id, "searching", "", new_msg.message_id)

    elif data == "my_tracks":
        await show_user_tracks(ctx.bot, chat_id, user_id)

    elif data == "upload_info":
        await show(
            "⬆️ *Загрузка трека*\n\n"
            "Просто отправьте аудио-файл в этот чат.\n"
            "Поддерживаются форматы: MP3, FLAC, OGG, M4A и другие.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        )

    elif data == "top":
        await show_top(ctx.bot, chat_id, user_id)

    elif data.startswith("play_"):
        track_id = int(data.split("_")[1])
        await send_track(ctx.bot, chat_id, user_id, track_id)

    elif data.startswith("my_tracks_page_"):
        page = int(data.split("_")[-1])
        await show_user_tracks(ctx.bot, chat_id, user_id, page)


# ─── Мои треки ────────────────────────────────────────────────────────────────
async def show_user_tracks(bot, chat_id: int, user_id: int, page: int = 0):
    limit  = 8
    offset = page * limit
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, artist, plays FROM tracks WHERE uploaded_by=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ) as cur:
            tracks = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*) FROM tracks WHERE uploaded_by=?", (user_id,)
        ) as cur:
            total = (await cur.fetchone())[0]

    if not tracks:
        await send_menu(bot, chat_id, user_id,
            "🎵 У вас пока нет загруженных треков.\n\nОтправьте аудио-файл, чтобы добавить его!",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        )
        return

    buttons = []
    for t in tracks:
        label = f"🎵 {t[2] + ' — ' if t[2] else ''}{t[1]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"play_{t[0]}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"my_tracks_page_{page-1}"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"my_tracks_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])

    await send_menu(bot, chat_id, user_id,
        f"🎵 *Мои треки* ({total} шт.):",
        InlineKeyboardMarkup(buttons)
    )


# ─── Топ популярных ───────────────────────────────────────────────────────────
async def show_top(bot, chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, artist, plays FROM tracks ORDER BY plays DESC LIMIT 10"
        ) as cur:
            tracks = await cur.fetchall()

    if not tracks:
        await send_menu(bot, chat_id, user_id,
            "🔥 Пока нет треков. Будьте первым — загрузите музыку!",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        )
        return

    buttons = []
    for i, t in enumerate(tracks, 1):
        label = f"{i}. {t[2] + ' — ' if t[2] else ''}{t[1]} ({t[3]} ▶)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"play_{t[0]}")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])

    await send_menu(bot, chat_id, user_id, "🔥 *Топ популярных треков:*", InlineKeyboardMarkup(buttons))


# ─── Воспроизведение трека ────────────────────────────────────────────────────
async def send_track(bot, chat_id: int, user_id: int, track_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_id, title, artist FROM tracks WHERE id=?", (track_id,)
        ) as cur:
            track = await cur.fetchone()
        if track:
            await db.execute("UPDATE tracks SET plays=plays+1 WHERE id=?", (track_id,))
            await db.commit()

    if not track:
        return

    title_str = f"{track[2] + ' — ' if track[2] else ''}{track[1]}"

    state, prev_audio_id, old_menu_id = await get_state(user_id)

    # Удаляем старое меню
    if old_menu_id:
        await delete_message_safe(bot, chat_id, old_menu_id)

    # Удаляем предыдущее аудио
    if prev_audio_id and str(prev_audio_id).isdigit():
        await delete_message_safe(bot, chat_id, int(prev_audio_id))

    # Отправляем меню "сейчас играет"
    menu_msg = await bot.send_message(
        chat_id      = chat_id,
        text         = f"▶️ *Сейчас играет:*\n🎵 {title_str}",
        parse_mode   = "Markdown",
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")
        ]])
    )

    # Отправляем аудио
    sent = await bot.send_audio(
        chat_id   = chat_id,
        audio     = track[0],
        title     = track[1],
        performer = track[2] or "",
    )

    await set_state(user_id, "", str(sent.message_id), menu_msg.message_id)


# ─── Получение аудио от пользователя ─────────────────────────────────────────
async def audio_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg     = update.message
    user_id = msg.from_user.id
    audio   = msg.audio

    title  = audio.title  or (audio.file_name or "Без названия").rsplit(".", 1)[0]
    artist = audio.performer or ""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tracks (file_id, title, artist, duration, uploaded_by) VALUES (?,?,?,?,?)",
            (audio.file_id, title, artist, audio.duration or 0, user_id)
        )
        await db.commit()

    state, data, old_msg_id = await get_state(user_id)
    if old_msg_id:
        await delete_message_safe(ctx.bot, msg.chat_id, old_msg_id)

    new_msg = await msg.reply_text(
        f"✅ *{artist + ' — ' if artist else ''}{title}* загружен!\n\nЧто хотите сделать?",
        parse_mode   = "Markdown",
        reply_markup = main_menu_keyboard()
    )
    await set_state(user_id, "", "", new_msg.message_id)


# ─── Текстовые сообщения (поиск) ─────────────────────────────────────────────
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id                  = update.effective_user.id
    text                     = update.message.text.strip()
    state, extra, old_msg_id = await get_state(user_id)
    chat_id                  = update.effective_chat.id

    async def reply_under(out_text, keyboard):
        if old_msg_id:
            await delete_message_safe(ctx.bot, chat_id, old_msg_id)
        new_msg = await update.message.reply_text(
            out_text,
            parse_mode   = "Markdown",
            reply_markup = keyboard
        )
        await set_state(user_id, "", "", new_msg.message_id)

    if state == "searching":
        query_str = f"%{text}%"
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id, title, artist, plays FROM tracks "
                "WHERE title LIKE ? OR artist LIKE ? ORDER BY plays DESC LIMIT 10",
                (query_str, query_str)
            ) as cur:
                results = await cur.fetchall()

        if not results:
            await reply_under(
                f"😔 По запросу *{text}* ничего не найдено.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Искать снова", callback_data="search")],
                    [InlineKeyboardButton("◀️ Главное меню",  callback_data="main_menu")]
                ])
            )
        else:
            buttons = []
            for t in results:
                label = f"🎵 {t[2] + ' — ' if t[2] else ''}{t[1]} ({t[3]} ▶)"
                buttons.append([InlineKeyboardButton(label, callback_data=f"play_{t[0]}")])
            buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
            await reply_under(f"🔍 Результаты по *{text}*:", InlineKeyboardMarkup(buttons))

    else:
        await reply_under("🎵 Главное меню:", main_menu_keyboard())


# ─── Запуск ───────────────────────────────────────────────────────────────────
def main():
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  menu_command))
    app.add_handler(MessageHandler(filters.AUDIO, audio_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
