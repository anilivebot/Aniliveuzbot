
import asyncio
import logging
import os
import sqlite3

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from dotenv import load_dotenv


# ==========================================
# 1. SOZLAMALAR
# ==========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

CHANNELS = [
    "@anilive_uz",
    "@narutouzbekbot",
    "@borutouzbekbot",
    "@vanpisuzbekbot"
]

API_URL = "https://api.jikan.moe/v4"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ==========================================
# 2. DATABASE
# ==========================================

db = sqlite3.connect("anime_bot.db")
db.execute("PRAGMA foreign_keys = ON")

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER,
    anime_id INTEGER,
    title TEXT,
    PRIMARY KEY (user_id, anime_id)
)
""")

db.commit()


def save_user(user_id, username):
    db.execute(
        "INSERT OR IGNORE INTO users VALUES (?, ?)",
        (user_id, username)
    )
    db.execute(
        "UPDATE users SET username = ? WHERE user_id = ?",
        (username, user_id)
    )
    db.commit()


def get_stats():
    return db.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]


def get_favorites(user_id):
    return db.execute(
        "SELECT anime_id, title FROM favorites WHERE user_id = ?",
        (user_id,)
    ).fetchall()


def toggle_favorite(user_id, anime_id, title):
    exists = db.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND anime_id=?",
        (user_id, anime_id)
    ).fetchone()

    if exists:
        db.execute(
            "DELETE FROM favorites WHERE user_id=? AND anime_id=?",
            (user_id, anime_id)
        )
        db.commit()
        return False

    db.execute(
        "INSERT INTO favorites VALUES (?, ?, ?)",
        (user_id, anime_id, title)
    )
    db.commit()
    return True


# ==========================================
# 3. FSM
# ==========================================

class SearchState(StatesGroup):
    waiting_for_name = State()


# ==========================================
# 4. API
# ==========================================

async def api_get(endpoint, params=None):
    try:
        timeout = aiohttp.ClientTimeout(total=25)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{API_URL}/{endpoint}",
                params=params
            ) as response:

                if response.status != 200:
                    logging.warning("API status: %s", response.status)
                    return None

                result = await response.json()
                return result.get("data")

    except Exception:
        logging.exception("API xatosi")
        return None


# ==========================================
# 5. OBUNA TEKSHIRISH
# ==========================================

async def check_subscription(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in ("left", "kicked"):
                return False

            if member.status == "restricted" and not member.is_member:
                return False

        except Exception:
            logging.exception("Obuna tekshirish xatosi: %s", channel)
            return False

    return True


def subscription_keyboard():
    buttons = []

    for channel in CHANNELS:
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {channel}",
                url=f"https://t.me/{channel[1:]}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def require_subscription(event):
    user_id = event.from_user.id

    if await check_subscription(user_id):
        return True

    text = (
        "🔒 ANILIVEUZBOT\n\n"
        "Botdan foydalanish uchun quyidagi "
        "kanallarga obuna bo'ling!\n\n"
        "Barcha kanallarga obuna bo'lgach, "
        "tekshirish tugmasini bosing."
    )

    if isinstance(event, Message):
        await event.answer(
            text,
            reply_markup=subscription_keyboard()
        )
    else:
        await event.answer(
            "❌ Avval barcha kanallarga obuna bo'ling!",
            show_alert=True
        )

    return False


# ==========================================
# 6. ASOSIY MENYU
# ==========================================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎬 Anime tavsiyalari",
                callback_data="recommend"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔍 Anime qidirish",
                callback_data="search"
            ),
            InlineKeyboardButton(
                text="⭐ Top 10",
                callback_data="top10"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎭 Janrlar",
                callback_data="genres"
            ),
            InlineKeyboardButton(
                text="❤️ Sevimlilar",
                callback_data="favorites"
            )
        ],
        [
            InlineKeyboardButton(
                text="ℹ️ Bot haqida",
                callback_data="about"
            )
        ]
    ])


async def send_menu(message):
    await message.answer(
        "🍥 ANILIVEUZBOT GA XUSH KELIBSIZ!\n\n"
        "Anime olamiga sayohatni boshlang!\n\n"
        "👇 Kerakli bo'limni tanlang:",
        reply_markup=main_menu()
    )


# ==========================================
# 7. ANIME TUGMALARI
# ==========================================

def anime_buttons(anime_id, title):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="❤️ Sevimlilarga qo'shish",
                callback_data=f"fav:{anime_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔗 MyAnimeList",
                url=f"https://myanimelist.net/anime/{anime_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏠 Bosh menyu",
                callback_data="menu"
            )
        ]
    ])


# ==========================================
# 8. ANIME MA'LUMOTINI CHIQARISH
# ==========================================

async def send_anime(message, anime):
    anime_id = anime.get("mal_id")
    title = anime.get("title") or "Noma'lum"
    english = anime.get("title_english") or "Mavjud emas"
    score = anime.get("score") or "Noma'lum"
    episodes = anime.get("episodes") or "Noma'lum"
    year = anime.get("year") or "Noma'lum"

    synopsis = anime.get("synopsis") or "Tavsif mavjud emas."

    if len(synopsis) > 550:
        synopsis = synopsis[:550] + "..."

    text = (
        f"🎬 {title}\n\n"
        f"🌍 Inglizcha nomi: {english}\n"
        f"⭐ Reyting: {score}\n"
        f"📺 Qismlar: {episodes}\n"
        f"📅 Yil: {year}\n\n"
        f"📝 Tavsif:\n{synopsis}"
    )

    image = (
        anime.get("images", {})
        .get("jpg", {})
        .get("image_url")
    )

    keyboard = anime_buttons(anime_id, title)

    if image:
        try:
            await message.answer_photo(
                photo=image,
                caption=text,
                reply_markup=keyboard
            )
            return
        except Exception:
            logging.exception("Anime rasmi yuborilmadi")

    await message.answer(
        text,
        reply_markup=keyboard
    )


# ==========================================
# 9. START
# ==========================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    save_user(
        message.from_user.id,
        message.from_user.username
    )

    if not await require_subscription(message):
        return

    await send_menu(message)


# ==========================================
# 10. OBUNANI QAYTA TEKSHIRISH
# ==========================================

@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):
    if not await check_subscription(callback.from_user.id):
        await callback.answer(
            "❌ Barcha kanallarga obuna bo'ling!",
            show_alert=True
        )
        return

    await callback.answer("✅ Obuna tasdiqlandi!")

    await callback.message.edit_text(
        "🎉 Obuna tasdiqlandi!\n\n"
        "Endi Aniliveuzbotdan foydalanishingiz mumkin.",
        reply_markup=main_menu()
    )


# ==========================================
# 11. BOSH MENYU
# ==========================================

@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery, state: FSMContext):
    if not await require_subscription(callback):
        return

    await state.clear()
    await callback.answer()

    await callback.message.answer(
        "🏠 ASOSIY MENYU",
        reply_markup=main_menu()
    )


# ==========================================
# 12. ANIME QIDIRISH
# ==========================================

@dp.callback_query(F.data == "search")
async def search_start(callback: CallbackQuery, state: FSMContext):
    if not await require_subscription(callback):
        return

    await state.set_state(SearchState.waiting_for_name)
    await callback.answer()

    await callback.message.answer(
        "🔍 Anime nomini yuboring.\n\n"
        "Masalan: Naruto, One Piece, Bleach"
    )


@dp.message(SearchState.waiting_for_name)
async def search_anime(message: Message, state: FSMContext):
    if not await require_subscription(message):
        await state.clear()
        return

    if not message.text:
        await message.answer("❗ Iltimos, anime nomini matn ko'rinishida yuboring.")
        return

    query = message.text.strip()

    if len(query) < 2 or len(query) > 100:
        await message.answer("❗ Anime nomini to'g'ri kiriting.")
        return

    await message.answer("🔎 Anime qidirilmoqda...")

    data = await api_get(
        "anime",
        {"q": query, "limit": 5}
    )

    if not data:
        await message.answer(
            "😔 Anime topilmadi yoki xizmat vaqtincha ishlamayapti."
        )
        await state.clear()
        return

    for anime in data:
        await send_anime(message, anime)

    await state.clear()


# ==========================================
# 13. TOP 10 ANIME
# ==========================================

@dp.callback_query(F.data == "top10")
async def top10(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    await callback.answer("⭐ Top 10 yuklanmoqda...")

    data = await api_get("top/anime", {"limit": 10})

    if not data:
        await callback.message.answer("❌ Ma'lumot topilmadi.")
        return

    text = "🏆 DUNYODAGI TOP 10 ANIME\n\n"

    for i, anime in enumerate(data, 1):
        title = anime.get("title", "Noma'lum")
        score = anime.get("score") or "Noma'lum"

        text += f"{i}. {title} — ⭐ {score}\n"

    await callback.message.answer(text)


# ==========================================
# 14. ANIME TAVSIYALARI
# ==========================================

@dp.callback_query(F.data == "recommend")
async def recommend(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    await callback.answer("🎬 Tavsiya tayyorlanmoqda...")

    anime = await api_get("random/anime")

    if anime:
        await send_anime(callback.message, anime)
    else:
        await callback.message.answer(
            "❌ Hozircha tavsiya olishning imkoni bo'lmadi."
        )


# ==========================================
# 15. JANRLAR
# ==========================================

GENRES = {
    "1": ("Action", 1),
    "2": ("Adventure", 2),
    "3": ("Comedy", 4),
    "4": ("Drama", 8),
    "5": ("Fantasy", 10),
    "6": ("Horror", 14),
    "7": ("Mystery", 7),
    "8": ("Romance", 22),
    "9": ("Sports", 30),
    "10": ("Supernatural", 37)
}


@dp.callback_query(F.data == "genres")
async def genres(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    buttons = []

    for genre_id, (name, _) in GENRES.items():
        buttons.append([
            InlineKeyboardButton(
                text=f"🎭 {name}",
                callback_data=f"genre:{genre_id}"
            )
        ])

    await callback.answer()

    await callback.message.answer(
        "🎭 ANIME JANRLARI\n\n"
        "O'zingizga yoqqan janrni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("genre:"))
async def genre_anime(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    key = callback.data.split(":")[1]

    if key not in GENRES:
        await callback.answer("Noto'g'ri janr!")
        return

    name, genre_id = GENRES[key]

    await callback.answer(f"🎭 {name}")

    data = await api_get(
        "anime",
        {
            "genres": genre_id,
            "order_by": "score",
            "sort": "desc",
            "limit": 5
        }
    )

    if not data:
        await callback.message.answer("❌ Anime topilmadi.")
        return

    for anime in data:
        await send_anime(callback.message, anime)


# ==========================================
# 16. SEVIMLILARGA QO'SHISH
# ==========================================

@dp.callback_query(F.data.startswith("fav:"))
async def favorite(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    try:
        anime_id = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Noto'g'ri anime ID!")
        return

    anime = await api_get(f"anime/{anime_id}")

    if not anime:
        await callback.answer("Anime ma'lumoti topilmadi!")
        return

    title = anime.get("title", "Noma'lum")

    added = toggle_favorite(
        callback.from_user.id,
        anime_id,
        title
    )

    if added:
        await callback.answer(
            "❤️ Sevimlilarga qo'shildi!",
            show_alert=True
        )
    else:
        await callback.answer(
            "🗑 Sevimlilardan o'chirildi!",
            show_alert=True
        )


# ==========================================
# 17. SEVIMLILAR
# ==========================================

@dp.callback_query(F.data == "favorites")
async def favorites(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    items = get_favorites(callback.from_user.id)

    if not items:
        await callback.answer()

        await callback.message.answer(
            "❤️ Hozircha sevimlilaringiz bo'sh.\n\n"
            "Anime topib, sevimlilarga qo'shing!"
        )
        return

    await callback.answer()

    buttons = []

    for anime_id, title in items[:30]:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {title[:40]}",
                callback_data=f"favdetail:{anime_id}"
            )
        ])

    await callback.message.answer(
        "❤️ SIZNING SEVIMLILARINGIZ",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("favdetail:"))
async def favorite_detail(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    anime_id = int(callback.data.split(":")[1])

    anime = await api_get(f"anime/{anime_id}")

    if anime:
        await callback.answer()
        await send_anime(callback.message, anime)
    else:
        await callback.answer("Anime topilmadi!")


# ==========================================
# 18. BOT HAQIDA
# ==========================================

@dp.callback_query(F.data == "about")
async def about(callback: CallbackQuery):
    if not await require_subscription(callback):
        return

    await callback.answer()

    await callback.message.answer(
        "🍥 ANILIVEUZBOT\n\n"
        "🇺🇿 O'zbekcha anime bot!\n\n"
        "🎬 Anime tavsiyalari\n"
        "🔍 Anime qidirish\n"
        "⭐ Top 10\n"
        "🎭 Janrlar\n"
        "❤️ Sevimlilar\n\n"
        "📚 Ma'lumotlar Jikan API orqali olinadi."
    )


# ==========================================
# 19. ADMIN PANEL
# ==========================================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Siz admin emassiz!")
        return

    total = get_stats()

    await message.answer(
        "👨‍💻 ADMIN PANEL\n\n"
        f"👥 Jami foydalanuvchilar: {total}\n\n"
        "⚙️ Aniliveuzbot boshqaruv paneli."
    )


# ==========================================
# 20. BOTNI ISHGA TUSHIRISH
# ==========================================

async def main():
    logging.info("Aniliveuzbot ishga tushmoqda...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
  
