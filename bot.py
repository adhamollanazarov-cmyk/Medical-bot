# bot_pg.py — Railway PostgreSQL versiyasi
# SQLite o'rniga psycopg2 ishlatiladi
# O'zgarishlar: sqlite3 → psycopg2, ? → %s, AUTOINCREMENT → SERIAL

import os
import asyncio
from datetime import datetime
from contextlib import contextmanager
from dotenv import load_dotenv
load_dotenv()
from aiogram.types import WebAppInfo
import psycopg2
import psycopg2.extras
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== SOZLAMALAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
ADMIN_IDS      = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]
DATABASE_URL   = os.getenv("DATABASE_URL")  # Railway avtomatik beradi

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# ===================== TARJIMALAR =====================
TEXTS = {
    "uz": {
        "welcome": (
            "👋 *Shifo Yordamchi Botga Xush Kelibsiz!*\n\n"
            "Bu bot orqali:\n"
            "• 🤖 AI yordamida simptomlaringizni tahlil qilasiz\n"
            "• 👨‍⚕️ Kerakli mutaxassisni topasiz\n"
            "• 📞 Doktor bilan bog'lanasiz\n\n"
            "Boshlash uchun ismingizni kiriting 👤"
        ),
        "welcome_back":     "👋 Xush kelibsiz, *{name}*!\n\nQuyidan bo'limni tanlang:",
        "ask_name":         "👤 *Ismingizni kiriting:*",
        "name_saved":       "✅ Salom, *{name}*!\n\n📅 *Yosh guruhingizni tanlang:*",
        "name_too_short":   "⚠️ Iltimos, to'liq ismingizni kiriting:",
        "ask_region":       "✅ *{age}* — saqlandi!\n\n📍 *Qaysi viloyatdasiz?*",
        "reg_done": (
            "🎉 *Ro'yxatdan o'tish yakunlandi!*\n\n"
            "👤 Ism: *{name}*\n"
            "📅 Yosh: *{age}*\n"
            "📍 Viloyat: *{region}*\n\n"
            "Endi AI shifokor sizga aniqroq tavsiya bera oladi.\n\n"
            "Quyidan bo'limni tanlang:"
        ),
        "main_menu":        "👋 *Shifo Yordamchi*\n\nQuyidan bo'limni tanlang:",
        "btn_ai":           "🩺 AI bilan suhbat",
        "btn_doctors":      "👨‍⚕️ Barcha doktorlar",
        "btn_by_spec":      "🔍 Mutaxassislik bo'yicha",
        "btn_admin":        "⚙️ Admin panel",
        "btn_home":         "🏠 Bosh sahifa",
        "btn_back":         "◀️ Orqaga",
        "btn_stop_ai":      "❌ Suhbatni tugatish",
        "btn_lang":         "🌐 Tilni o'zgartirish",
        "ai_started":       "🩺 *AI suhbat boshlandi!*\n\nQayeringiz og'riyapti yoki qanday noqulaylik sezmoqdasiz? Batafsil yozing.",
        "analyzing":        "🔍 Tahlil qilinmoqda...",
        "recommend_found":  "{text}\n\n✅ *Tavsiya: {spec}*\n\nBizda quyidagi {spec}lar mavjud:",
        "recommend_none":   "{text}\n\n✅ *Tavsiya: {spec}*\n\n⚠️ Hozirda bu mutaxassisimiz mavjud emas.",
        "error":            "⚠️ Xatolik: {err}\n\n/start bosing.",
        "doctors_title":    "👨‍⚕️ *Bizning doktorlarimiz*\n\nJami: {count} ta mutaxassis\n\nMutaxassislikni tanlang:",
        "no_doctors":       "😔 Hozirda doktorlar mavjud emas.",
        "spec_title":       "👨‍⚕️ *{spec}lar:*\n\nBiror doktorni tanlang:",
        "pick_spec":        "🔍 *Mutaxassislik tanlang:*",
        "doc_not_found":    "Doktor topilmadi!",
        "doc_info":         "👨‍⚕️ *{name}*\n\n🔬 Mutaxassislik: {spec}\n📞 Telefon: {phone}\n\nℹ️ {desc}",
        "age_under18":      "👶 18 yoshgacha",
        "age_18_35":        "🧑 18–35 yosh",
        "age_36_55":        "🧔 36–55 yosh",
        "age_over56":       "👴 56 yoshdan yuqori",
        "lang_changed":     "✅ Til o'zgartirildi: O'zbek tili",
        "choose_lang":      "🌐 Tilni tanlang:\nSelect language:\nВыберите язык:",
        "system_prompt": (
            "Sen tibbiy yordamchi botsan. Faqat o'ZBEK TILIDA javob ber.\n"
            "1. Foydalanuvchidan simptomlar haqida 2-3 savol so'ra.\n"
            "2. Keyin qaysi mutaxassis kerakligini ayt.\n"
            "Mavjud mutaxassislar: {specs}\n"
            "Foydalanuvchi: {profile}\n"
            "QOIDALAR:\n"
            "- Tibbiy tashxis QO'YMA — faqat yo'naltir.\n"
            "- Jiddiy simptom bo'lsa DARHOL tez yordam chaqirishni ayt.\n"
            "- Yetarli ma'lumot bo'lgach javob oxiriga qo'sh:\nTAVSIYA: <mutaxassis>\n"
        ),
    },
    "ru": {
        "welcome": (
            "👋 *Добро пожаловать в Shifo Yordamchi!*\n\n"
            "С помощью этого бота вы можете:\n"
            "• 🤖 Анализировать симптомы с помощью ИИ\n"
            "• 👨‍⚕️ Найти нужного специалиста\n"
            "• 📞 Связаться с врачом\n\n"
            "Для начала введите ваше имя 👤"
        ),
        "welcome_back":     "👋 Добро пожаловать, *{name}*!\n\nВыберите раздел:",
        "ask_name":         "👤 *Введите ваше имя:*",
        "name_saved":       "✅ Привет, *{name}*!\n\n📅 *Выберите возрастную группу:*",
        "name_too_short":   "⚠️ Пожалуйста, введите полное имя:",
        "ask_region":       "✅ *{age}* — сохранено!\n\n📍 *В каком регионе вы находитесь?*",
        "reg_done": (
            "🎉 *Регистрация завершена!*\n\n"
            "👤 Имя: *{name}*\n"
            "📅 Возраст: *{age}*\n"
            "📍 Регион: *{region}*\n\n"
            "Теперь ИИ-врач сможет давать вам более точные рекомендации.\n\n"
            "Выберите раздел:"
        ),
        "main_menu":        "👋 *Shifo Yordamchi*\n\nВыберите раздел:",
        "btn_ai":           "🩺 Чат с ИИ",
        "btn_doctors":      "👨‍⚕️ Все врачи",
        "btn_by_spec":      "🔍 По специализации",
        "btn_admin":        "⚙️ Панель администратора",
        "btn_home":         "🏠 Главная",
        "btn_back":         "◀️ Назад",
        "btn_stop_ai":      "❌ Завершить беседу",
        "btn_lang":         "🌐 Изменить язык",
        "ai_started":       "🩺 *Чат с ИИ начат!*\n\nЧто вас беспокоит? Опишите симптомы подробно.",
        "analyzing":        "🔍 Анализирую...",
        "recommend_found":  "{text}\n\n✅ *Рекомендация: {spec}*\n\nДоступные специалисты {spec}:",
        "recommend_none":   "{text}\n\n✅ *Рекомендация: {spec}*\n\n⚠️ Данный специалист сейчас недоступен.",
        "error":            "⚠️ Ошибка: {err}\n\nНажмите /start.",
        "doctors_title":    "👨‍⚕️ *Наши врачи*\n\nВсего: {count} специалистов\n\nВыберите специализацию:",
        "no_doctors":       "😔 Врачей пока нет.",
        "spec_title":       "👨‍⚕️ *{spec}:*\n\nВыберите врача:",
        "pick_spec":        "🔍 *Выберите специализацию:*",
        "doc_not_found":    "Врач не найден!",
        "doc_info":         "👨‍⚕️ *{name}*\n\n🔬 Специализация: {spec}\n📞 Телефон: {phone}\n\nℹ️ {desc}",
        "age_under18":      "👶 До 18 лет",
        "age_18_35":        "🧑 18–35 лет",
        "age_36_55":        "🧔 36–55 лет",
        "age_over56":       "👴 Старше 56",
        "lang_changed":     "✅ Язык изменён: Русский",
        "choose_lang":      "🌐 Tilni tanlang:\nSelect language:\nВыберите язык:",
        "system_prompt": (
            "Ты медицинский ассистент-бот. Отвечай ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.\n"
            "1. Задай 2-3 уточняющих вопроса о симптомах.\n"
            "2. Затем укажи, к какому специалисту обратиться.\n"
            "Доступные специалисты: {specs}\n"
            "Пользователь: {profile}\n"
            "ПРАВИЛА:\n"
            "- НЕ ставь диагнозы — только направляй.\n"
            "- При серьёзных симптомах немедленно советуй вызвать скорую.\n"
            "- Когда соберёшь достаточно данных, добавь в конце:\nТАВСИЯ: <специалист>\n"
        ),
    },
    "en": {
        "welcome": (
            "👋 *Welcome to Shifo Yordamchi!*\n\n"
            "With this bot you can:\n"
            "• 🤖 Analyze your symptoms with AI\n"
            "• 👨‍⚕️ Find the right specialist\n"
            "• 📞 Contact a doctor\n\n"
            "To get started, enter your name 👤"
        ),
        "welcome_back":     "👋 Welcome back, *{name}*!\n\nChoose a section:",
        "ask_name":         "👤 *Enter your name:*",
        "name_saved":       "✅ Hello, *{name}*!\n\n📅 *Select your age group:*",
        "name_too_short":   "⚠️ Please enter your full name:",
        "ask_region":       "✅ *{age}* — saved!\n\n📍 *Which region are you in?*",
        "reg_done": (
            "🎉 *Registration complete!*\n\n"
            "👤 Name: *{name}*\n"
            "📅 Age: *{age}*\n"
            "📍 Region: *{region}*\n\n"
            "Now the AI doctor can give you more accurate advice.\n\n"
            "Choose a section:"
        ),
        "main_menu":        "👋 *Shifo Yordamchi*\n\nChoose a section:",
        "btn_ai":           "🩺 AI Chat",
        "btn_doctors":      "👨‍⚕️ All Doctors",
        "btn_by_spec":      "🔍 By Specialty",
        "btn_admin":        "⚙️ Admin Panel",
        "btn_home":         "🏠 Home",
        "btn_back":         "◀️ Back",
        "btn_stop_ai":      "❌ End Chat",
        "btn_lang":         "🌐 Change Language",
        "ai_started":       "🩺 *AI chat started!*\n\nWhat symptoms are you experiencing? Please describe in detail.",
        "analyzing":        "🔍 Analyzing...",
        "recommend_found":  "{text}\n\n✅ *Recommendation: {spec}*\n\nAvailable {spec} doctors:",
        "recommend_none":   "{text}\n\n✅ *Recommendation: {spec}*\n\n⚠️ No specialists available at the moment.",
        "error":            "⚠️ Error: {err}\n\nPress /start.",
        "doctors_title":    "👨‍⚕️ *Our Doctors*\n\nTotal: {count} specialists\n\nSelect a specialty:",
        "no_doctors":       "😔 No doctors available.",
        "spec_title":       "👨‍⚕️ *{spec}:*\n\nChoose a doctor:",
        "pick_spec":        "🔍 *Select specialty:*",
        "doc_not_found":    "Doctor not found!",
        "doc_info":         "👨‍⚕️ *{name}*\n\n🔬 Specialty: {spec}\n📞 Phone: {phone}\n\nℹ️ {desc}",
        "age_under18":      "👶 Under 18",
        "age_18_35":        "🧑 18–35",
        "age_36_55":        "🧔 36–55",
        "age_over56":       "👴 Over 56",
        "lang_changed":     "✅ Language changed: English",
        "choose_lang":      "🌐 Tilni tanlang:\nSelect language:\nВыберите язык:",
        "system_prompt": (
            "You are a medical assistant bot. Reply ONLY IN ENGLISH.\n"
            "1. Ask 2-3 clarifying questions about symptoms.\n"
            "2. Then indicate which specialist to see.\n"
            "Available specialists: {specs}\n"
            "User profile: {profile}\n"
            "RULES:\n"
            "- Do NOT diagnose — only guide.\n"
            "- For serious symptoms, immediately advise calling emergency services.\n"
            "- Once you have enough info, append to the end:\nTAVSIYA: <specialist>\n"
        ),
    },
}

def t(lang: str, key: str, **kwargs) -> str:
    """Tarjima olish yordamchi funksiyasi."""
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, TEXTS["uz"].get(key, key))
    return text.format(**kwargs) if kwargs else text

# ===================== FSM STATES =====================
class UserReg(StatesGroup):
    lang      = State()
    full_name = State()
    age       = State()
    region    = State()

class AiChat(StatesGroup):
    chatting = State()

class AdminAdd(StatesGroup):
    name    = State()
    spec    = State()
    phone   = State()
    desc    = State()
    photo   = State()

class AdminEdit(StatesGroup):
    choose_field = State()
    new_value    = State()
    new_photo    = State()


# ===================== DATABASE — PostgreSQL =====================
# SQLite farqi:
#   sqlite3.connect(DB)  →  psycopg2.connect(DATABASE_URL)
#   ?                    →  %s
#   AUTOINCREMENT        →  SERIAL
#   INTEGER PRIMARY KEY  →  SERIAL PRIMARY KEY
#   ON CONFLICT(user_id) DO UPDATE  →  ON CONFLICT (user_id) DO UPDATE (bir xil)

@contextmanager
def get_conn():
    """PostgreSQL ulanish context manager."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        c = conn.cursor()

        # Doctors jadvali
        c.execute("""
            CREATE TABLE IF NOT EXISTS doctors (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                specialty   TEXT NOT NULL,
                phone       TEXT NOT NULL,
                description TEXT,
                photo_id    TEXT,
                is_active   INTEGER DEFAULT 1
            )
        """)

        # Users jadvali
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       BIGINT PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                full_name     TEXT,
                age_group     TEXT,
                region        TEXT,
                lang          TEXT DEFAULT 'uz',
                is_registered INTEGER DEFAULT 0,
                joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Analytics jadvali
        c.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id            SERIAL PRIMARY KEY,
                user_id       BIGINT,
                symptom_text  TEXT,
                specialty     TEXT,
                doctor_id     INTEGER,
                event_type    TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Demo doktorlar — faqat jadval bo'sh bo'lsa
        c.execute("SELECT COUNT(*) FROM doctors")
        if c.fetchone()[0] == 0:
            demo = [
                ("Dr. Alisher Karimov",  "Kardiolog",       "+998901234567", "Yurak va qon tomir kasalliklari mutaxassisi. 15 yillik tajriba."),
                ("Dr. Malika Tosheva",   "Nevropatolog",    "+998901234568", "Bosh og'rig'i, insult, asab kasalliklari bo'yicha mutaxassis."),
                ("Dr. Bobur Yusupov",    "Gastroenterolog", "+998901234569", "Oshqozon, jigar, ichaklarni davolash mutaxassisi."),
                ("Dr. Dilnoza Rahimova", "Pulmonolog",      "+998901234570", "O'pka va nafas yo'llari kasalliklari mutaxassisi."),
                ("Dr. Jasur Mirzaev",    "Ortoped",         "+998901234571", "Suyak, bo'g'im va mushak kasalliklari bo'yicha mutaxassis."),
                ("Dr. Feruza Nazarova",  "Endokrinolog",    "+998901234572", "Qandli diabet, qalqonsimon bez mutaxassisi."),
                ("Dr. Sardor Holmatov",  "Terapevt",        "+998901234573", "Umumiy kasalliklar va profilaktika mutaxassisi."),
                ("Dr. Nozima Ergasheva", "Ginekolog",       "+998901234574", "Xotin-qizlar sog'lig'i mutaxassisi."),
            ]
            c.executemany(
                "INSERT INTO doctors (name,specialty,phone,description) VALUES (%s,%s,%s,%s)",
                demo
            )

# ===================== DB: DOCTORS =====================
def db_all_doctors():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE is_active=1")
        return c.fetchall()

def db_doctors_by_spec(specialty):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE is_active=1 AND specialty ILIKE %s",
            (f"%{specialty}%",)
        )
        return c.fetchall()

def db_doctor_by_id(doc_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE id=%s", (doc_id,))
        return c.fetchone()

def db_add_doctor(name, spec, phone, desc, photo_id=None):
    with get_conn() as conn:
        conn.cursor().execute(
            "INSERT INTO doctors (name,specialty,phone,description,photo_id) VALUES (%s,%s,%s,%s,%s)",
            (name, spec, phone, desc, photo_id)
        )

def db_delete_doctor(doc_id):
    with get_conn() as conn:
        conn.cursor().execute("UPDATE doctors SET is_active=0 WHERE id=%s", (doc_id,))

def db_update_doctor(doc_id, field, value):
    allowed = {"name", "specialty", "phone", "description", "photo_id"}
    if field not in allowed:
        return
    with get_conn() as conn:
        conn.cursor().execute(f"UPDATE doctors SET {field}=%s WHERE id=%s", (value, doc_id))

# ===================== DB: USERS =====================
def db_upsert_user(user_id, username, first_name):
    with get_conn() as conn:
        conn.cursor().execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                last_seen  = CURRENT_TIMESTAMP,
                username   = EXCLUDED.username,
                first_name = EXCLUDED.first_name
        """, (user_id, username or "", first_name or ""))

def db_get_user(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_id,full_name,age_group,region,is_registered,lang FROM users WHERE user_id=%s",
            (user_id,)
        )
        row = c.fetchone()
    if not row:
        return None
    return {"user_id": row[0], "full_name": row[1], "age_group": row[2],
            "region": row[3], "is_registered": row[4], "lang": row[5] or "uz"}

def db_set_lang(user_id, lang):
    with get_conn() as conn:
        conn.cursor().execute("UPDATE users SET lang=%s WHERE user_id=%s", (lang, user_id))

def db_complete_registration(user_id, full_name, age_group, region, lang):
    with get_conn() as conn:
        conn.cursor().execute("""
            UPDATE users SET full_name=%s, age_group=%s, region=%s, lang=%s, is_registered=1
            WHERE user_id=%s
        """, (full_name, age_group, region, lang, user_id))

# ===================== DB: ANALYTICS =====================
def db_log_event(user_id, event_type, symptom_text=None, specialty=None, doctor_id=None):
    with get_conn() as conn:
        conn.cursor().execute("""
            INSERT INTO analytics (user_id,symptom_text,specialty,doctor_id,event_type)
            VALUES (%s,%s,%s,%s,%s)
        """, (user_id, symptom_text, specialty, doctor_id, event_type))

def db_get_stats():
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE DATE(joined_at) = CURRENT_DATE")
        today_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE is_registered = 1")
        registered = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM analytics WHERE event_type = 'ai_recommendation'")
        total_queries = c.fetchone()[0]

        c.execute("""
            SELECT COUNT(*) FROM analytics
            WHERE event_type = 'ai_recommendation'
              AND created_at >= NOW() - INTERVAL '7 days'
        """)
        week_queries = c.fetchone()[0]

        c.execute("""
            SELECT specialty, COUNT(*) AS cnt FROM analytics
            WHERE event_type = 'ai_recommendation' AND specialty IS NOT NULL
            GROUP BY specialty ORDER BY cnt DESC LIMIT 5
        """)
        top_specialties = c.fetchall()

        c.execute("""
            SELECT d.name, d.specialty, COUNT(*) AS cnt
            FROM analytics a JOIN doctors d ON a.doctor_id = d.id
            WHERE a.event_type = 'doctor_viewed'
            GROUP BY d.name, d.specialty ORDER BY cnt DESC LIMIT 5
        """)
        top_doctors = c.fetchall()

        c.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt FROM analytics
            WHERE event_type = 'ai_recommendation'
              AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY day ORDER BY day
        """)
        daily_stats = c.fetchall()

        c.execute("""
            SELECT region, COUNT(*) AS cnt FROM users
            WHERE region IS NOT NULL AND is_registered = 1
            GROUP BY region ORDER BY cnt DESC LIMIT 5
        """)
        region_stats = c.fetchall()

        c.execute("""
            SELECT age_group, COUNT(*) AS cnt FROM users
            WHERE age_group IS NOT NULL AND is_registered = 1
            GROUP BY age_group ORDER BY cnt DESC
        """)
        age_stats = c.fetchall()

        c.execute("""
            SELECT lang, COUNT(*) AS cnt FROM users
            WHERE lang IS NOT NULL GROUP BY lang ORDER BY cnt DESC
        """)
        lang_stats = c.fetchall()

    return dict(total_users=total_users, today_users=today_users, registered=registered,
                total_queries=total_queries, week_queries=week_queries,
                top_specialties=top_specialties, top_doctors=top_doctors,
                daily_stats=daily_stats, region_stats=region_stats,
                age_stats=age_stats, lang_stats=lang_stats)


# ===================== FOYDALANUVCHI TILINI OLISH =====================
def get_lang(user_id: int) -> str:
    """Foydalanuvchi tilini bazadan olish, default: uz."""
    user = db_get_user(user_id)
    return user["lang"] if user else "uz"

# ===================== AI =====================
async def ask_ai(history: list, user_id: int, lang: str) -> str:
    doctors = db_all_doctors()
    specs   = ", ".join(set(d[2] for d in doctors))

    profile = ""
    user = db_get_user(user_id)
    if user and user["is_registered"]:
        profile = f"Ism: {user['full_name']}, Yosh: {user['age_group']}, Viloyat: {user['region']}"

    system_content = t(lang, "system_prompt", specs=specs, profile=profile or "Noma'lum")
    messages = [{"role": "system", "content": system_content}] + history

    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, max_tokens=1000
    )
    return resp.choices[0].message.content

def extract_specialty(text):
    for line in text.splitlines():
        if line.strip().startswith("TAVSIYA:"):
            return line.replace("TAVSIYA:", "").strip()
    return None

def clean_ai_text(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("TAVSIYA:")).strip()

# ===================== KLAVIATURALAR =====================
def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbek tili",  callback_data="setlang_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="setlang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English",      callback_data="setlang_en")],
    ])

def main_kb(user_id: int, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text="🌐 Mini App ni ochish",
            web_app=WebAppInfo(url="https://medaai-production-5029.up.railway.app/app/")
        )],
        [InlineKeyboardButton(text=t(lang,"btn_ai"),      callback_data="start_ai")],
        [InlineKeyboardButton(text=t(lang,"btn_doctors"), callback_data="all_doctors")],
        [InlineKeyboardButton(text=t(lang,"btn_by_spec"), callback_data="by_spec")],
        [InlineKeyboardButton(text=t(lang,"btn_lang"),    callback_data="change_lang")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text=t(lang,"btn_admin"), callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def stop_ai_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"btn_stop_ai"), callback_data="stop_ai")]
    ])

def home_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"btn_home"), callback_data="main")]
    ])

async def safe_edit(cq: CallbackQuery, text: str, reply_markup=None, parse_mode="Markdown"):
    try:
        await cq.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await cq.message.delete()
        except Exception:
            pass
        await cq.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

# ===================== /start =====================
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    db_upsert_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    db_log_event(msg.from_user.id, "start")

    user = db_get_user(msg.from_user.id)
    if user and user["is_registered"]:
        lang = user["lang"]
        await msg.answer(
            t(lang, "welcome_back", name=user["full_name"]),
            reply_markup=main_kb(msg.from_user.id, lang),
            parse_mode="Markdown"
        )
    else:
        # Yangi foydalanuvchi — avval til tanlash
        await state.set_state(UserReg.lang)
        await msg.answer(
            t("uz", "choose_lang"),
            reply_markup=lang_kb()
        )

# ===================== TIL TANLASH (RO'YXATDAN O'TISH) =====================
@dp.callback_query(F.data.startswith("setlang_"), UserReg.lang)
async def reg_set_lang(cq: CallbackQuery, state: FSMContext):
    lang = cq.data.removeprefix("setlang_")
    await state.update_data(lang=lang)
    await state.set_state(UserReg.full_name)
    await cq.message.edit_text(
        t(lang, "welcome") + "\n\n" + t(lang, "ask_name"),
        parse_mode="Markdown"
    )
    await cq.answer()

# ===================== TIL O'ZGARTIRISH (ASOSIY MENYU) =====================
@dp.callback_query(F.data == "change_lang")
async def cb_change_lang(cq: CallbackQuery):
    await safe_edit(cq, t("uz", "choose_lang"), reply_markup=lang_kb())
    await cq.answer()

@dp.callback_query(F.data.startswith("setlang_"))
async def cb_setlang(cq: CallbackQuery, state: FSMContext):
    # Ro'yxatdan o'tish oqimida bo'lmagan holat (til o'zgartirish)
    lang = cq.data.removeprefix("setlang_")
    db_set_lang(cq.from_user.id, lang)
    await safe_edit(cq,
        t(lang, "main_menu"),
        reply_markup=main_kb(cq.from_user.id, lang),
    )
    await cq.answer(t(lang, "lang_changed"))

# ===================== RO'YXATDAN O'TISH: ISM =====================
@dp.message(UserReg.full_name)
async def reg_full_name(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    name = msg.text.strip()
    if len(name) < 2:
        await msg.answer(t(lang, "name_too_short"))
        return
    await state.update_data(full_name=name)
    await state.set_state(UserReg.age)
    rows = [
        [InlineKeyboardButton(text=t(lang,"age_under18"), callback_data="age_under18")],
        [InlineKeyboardButton(text=t(lang,"age_18_35"),   callback_data="age_18_35")],
        [InlineKeyboardButton(text=t(lang,"age_36_55"),   callback_data="age_36_55")],
        [InlineKeyboardButton(text=t(lang,"age_over56"),  callback_data="age_over56")],
    ]
    await msg.answer(
        t(lang, "name_saved", name=name),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

# ===================== RO'YXATDAN O'TISH: YOSH =====================
@dp.callback_query(F.data.startswith("age_"), UserReg.age)
async def reg_age(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    age_map = {
        "age_under18": t(lang,"age_under18"),
        "age_18_35":   t(lang,"age_18_35"),
        "age_36_55":   t(lang,"age_36_55"),
        "age_over56":  t(lang,"age_over56"),
    }
    age_group = age_map.get(cq.data, cq.data)
    await state.update_data(age_group=age_group)
    await state.set_state(UserReg.region)
    rows = [
        [InlineKeyboardButton(text="🏙 Toshkent shahri",   callback_data="reg_Toshkent shahri")],
        [InlineKeyboardButton(text="🌆 Toshkent viloyati", callback_data="reg_Toshkent viloyati")],
        [InlineKeyboardButton(text="🌿 Xorazm",            callback_data="reg_Xorazm")],
        [InlineKeyboardButton(text="🏔 Samarqand",         callback_data="reg_Samarqand")],
        [InlineKeyboardButton(text="🌅 Farg'ona",          callback_data="reg_Fargona")],
        [InlineKeyboardButton(text="🌾 Qashqadaryo",       callback_data="reg_Qashqadaryo")],
        [InlineKeyboardButton(text="🏜 Buxoro",            callback_data="reg_Buxoro")],
        [InlineKeyboardButton(text="🌊 Namangan",          callback_data="reg_Namangan")],
        [InlineKeyboardButton(text="🗺 Boshqa / Другое / Other", callback_data="reg_Boshqa")],
    ]
    await cq.message.edit_text(
        t(lang, "ask_region", age=age_group),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await cq.answer()

# ===================== RO'YXATDAN O'TISH: VILOYAT =====================
@dp.callback_query(F.data.startswith("reg_"), UserReg.region)
async def reg_region(cq: CallbackQuery, state: FSMContext):
    region = cq.data.removeprefix("reg_")
    data   = await state.get_data()
    lang   = data.get("lang", "uz")
    db_complete_registration(cq.from_user.id, data["full_name"], data["age_group"], region, lang)
    db_log_event(cq.from_user.id, "registered")
    await state.clear()
    await cq.message.edit_text(
        t(lang, "reg_done", name=data["full_name"], age=data["age_group"], region=region),
        reply_markup=main_kb(cq.from_user.id, lang),
        parse_mode="Markdown"
    )
    await cq.answer()

# ===================== ASOSIY MENYU =====================
@dp.callback_query(F.data == "main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_lang(cq.from_user.id)
    await safe_edit(cq, t(lang,"main_menu"), reply_markup=main_kb(cq.from_user.id, lang))
    await cq.answer()

# ===================== AI CHAT =====================
@dp.callback_query(F.data == "start_ai")
async def cb_start_ai(cq: CallbackQuery, state: FSMContext):
    lang = get_lang(cq.from_user.id)
    await state.set_state(AiChat.chatting)
    await state.update_data(history=[])
    db_log_event(cq.from_user.id, "ai_chat_started")
    await cq.message.edit_text(
        t(lang, "ai_started"),
        reply_markup=stop_ai_kb(lang),
        parse_mode="Markdown"
    )
    await cq.answer()

@dp.callback_query(F.data == "stop_ai")
async def cb_stop_ai(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_lang(cq.from_user.id)
    await safe_edit(cq, t(lang,"main_menu"), reply_markup=main_kb(cq.from_user.id, lang))
    await cq.answer()

@dp.message(AiChat.chatting)
async def ai_chat_msg(msg: Message, state: FSMContext):
    lang    = get_lang(msg.from_user.id)
    data    = await state.get_data()
    history = data.get("history", [])
    history.append({"role": "user", "content": msg.text})

    wait = await msg.answer(t(lang, "analyzing"))
    try:
        ai_text   = await ask_ai(history, msg.from_user.id, lang)
        history.append({"role": "assistant", "content": ai_text})
        await state.update_data(history=history)
        specialty = extract_specialty(ai_text)
        display   = clean_ai_text(ai_text)
        await wait.delete()

        if specialty:
            db_log_event(msg.from_user.id, "ai_recommendation",
                         symptom_text=history[0]["content"][:300], specialty=specialty)
            doctors = db_doctors_by_spec(specialty)
            if doctors:
                body = t(lang, "recommend_found", text=display, spec=specialty)
                rows = [[InlineKeyboardButton(text=f"👨‍⚕️ {d[1]}", callback_data=f"doc_{d[0]}")] for d in doctors]
            else:
                body = t(lang, "recommend_none", text=display, spec=specialty)
                rows = []
            rows.append([InlineKeyboardButton(text=t(lang,"btn_home"), callback_data="main")])
            await msg.answer(body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")
            await state.clear()
        else:
            await msg.answer(display, reply_markup=stop_ai_kb(lang), parse_mode="Markdown")
    except Exception as e:
        await wait.delete()
        await msg.answer(t(lang, "error", err=str(e)))
        await state.clear()

# ===================== DOKTORLAR =====================
@dp.callback_query(F.data == "all_doctors")
async def cb_all_doctors(cq: CallbackQuery):
    lang = get_lang(cq.from_user.id)
    db_log_event(cq.from_user.id, "doctors_viewed")
    doctors = db_all_doctors()
    if not doctors:
        await safe_edit(cq, t(lang,"no_doctors"), reply_markup=home_kb(lang))
        return
    specs = {}
    for d in doctors:
        specs.setdefault(d[2], []).append(d)
    rows = [[InlineKeyboardButton(text=f"📋 {s} ({len(ds)} ta)", callback_data=f"spec_{s}")] for s, ds in specs.items()]
    rows.append([InlineKeyboardButton(text=t(lang,"btn_home"), callback_data="main")])
    await safe_edit(cq, t(lang,"doctors_title", count=len(doctors)), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data == "by_spec")
async def cb_by_spec(cq: CallbackQuery):
    lang  = get_lang(cq.from_user.id)
    specs = sorted(set(d[2] for d in db_all_doctors()))
    rows  = [[InlineKeyboardButton(text=f"🔬 {s}", callback_data=f"spec_{s}")] for s in specs]
    rows.append([InlineKeyboardButton(text=t(lang,"btn_home"), callback_data="main")])
    await safe_edit(cq, t(lang,"pick_spec"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data.startswith("spec_"))
async def cb_spec(cq: CallbackQuery):
    lang    = get_lang(cq.from_user.id)
    spec    = cq.data.removeprefix("spec_")
    doctors = db_doctors_by_spec(spec)
    rows    = [[InlineKeyboardButton(text=f"👨‍⚕️ {d[1]}", callback_data=f"doc_{d[0]}")] for d in doctors]
    rows.append([InlineKeyboardButton(text=t(lang,"btn_back"), callback_data="all_doctors")])
    await safe_edit(cq, t(lang,"spec_title",spec=spec), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data.startswith("doc_"))
async def cb_doc(cq: CallbackQuery):
    lang   = get_lang(cq.from_user.id)
    doc_id = int(cq.data.removeprefix("doc_"))
    d      = db_doctor_by_id(doc_id)
    if not d:
        await cq.answer(t(lang,"doc_not_found"), show_alert=True)
        return
    db_log_event(cq.from_user.id, "doctor_viewed", specialty=d[2], doctor_id=d[0])
    text = t(lang, "doc_info", name=d[1], spec=d[2], phone=d[3], desc=d[4] or "—")
    rows = [
        [InlineKeyboardButton(text=t(lang,"btn_back"), callback_data=f"spec_{d[2]}")],
        [InlineKeyboardButton(text=t(lang,"btn_home"), callback_data="main")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if d[5]:
        try:
            await cq.message.delete()
        except Exception:
            pass
        await cq.message.answer_photo(photo=d[5], caption=text, reply_markup=kb, parse_mode="Markdown")
    else:
        await cq.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await cq.answer()

# ===================== ADMIN PANEL =====================
@dp.callback_query(F.data == "admin")
async def cb_admin(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(text="📊 Statistika",                     callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Yangi doktor qo'shish",          callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Doktorni tahrirlash",            callback_data="admin_edit_list")],
        [InlineKeyboardButton(text="📋 Doktorlar ro'yxati (o'chirish)", callback_data="admin_list")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa",                    callback_data="main")],
    ]
    await safe_edit(cq, "⚙️ *Admin Panel*\n\nNimani qilmoqchisiz?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    try:
        s = db_get_stats()
    except Exception as e:
        await cq.answer(f"❌ Xatolik: {e}", show_alert=True)
        return

    def fmt_list(items, bar=True):
        if not items:
            return "  Hali ma'lumot yo'q\n"
        out = ""
        for row in items:
            label, cnt = row[0], row[-1]
            b = " " + "█"*min(cnt,10) if bar else ""
            out += f"  • {label}: {cnt} ta{b}\n"
        return out

    # Til statistikasi
    lang_names = {"uz": "O'zbek", "ru": "Русский", "en": "English"}
    lang_lines = ""
    for lang_code, cnt in s["lang_stats"]:
        lang_lines += f"  • {lang_names.get(lang_code, lang_code)}: {cnt} ta\n"
    if not lang_lines:
        lang_lines = "  Hali ma'lumot yo'q\n"

    daily = ""
    for day, cnt in s["daily_stats"]:
        daily += f"  {day}: {cnt} ta {'▓'*min(cnt,15)}\n"
    if not daily:
        daily = "  Hali ma'lumot yo'q\n"

    text = (
        f"📊 *Shifo Yordamchi — Statistika*\n"
        f"_{datetime.now().strftime('%d.%m.%Y %H:%M')}_\n\n"
        f"👥 *Foydalanuvchilar:*\n"
        f"  • Jami kirganlar: *{s['total_users']}*\n"
        f"  • Ro'yxatdan o'tganlar: *{s['registered']}*\n"
        f"  • Bugun yangi: *{s['today_users']}*\n\n"
        f"🌐 *Tillar bo'yicha:*\n{lang_lines}\n"
        f"🩺 *AI So'rovlar:*\n"
        f"  • Jami: *{s['total_queries']}*\n"
        f"  • Bu hafta: *{s['week_queries']}*\n\n"
        f"📍 *Viloyatlar:*\n{fmt_list(s['region_stats'])}\n"
        f"📅 *Yosh guruhlari:*\n{fmt_list(s['age_stats'], bar=False)}\n"
        f"🔬 *Top mutaxassislar:*\n{fmt_list(s['top_specialties'])}\n"
        f"👨‍⚕️ *Top shifokorlar:*\n{fmt_list(s['top_doctors'])}\n"
        f"📈 *Kunlik (7 kun):*\n{daily}"
    )
    rows = [[InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")]]
    await safe_edit(cq, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

# ===================== ADMIN: DOKTOR QO'SHISH =====================
@dp.callback_query(F.data == "admin_add")
async def cb_admin_add(cq: CallbackQuery, state: FSMContext):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    await state.set_state(AdminAdd.name)
    await cq.message.edit_text(
        "👨‍⚕️ *Yangi doktor qo'shish*\n\nDoktorning to'liq ismini kiriting:",
        parse_mode="Markdown"
    )
    await cq.answer()

@dp.message(AdminAdd.name)
async def adm_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await state.set_state(AdminAdd.spec)
    await msg.answer("✅ Ism saqlandi!\n\nMutaxassisligini kiriting:")

@dp.message(AdminAdd.spec)
async def adm_spec(msg: Message, state: FSMContext):
    await state.update_data(spec=msg.text)
    await state.set_state(AdminAdd.phone)
    await msg.answer("✅ Mutaxassislik saqlandi!\n\nTelefon raqamini kiriting:")

@dp.message(AdminAdd.phone)
async def adm_phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(AdminAdd.desc)
    await msg.answer("✅ Telefon saqlandi!\n\nQisqacha tavsif kiriting:")

@dp.message(AdminAdd.desc)
async def adm_desc(msg: Message, state: FSMContext):
    await state.update_data(desc=msg.text)
    await state.set_state(AdminAdd.photo)
    rows = [[InlineKeyboardButton(text="⏭ Rasmsiz qo'shish", callback_data="admin_skip_photo")]]
    await msg.answer("✅ Tavsif saqlandi!\n\n📸 Doktor rasmini yuboring:",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.message(AdminAdd.photo, F.photo)
async def adm_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    pid  = msg.photo[-1].file_id
    db_add_doctor(data["name"], data["spec"], data["phone"], data["desc"], pid)
    await state.clear()
    rows = [[InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin")]]
    await msg.answer_photo(photo=pid,
        caption=f"✅ *Doktor qo'shildi!*\n\n👨‍⚕️ {data['name']}\n🔬 {data['spec']}\n📞 {data['phone']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_skip_photo", AdminAdd.photo)
async def adm_skip_photo(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db_add_doctor(data["name"], data["spec"], data["phone"], data["desc"], None)
    await state.clear()
    rows = [[InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin")]]
    await cq.message.edit_text(
        f"✅ *Doktor qo'shildi!*\n\n👨‍⚕️ {data['name']}\n🔬 {data['spec']}\n📞 {data['phone']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")
    await cq.answer()

# ===================== ADMIN: DOKTOR TAHRIRLASH =====================
@dp.callback_query(F.data == "admin_edit_list")
async def cb_admin_edit_list(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doctors = db_all_doctors()
    if not doctors:
        await safe_edit(cq, "😔 Doktorlar mavjud emas.", reply_markup=home_kb("uz"))
        return
    rows = [[InlineKeyboardButton(text=f"✏️ {d[1]} ({d[2]})", callback_data=f"aedit_{d[0]}")] for d in doctors]
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")])
    await safe_edit(cq, "✏️ *Tahrirlash uchun doktorni tanlang:*",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data.startswith("aedit_"))
async def cb_admin_edit_choose(cq: CallbackQuery, state: FSMContext):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doc_id = int(cq.data.removeprefix("aedit_"))
    d = db_doctor_by_id(doc_id)
    if not d:
        await cq.answer("Doktor topilmadi!", show_alert=True)
        return
    await state.set_state(AdminEdit.choose_field)
    await state.update_data(edit_doc_id=doc_id)
    has_photo = "✅ Bor" if d[5] else "❌ Yo'q"
    rows = [
        [InlineKeyboardButton(text=f"👤 Ism: {d[1]}",          callback_data="ef_name")],
        [InlineKeyboardButton(text=f"🔬 Mutaxassislik: {d[2]}", callback_data="ef_spec")],
        [InlineKeyboardButton(text=f"📞 Telefon: {d[3]}",       callback_data="ef_phone")],
        [InlineKeyboardButton(text="ℹ️ Tavsif",                 callback_data="ef_desc")],
        [InlineKeyboardButton(text=f"📸 Rasm: {has_photo}",     callback_data="ef_photo")],
        [InlineKeyboardButton(text="◀️ Orqaga",                 callback_data="admin_edit_list")],
    ]
    await safe_edit(cq, f"✏️ *{d[1]}* — qaysi maydonni o'zgartirish?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

FIELD_LABELS = {
    "ef_name":  ("name",        "👤 Yangi ismni kiriting:"),
    "ef_spec":  ("specialty",   "🔬 Yangi mutaxassislikni kiriting:"),
    "ef_phone": ("phone",       "📞 Yangi telefon raqamini kiriting:"),
    "ef_desc":  ("description", "ℹ️ Yangi tavsifni kiriting:"),
}

@dp.callback_query(F.data.in_({"ef_name","ef_spec","ef_phone","ef_desc"}), AdminEdit.choose_field)
async def cb_edit_text_field(cq: CallbackQuery, state: FSMContext):
    field_key, prompt = FIELD_LABELS[cq.data]
    await state.update_data(edit_field=field_key)
    await state.set_state(AdminEdit.new_value)
    rows = [[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_edit_list")]]
    await safe_edit(cq, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.message(AdminEdit.new_value)
async def cb_edit_save_value(msg: Message, state: FSMContext):
    data   = await state.get_data()
    doc_id = data["edit_doc_id"]
    field  = data["edit_field"]
    db_update_doctor(doc_id, field, msg.text)
    await state.clear()
    d = db_doctor_by_id(doc_id)
    rows = [
        [InlineKeyboardButton(text="✏️ Yana tahrirlash", callback_data=f"aedit_{doc_id}")],
        [InlineKeyboardButton(text="⚙️ Admin panel",     callback_data="admin")],
    ]
    await msg.answer(
        f"✅ *Saqlandi!*\n\n👤 {d[1]}\n🔬 {d[2]}\n📞 {d[3]}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")

@dp.callback_query(F.data == "ef_photo", AdminEdit.choose_field)
async def cb_edit_photo_field(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminEdit.new_photo)
    rows = [
        [InlineKeyboardButton(text="🗑 Rasmni o'chirish", callback_data="edit_remove_photo")],
        [InlineKeyboardButton(text="❌ Bekor qilish",     callback_data="admin_edit_list")],
    ]
    await safe_edit(cq, "📸 *Yangi rasmni yuboring:*",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.message(AdminEdit.new_photo, F.photo)
async def cb_edit_save_photo(msg: Message, state: FSMContext):
    data     = await state.get_data()
    doc_id   = data["edit_doc_id"]
    photo_id = msg.photo[-1].file_id
    db_update_doctor(doc_id, "photo_id", photo_id)
    await state.clear()
    rows = [
        [InlineKeyboardButton(text="✏️ Yana tahrirlash", callback_data=f"aedit_{doc_id}")],
        [InlineKeyboardButton(text="⚙️ Admin panel",     callback_data="admin")],
    ]
    await msg.answer_photo(photo=photo_id, caption="✅ *Rasm yangilandi!*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")

@dp.callback_query(F.data == "edit_remove_photo", AdminEdit.new_photo)
async def cb_edit_remove_photo(cq: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    doc_id = data["edit_doc_id"]
    db_update_doctor(doc_id, "photo_id", None)
    await state.clear()
    rows = [
        [InlineKeyboardButton(text="✏️ Yana tahrirlash", callback_data=f"aedit_{doc_id}")],
        [InlineKeyboardButton(text="⚙️ Admin panel",     callback_data="admin")],
    ]
    await safe_edit(cq, "✅ *Rasm o'chirildi!*", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

# ===================== ADMIN: O'CHIRISH =====================
@dp.callback_query(F.data == "admin_list")
async def cb_admin_list(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doctors = db_all_doctors()
    if not doctors:
        await safe_edit(cq, "😔 Doktorlar mavjud emas.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")]]))
        return
    rows = [[InlineKeyboardButton(text=f"🗑 {d[1]} ({d[2]})", callback_data=f"adel_{d[0]}")] for d in doctors]
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")])
    await safe_edit(cq, "🗑 *O'chirish uchun doktorni tanlang:*",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data.startswith("adel_"))
async def cb_admin_del(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    db_delete_doctor(int(cq.data.removeprefix("adel_")))
    await cq.answer("✅ Doktor o'chirildi!", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="📊 Statistika",                     callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Yangi doktor qo'shish",          callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Doktorni tahrirlash",            callback_data="admin_edit_list")],
        [InlineKeyboardButton(text="📋 Doktorlar ro'yxati (o'chirish)", callback_data="admin_list")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa",                    callback_data="main")],
    ]
    await safe_edit(cq, "⚙️ *Admin Panel*", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

# ===================== MAIN =====================
# ===================== MAIN =====================
async def main():
    if not DATABASE_URL:
        print("❌ DATABASE_URL topilmadi! Railway da PostgreSQL qo'shing.")
        return
    init_db()
    print("✅ PostgreSQL ulanish muvaffaqiyatli")
    print("✅ Jadvallar tayyor")
    print("🤖 Shifo Yordamchi Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
