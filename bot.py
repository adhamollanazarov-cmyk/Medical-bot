import os
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== SOZLAMALAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
ADMIN_IDS       = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ===================== FSM STATES =====================
class UserReg(StatesGroup):
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

# ===================== DATABASE =====================
DB = "medical_bot.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # --- Doctors jadvali ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            specialty   TEXT NOT NULL,
            phone       TEXT NOT NULL,
            description TEXT,
            photo_id    TEXT,
            is_active   INTEGER DEFAULT 1
        )
    """)
    try:
        c.execute("ALTER TABLE doctors ADD COLUMN photo_id TEXT")
    except Exception:
        pass

    # --- Foydalanuvchilar jadvali (YANGI) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            full_name   TEXT,
            age_group   TEXT,
            region      TEXT,
            is_registered INTEGER DEFAULT 0,
            joined_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Analytics jadvali (YANGI) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            symptom_text  TEXT,
            specialty     TEXT,
            doctor_id     INTEGER,
            event_type    TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Demo doktorlar
    c.execute("SELECT COUNT(*) FROM doctors")
    if c.fetchone()[0] == 0:
        demo = [
            ("Dr. Alisher Karimov",  "Kardiolog",        "+998901234567", "Yurak va qon tomir kasalliklari mutaxassisi. 15 yillik tajriba."),
            ("Dr. Malika Tosheva",   "Nevropatolog",     "+998901234568", "Bosh og'rig'i, insult, asab kasalliklari bo'yicha mutaxassis."),
            ("Dr. Bobur Yusupov",    "Gastroenterolog",  "+998901234569", "Oshqozon, jigar, ichaklarni davolash mutaxassisi."),
            ("Dr. Dilnoza Rahimova", "Pulmonolog",       "+998901234570", "O'pka va nafas yo'llari kasalliklari mutaxassisi."),
            ("Dr. Jasur Mirzaev",    "Ortoped",          "+998901234571", "Suyak, bo'g'im va mushak kasalliklari bo'yicha mutaxassis."),
            ("Dr. Feruza Nazarova",  "Endokrinolog",     "+998901234572", "Qandli diabet, qalqonsimon bez mutaxassisi."),
            ("Dr. Sardor Holmatov",  "Terapevt",         "+998901234573", "Umumiy kasalliklar va profilaktika mutaxassisi."),
            ("Dr. Nozima Ergasheva", "Ginekolog",        "+998901234574", "Xotin-qizlar sog'lig'i mutaxassisi."),
        ]
        c.executemany(
            "INSERT INTO doctors (name, specialty, phone, description) VALUES (?,?,?,?)", demo
        )

    conn.commit()
    conn.close()

# ===================== DB: DOCTORS =====================
def db_all_doctors():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE is_active=1"
    ).fetchall()
    conn.close()
    return rows

def db_doctors_by_spec(specialty: str):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE is_active=1 AND specialty LIKE ?",
        (f"%{specialty}%",)
    ).fetchall()
    conn.close()
    return rows

def db_doctor_by_id(doc_id: int):
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE id=?", (doc_id,)
    ).fetchone()
    conn.close()
    return row

def db_add_doctor(name, spec, phone, desc, photo_id=None):
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT INTO doctors (name,specialty,phone,description,photo_id) VALUES (?,?,?,?,?)",
        (name, spec, phone, desc, photo_id)
    )
    conn.commit()
    conn.close()

def db_delete_doctor(doc_id: int):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE doctors SET is_active=0 WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()

def db_update_doctor(doc_id: int, field: str, value: str):
    allowed = {"name", "specialty", "phone", "description", "photo_id"}
    if field not in allowed:
        return
    conn = sqlite3.connect(DB)
    conn.execute(f"UPDATE doctors SET {field}=? WHERE id=?", (value, doc_id))
    conn.commit()
    conn.close()

# ===================== DB: ANALYTICS (YANGI) =====================
def db_upsert_user(user_id: int, username: str, first_name: str):
    """Foydalanuvchini bazaga qo'shish yoki last_seen yangilash."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            last_seen = CURRENT_TIMESTAMP,
            username = excluded.username,
            first_name = excluded.first_name
    """, (user_id, username or "", first_name or ""))
    conn.commit()
    conn.close()

def db_get_user(user_id: int) -> dict | None:
    """Foydalanuvchi ma'lumotlarini olish."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT user_id, full_name, age_group, region, is_registered FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "full_name": row[1],
        "age_group": row[2],
        "region": row[3],
        "is_registered": row[4],
    }

def db_complete_registration(user_id: int, full_name: str, age_group: str, region: str):
    """Ro'yxatdan o'tishni yakunlash."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        UPDATE users SET full_name=?, age_group=?, region=?, is_registered=1
        WHERE user_id=?
    """, (full_name, age_group, region, user_id))
    conn.commit()
    conn.close()

def db_log_event(user_id: int, event_type: str,
                 symptom_text: str = None,
                 specialty: str = None,
                 doctor_id: int = None):
    """Har qanday muhim voqeani analytics jadvaliga yozish."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT INTO analytics (user_id, symptom_text, specialty, doctor_id, event_type)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, symptom_text, specialty, doctor_id, event_type))
    conn.commit()
    conn.close()

def db_get_stats() -> dict:
    """Pitch uchun asosiy statistikalar."""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Jami foydalanuvchilar
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Bugungi yangi foydalanuvchilar
    today_users = c.execute("""
        SELECT COUNT(*) FROM users
        WHERE DATE(joined_at) = DATE('now')
    """).fetchone()[0]

    # Jami so'rovlar (AI suhbat)
    total_queries = c.execute("""
        SELECT COUNT(*) FROM analytics WHERE event_type = 'ai_recommendation'
    """).fetchone()[0]

    # Bu haftadagi so'rovlar
    week_queries = c.execute("""
        SELECT COUNT(*) FROM analytics
        WHERE event_type = 'ai_recommendation'
        AND created_at >= DATE('now', '-7 days')
    """).fetchone()[0]

    # Eng ko'p tavsiya qilingan 5 ta mutaxassis
    top_specialties = c.execute("""
        SELECT specialty, COUNT(*) as cnt
        FROM analytics
        WHERE event_type = 'ai_recommendation' AND specialty IS NOT NULL
        GROUP BY specialty
        ORDER BY cnt DESC
        LIMIT 5
    """).fetchall()

    # Eng ko'p tanlangan 5 ta shifokor
    top_doctors = c.execute("""
        SELECT d.name, d.specialty, COUNT(*) as cnt
        FROM analytics a
        JOIN doctors d ON a.doctor_id = d.id
        WHERE a.event_type = 'doctor_viewed'
        GROUP BY a.doctor_id
        ORDER BY cnt DESC
        LIMIT 5
    """).fetchall()

    # Kunlik so'rovlar (oxirgi 7 kun)
    daily_stats = c.execute("""
        SELECT DATE(created_at) as day, COUNT(*) as cnt
        FROM analytics
        WHERE event_type = 'ai_recommendation'
        AND created_at >= DATE('now', '-7 days')
        GROUP BY day
        ORDER BY day
    """).fetchall()

    # Viloyatlar bo'yicha taqsimot
    region_stats = c.execute("""
        SELECT region, COUNT(*) as cnt
        FROM users
        WHERE region IS NOT NULL AND is_registered=1
        GROUP BY region
        ORDER BY cnt DESC
        LIMIT 5
    """).fetchall()

    # Yosh guruhlari bo'yicha taqsimot
    age_stats = c.execute("""
        SELECT age_group, COUNT(*) as cnt
        FROM users
        WHERE age_group IS NOT NULL AND is_registered=1
        GROUP BY age_group
        ORDER BY cnt DESC
    """).fetchall()

    # Ro'yxatdan o'tganlar soni
    registered = c.execute(
        "SELECT COUNT(*) FROM users WHERE is_registered=1"
    ).fetchone()[0]

    conn.close()
    return {
        "total_users": total_users,
        "today_users": today_users,
        "total_queries": total_queries,
        "week_queries": week_queries,
        "top_specialties": top_specialties,
        "top_doctors": top_doctors,
        "daily_stats": daily_stats,
        "region_stats": region_stats,
        "age_stats": age_stats,
        "registered": registered,
    }

# ===================== AI =====================
async def ask_chatgpt(history: list[dict], user_id: int = None) -> str:
    doctors    = db_all_doctors()
    specs      = ", ".join(set(d[2] for d in doctors))

    # Foydalanuvchi profili AI ga uzatiladi
    user_profile = ""
    if user_id:
        u = db_get_user(user_id)
        if u and u["is_registered"]:
            user_profile = (
                f"\nFoydalanuvchi ma'lumotlari:\n"
                f"- Ism: {u['full_name']}\n"
                f"- Yosh guruhi: {u['age_group']}\n"
                f"- Viloyat: {u['region']}\n"
                "Bu ma'lumotlarni tavsiyada hisobga ol.\n"
            )

    system_msg = {
        "role": "system",
        "content": (
            "Sen tibbiy yordamchi botsan. Vazifang:\n"
            "1. Foydalanuvchidan simptomlar haqida 2-3 savol so'ra.\n"
            "2. Yetarli ma'lumot to'plangach qaysi mutaxassis kerakligini aniqlash.\n"
            f"Mavjud mutaxassislar: {specs}\n"
            f"{user_profile}\n"
            "QOIDALAR:\n"
            "- Faqat o'zbek tilida gapir.\n"
            "- Foydalanuvchi yoshini hisobga olib tavsiya ber (bola, katta, keksa uchun farqli).\n"
            "- Tibbiy tashxis QO'YMA — faqat qaysi doktorga borish kerakligini ayt.\n"
            "- Jiddiy simptom (nafas qiyinligi, ko'krak og'rig'i) bo'lsa DARHOL tez yordam chaqirishni ayt.\n"
            "- Tavsiya berish uchun yetarli ma'lumot to'plangach javob oxiriga "
            "aynan shu qatorni qo'sh:\nTAVSIYA: <mutaxassis nomi>\n"
            "Misol: TAVSIYA: Kardiolog"
        )
    }
    messages = [system_msg] + history
    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=1000,
    )
    return resp.choices[0].message.content

def extract_specialty(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip().startswith("TAVSIYA:"):
            return line.replace("TAVSIYA:", "").strip()
    return None

def clean_ai_text(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("TAVSIYA:")).strip()

# ===================== KEYBOARDS =====================
def main_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🩺 AI bilan suhbat",       callback_data="start_ai")],
        [InlineKeyboardButton(text="👨‍⚕️ Barcha doktorlar",   callback_data="all_doctors")],
        [InlineKeyboardButton(text="🔍 Mutaxassislik bo'yicha", callback_data="by_spec")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(to: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")]
    ])

def stop_ai_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Suhbatni tugatish", callback_data="stop_ai")]
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

    # Foydalanuvchini bazaga qo'shish (yangi bo'lsa)
    db_upsert_user(
        user_id=msg.from_user.id,
        username=msg.from_user.username,
        first_name=msg.from_user.first_name
    )
    db_log_event(user_id=msg.from_user.id, event_type="start")

    # Ro'yxatdan o'tganmi tekshiramiz
    user = db_get_user(msg.from_user.id)
    if user and user["is_registered"]:
        # Avval ro'yxatdan o'tgan — to'g'ri menyuga
        await msg.answer(
            f"👋 Xush kelibsiz, *{user['full_name']}*!\n\n"
            "Quyidan bo'limni tanlang:",
            reply_markup=main_kb(msg.from_user.id),
            parse_mode="Markdown"
        )
    else:
        # Yangi foydalanuvchi — ro'yxatdan o'tkazish
        await state.set_state(UserReg.full_name)
        await msg.answer(
            "👋 *Shifo Yordamchi Botga Xush Kelibsiz!*\n\n"
            "Bu bot orqali:\n"
            "• 🤖 AI yordamida simptomlaringizni tahlil qilasiz\n"
            "• 👨‍⚕️ Kerakli mutaxassisni topasiz\n"
            "• 📞 Doktor bilan bog'lanasiz\n\n"
            "Boshlash uchun bir necha savol:\n\n"
            "👤 *Ismingizni kiriting:*",
            parse_mode="Markdown"
        )

# --- Ro'yxatdan o'tish: Ism ---
@dp.message(UserReg.full_name)
async def reg_full_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2:
        await msg.answer("⚠️ Iltimos, to'liq ismingizni kiriting:")
        return
    await state.update_data(full_name=name)
    await state.set_state(UserReg.age)

    rows = [
        [InlineKeyboardButton(text="👶 18 yoshgacha",  callback_data="age_under18")],
        [InlineKeyboardButton(text="🧑 18–35 yosh",    callback_data="age_18_35")],
        [InlineKeyboardButton(text="🧔 36–55 yosh",    callback_data="age_36_55")],
        [InlineKeyboardButton(text="👴 56 yoshdan yuqori", callback_data="age_over56")],
    ]
    await msg.answer(
        f"✅ Salom, *{name}*!\n\n📅 *Yosh guruhingizni tanlang:*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

# --- Ro'yxatdan o'tish: Yosh ---
AGE_LABELS = {
    "age_under18": "18 yoshgacha",
    "age_18_35":   "18–35 yosh",
    "age_36_55":   "36–55 yosh",
    "age_over56":  "56 yoshdan yuqori",
}

@dp.callback_query(F.data.startswith("age_"), UserReg.age)
async def reg_age(cq: CallbackQuery, state: FSMContext):
    age_group = AGE_LABELS.get(cq.data, cq.data)
    await state.update_data(age_group=age_group)
    await state.set_state(UserReg.region)

    rows = [
        [InlineKeyboardButton(text="🏙 Toshkent shahri",   callback_data="reg_Toshkent shahri")],
        [InlineKeyboardButton(text="🌆 Toshkent viloyati", callback_data="reg_Toshkent viloyati")],
        [InlineKeyboardButton(text="🌿 Xorazm",            callback_data="reg_Xorazm")],
        [InlineKeyboardButton(text="🏔 Samarqand",         callback_data="reg_Samarqand")],
        [InlineKeyboardButton(text="🌅 Farg'ona",          callback_data="reg_Farg'ona")],
        [InlineKeyboardButton(text="🌾 Qashqadaryo",       callback_data="reg_Qashqadaryo")],
        [InlineKeyboardButton(text="🏜 Buxoro",            callback_data="reg_Buxoro")],
        [InlineKeyboardButton(text="🌊 Namangan",          callback_data="reg_Namangan")],
        [InlineKeyboardButton(text="🗺 Boshqa viloyat",    callback_data="reg_Boshqa")],
    ]
    await cq.message.edit_text(
        f"✅ *{age_group}* — saqlandi!\n\n📍 *Qaysi viloyatdasiz?*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await cq.answer()

# --- Ro'yxatdan o'tish: Viloyat → Yakunlash ---
@dp.callback_query(F.data.startswith("reg_"), UserReg.region)
async def reg_region(cq: CallbackQuery, state: FSMContext):
    region = cq.data.removeprefix("reg_")
    data   = await state.get_data()

    # Bazaga saqlash
    db_complete_registration(
        user_id=cq.from_user.id,
        full_name=data["full_name"],
        age_group=data["age_group"],
        region=region
    )
    db_log_event(user_id=cq.from_user.id, event_type="registered")
    await state.clear()

    await cq.message.edit_text(
        f"🎉 *Ro'yxatdan o'tish muvaffaqiyatli yakunlandi!*\n\n"
        f"👤 Ism: *{data['full_name']}*\n"
        f"📅 Yosh: *{data['age_group']}*\n"
        f"📍 Viloyat: *{region}*\n\n"
        "Endi AI shifokor sizga aniqroq tavsiya bera oladi.\n\n"
        "Quyidan bo'limni tanlang:",
        reply_markup=main_kb(cq.from_user.id),
        parse_mode="Markdown"
    )
    await cq.answer()

# ===================== CALLBACK: bosh sahifa =====================
@dp.callback_query(F.data == "main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cq,
        "👋 *Shifo Yordamchi Bot*\n\nQuyidan bo'limni tanlang:",
        reply_markup=main_kb(cq.from_user.id),
    )
    await cq.answer()

# ===================== AI CHAT =====================
@dp.callback_query(F.data == "start_ai")
async def cb_start_ai(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AiChat.chatting)
    await state.update_data(history=[])

    # ✅ ANALYTICS: AI suhbat boshlandi
    db_log_event(user_id=cq.from_user.id, event_type="ai_chat_started")

    await cq.message.edit_text(
        "🩺 *AI suhbat boshlandi!*\n\n"
        "Qayeringiz og'riyapti yoki qanday noqulaylik sezmoqdasiz? "
        "Iloji boricha batafsil yozing.",
        reply_markup=stop_ai_kb(),
        parse_mode="Markdown"
    )
    await cq.answer()

@dp.callback_query(F.data == "stop_ai")
async def cb_stop_ai(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "👋 *Shifo Yordamchi Bot*\n\nQuyidan bo'limni tanlang:",
        reply_markup=main_kb(cq.from_user.id),
        parse_mode="Markdown"
    )
    await cq.answer()

@dp.message(AiChat.chatting)
async def ai_chat_msg(msg: Message, state: FSMContext):
    data    = await state.get_data()
    history = data.get("history", [])
    history.append({"role": "user", "content": msg.text})

    wait = await msg.answer("🔍 Tahlil qilinmoqda...")
    try:
        ai_text  = await ask_chatgpt(history, user_id=msg.from_user.id)
        history.append({"role": "assistant", "content": ai_text})
        await state.update_data(history=history)

        specialty = extract_specialty(ai_text)
        display   = clean_ai_text(ai_text)

        await wait.delete()

        if specialty:
            # ✅ ANALYTICS: AI tavsiya berdi — simptom va mutaxassisni saqlash
            db_log_event(
                user_id=msg.from_user.id,
                event_type="ai_recommendation",
                symptom_text=history[0]["content"][:300] if history else None,
                specialty=specialty
            )

            doctors = db_doctors_by_spec(specialty)
            rows    = []
            if doctors:
                body = f"{display}\n\n✅ *Tavsiya: {specialty}*\n\nBizda quyidagi {specialty}lar mavjud:"
                for d in doctors:
                    rows.append([InlineKeyboardButton(text=f"👨‍⚕️ {d[1]}", callback_data=f"doc_{d[0]}")])
            else:
                body = f"{display}\n\n✅ *Tavsiya: {specialty}*\n\n⚠️ Hozirda bu mutaxassisimiz mavjud emas."

            rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")])
            await msg.answer(body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")
            await state.clear()
        else:
            await msg.answer(display, reply_markup=stop_ai_kb(), parse_mode="Markdown")

    except Exception as e:
        await wait.delete()
        await msg.answer(f"⚠️ Xatolik: {e}\n\n/start bosing.")
        await state.clear()

# ===================== DOKTORLAR =====================
@dp.callback_query(F.data == "all_doctors")
async def cb_all_doctors(cq: CallbackQuery):
    # ✅ ANALYTICS: doktorlar sahifasi ochildi
    db_log_event(user_id=cq.from_user.id, event_type="doctors_viewed")

    doctors = db_all_doctors()
    if not doctors:
        await cq.message.edit_text("😔 Hozirda doktorlar mavjud emas.", reply_markup=back_kb())
        return

    specs = {}
    for d in doctors:
        specs.setdefault(d[2], []).append(d)

    rows = [
        [InlineKeyboardButton(text=f"📋 {s} ({len(docs)} ta)", callback_data=f"spec_{s}")]
        for s, docs in specs.items()
    ]
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")])
    await safe_edit(cq,
        f"👨‍⚕️ *Bizning doktorlarimiz*\n\nJami: {len(doctors)} ta mutaxassis\n\nMutaxassislikni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cq.answer()

@dp.callback_query(F.data == "by_spec")
async def cb_by_spec(cq: CallbackQuery):
    doctors = db_all_doctors()
    specs   = sorted(set(d[2] for d in doctors))
    rows    = [[InlineKeyboardButton(text=f"🔬 {s}", callback_data=f"spec_{s}")] for s in specs]
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")])
    await safe_edit(cq, "🔍 *Mutaxassislik tanlang:*", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.callback_query(F.data.startswith("spec_"))
async def cb_spec(cq: CallbackQuery):
    spec    = cq.data.removeprefix("spec_")
    doctors = db_doctors_by_spec(spec)
    rows    = [[InlineKeyboardButton(text=f"👨‍⚕️ {d[1]}", callback_data=f"doc_{d[0]}")] for d in doctors]
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="all_doctors")])
    await safe_edit(cq,
        f"👨‍⚕️ *{spec}lar:*\n\nBiror doktorni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("doc_"))
async def cb_doc(cq: CallbackQuery):
    doc_id = int(cq.data.removeprefix("doc_"))
    d      = db_doctor_by_id(doc_id)
    if not d:
        await cq.answer("Doktor topilmadi!", show_alert=True)
        return

    # ✅ ANALYTICS: qaysi shifokor ko'rildi
    db_log_event(
        user_id=cq.from_user.id,
        event_type="doctor_viewed",
        specialty=d[2],
        doctor_id=d[0]
    )

    no_info  = d[4] or "Ma'lumot yo'q"
    photo_id = d[5] if len(d) > 5 else None
    text = (
        f"👨‍⚕️ *{d[1]}*\n\n"
        f"🔬 Mutaxassislik: {d[2]}\n"
        f"📞 Telefon: {d[3]}\n\n"
        f"ℹ️ {no_info}"
    )
    rows = [
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"spec_{d[2]}")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    if photo_id:
        try:
            await cq.message.delete()
        except Exception:
            pass
        await cq.message.answer_photo(
            photo=photo_id,
            caption=text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
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
        [InlineKeyboardButton(text="📊 Statistika",                    callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Yangi doktor qo'shish",         callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Doktorni tahrirlash",           callback_data="admin_edit_list")],
        [InlineKeyboardButton(text="📋 Doktorlar ro'yxati (o'chirish)", callback_data="admin_list")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa",                   callback_data="main")],
    ]
    await safe_edit(cq,
        "⚙️ *Admin Panel*\n\nNimani qilmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cq.answer()

# ===================== ADMIN: STATISTIKA (YANGI) =====================
@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    stats = db_get_stats()

    # Eng ko'p so'raladigan mutaxassislar
    spec_lines = ""
    for i, (spec, cnt) in enumerate(stats["top_specialties"], 1):
        bar = "█" * min(cnt, 10)
        spec_lines += f"  {i}. {spec}: {cnt} ta {bar}\n"
    if not spec_lines:
        spec_lines = "  Hali ma'lumot yo'q\n"

    # Eng ko'p ko'rilgan shifokorlar
    doc_lines = ""
    for i, (name, spec, cnt) in enumerate(stats["top_doctors"], 1):
        doc_lines += f"  {i}. {name} ({spec}): {cnt} marta\n"
    if not doc_lines:
        doc_lines = "  Hali ma'lumot yo'q\n"

    # Kunlik statistika
    daily_lines = ""
    for day, cnt in stats["daily_stats"]:
        bar = "▓" * min(cnt, 15)
        daily_lines += f"  {day}: {cnt} ta {bar}\n"
    if not daily_lines:
        daily_lines = "  Hali ma'lumot yo'q\n"

    # Viloyatlar
    region_lines = ""
    for reg, cnt in stats["region_stats"]:
        bar = "█" * min(cnt, 10)
        region_lines += f"  • {reg}: {cnt} ta {bar}\n"
    if not region_lines:
        region_lines = "  Hali ma'lumot yo'q\n"

    # Yosh guruhlari
    age_lines = ""
    for age, cnt in stats["age_stats"]:
        age_lines += f"  • {age}: {cnt} ta\n"
    if not age_lines:
        age_lines = "  Hali ma'lumot yo'q\n"

    text = (
        f"📊 *Shifo Yordamchi — Statistika*\n"
        f"_{datetime.now().strftime('%d.%m.%Y %H:%M')}_\n\n"
        f"👥 *Foydalanuvchilar:*\n"
        f"  • Jami kirganlar: *{stats['total_users']} ta*\n"
        f"  • Ro'yxatdan o'tganlar: *{stats['registered']} ta*\n"
        f"  • Bugun yangi: *{stats['today_users']} ta*\n\n"
        f"🩺 *AI So'rovlar:*\n"
        f"  • Jami: *{stats['total_queries']} ta*\n"
        f"  • Bu hafta: *{stats['week_queries']} ta*\n\n"
        f"📍 *Viloyatlar bo'yicha:*\n"
        f"{region_lines}\n"
        f"📅 *Yosh guruhlari:*\n"
        f"{age_lines}\n"
        f"🔬 *Eng ko'p so'raladigan mutaxassislar:*\n"
        f"{spec_lines}\n"
        f"👨‍⚕️ *Eng ko'p ko'rilgan shifokorlar:*\n"
        f"{doc_lines}\n"
        f"📈 *Kunlik so'rovlar (7 kun):*\n"
        f"{daily_lines}"
    )

    rows = [[InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")]]
    await safe_edit(cq, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

# ===================== ADMIN: RO'YXAT VA O'CHIRISH =====================
@dp.callback_query(F.data == "admin_edit_list")
async def cb_admin_edit_list(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doctors = db_all_doctors()
    if not doctors:
        await cq.message.edit_text("😔 Doktorlar mavjud emas.", reply_markup=back_kb())
        return
    rows = [
        [InlineKeyboardButton(text=f"✏️ {d[1]} ({d[2]})", callback_data=f"aedit_{d[0]}")]
        for d in doctors
    ]
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")])
    await safe_edit(cq,
        "✏️ *Tahrirlash uchun doktorni tanlang:*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
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
        [InlineKeyboardButton(text=f"ℹ️ Tavsif",               callback_data="ef_desc")],
        [InlineKeyboardButton(text=f"📸 Rasm: {has_photo}",     callback_data="ef_photo")],
        [InlineKeyboardButton(text="◀️ Orqaga",                 callback_data="admin_edit_list")],
    ]
    await safe_edit(cq,
        f"✏️ *{d[1]}* — qaysi maydonni o'zgartirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cq.answer()

@dp.callback_query(F.data == "admin_list")
async def cb_admin_list(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doctors = db_all_doctors()
    if not doctors:
        await cq.message.edit_text("😔 Doktorlar mavjud emas.", reply_markup=back_kb("admin"))
        return
    rows = [
        [InlineKeyboardButton(text=f"🗑 {d[1]} ({d[2]})", callback_data=f"adel_{d[0]}")]
        for d in doctors
    ]
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin")])
    await safe_edit(cq,
        "🗑 *O'chirish uchun doktorni tanlang:*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("adel_"))
async def cb_admin_del(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    doc_id = int(cq.data.removeprefix("adel_"))
    db_delete_doctor(doc_id)
    await cq.answer("✅ Doktor o'chirildi!", show_alert=True)
    rows = [
        [InlineKeyboardButton(text="📊 Statistika",                    callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Yangi doktor qo'shish",         callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Doktorni tahrirlash",           callback_data="admin_edit_list")],
        [InlineKeyboardButton(text="📋 Doktorlar ro'yxati (o'chirish)", callback_data="admin_list")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa",                   callback_data="main")],
    ]
    await safe_edit(cq,
        "⚙️ *Admin Panel*\n\nNimani qilmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )

# ===================== DOKTOR QO'SHISH FSM =====================
@dp.callback_query(F.data == "admin_add")
async def cb_admin_add(cq: CallbackQuery, state: FSMContext):
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    await state.set_state(AdminAdd.name)
    await cq.message.edit_text(
        "👨‍⚕️ *Yangi doktor qo'shish*\n\nDoktorning to'liq ismini kiriting:\n_(Masalan: Dr. Alisher Karimov)_",
        parse_mode="Markdown"
    )
    await cq.answer()

@dp.message(AdminAdd.name)
async def adm_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await state.set_state(AdminAdd.spec)
    await msg.answer("✅ Ism saqlandi!\n\nMutaxassisligini kiriting:\n_(Masalan: Kardiolog)_", parse_mode="Markdown")

@dp.message(AdminAdd.spec)
async def adm_spec(msg: Message, state: FSMContext):
    await state.update_data(spec=msg.text)
    await state.set_state(AdminAdd.phone)
    await msg.answer("✅ Mutaxassislik saqlandi!\n\nTelefon raqamini kiriting:\n_(Masalan: +998901234567)_", parse_mode="Markdown")

@dp.message(AdminAdd.phone)
async def adm_phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(AdminAdd.desc)
    await msg.answer("✅ Telefon saqlandi!\n\nQisqacha tavsif kiriting:", parse_mode="Markdown")

@dp.message(AdminAdd.desc)
async def adm_desc(msg: Message, state: FSMContext):
    await state.update_data(desc=msg.text)
    await state.set_state(AdminAdd.photo)
    rows = [[InlineKeyboardButton(text="⏭ Rasmsiz qo'shish", callback_data="admin_skip_photo")]]
    await msg.answer(
        "✅ Tavsif saqlandi!\n\n📸 *Doktor rasmini yuboring:*\n_(Rasm bo'lmasa — quyidagi tugmani bosing)_",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

@dp.message(AdminAdd.photo, F.photo)
async def adm_photo(msg: Message, state: FSMContext):
    data     = await state.get_data()
    photo_id = msg.photo[-1].file_id
    db_add_doctor(data["name"], data["spec"], data["phone"], data["desc"], photo_id)
    await state.clear()
    rows = [[InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin")]]
    await msg.answer_photo(
        photo=photo_id,
        caption=(
            f"✅ *Doktor muvaffaqiyatli qo'shildi!*\n\n"
            f"👨‍⚕️ {data['name']}\n"
            f"🔬 {data['spec']}\n"
            f"📞 {data['phone']}\n"
            f"ℹ️ {data['desc']}"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "admin_skip_photo", AdminAdd.photo)
async def adm_skip_photo(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db_add_doctor(data["name"], data["spec"], data["phone"], data["desc"], None)
    await state.clear()
    rows = [[InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin")]]
    await cq.message.edit_text(
        f"✅ *Doktor muvaffaqiyatli qo'shildi!*\n\n"
        f"👨‍⚕️ {data['name']}\n"
        f"🔬 {data['spec']}\n"
        f"📞 {data['phone']}\n"
        f"ℹ️ {data['desc']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await cq.answer()

# ===================== DOKTOR TAHRIRLASH =====================
FIELD_LABELS = {
    "ef_name":  ("name",        "👤 Yangi ismni kiriting:"),
    "ef_spec":  ("specialty",   "🔬 Yangi mutaxassislikni kiriting:"),
    "ef_phone": ("phone",       "📞 Yangi telefon raqamini kiriting:"),
    "ef_desc":  ("description", "ℹ️ Yangi tavsifni kiriting:"),
}

@dp.callback_query(F.data.in_({"ef_name", "ef_spec", "ef_phone", "ef_desc"}), AdminEdit.choose_field)
async def cb_edit_text_field(cq: CallbackQuery, state: FSMContext):
    field_key, prompt = FIELD_LABELS[cq.data]
    await state.update_data(edit_field=field_key)
    await state.set_state(AdminEdit.new_value)
    rows = [[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_edit_list")]]
    await safe_edit(cq, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()

@dp.message(AdminEdit.new_value)
async def cb_edit_save_value(msg: Message, state: FSMContext):
    data = await state.get_data()
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
        f"✅ *Muvaffaqiyatli saqlandi!*\n\n"
        f"👤 {d[1]}\n🔬 {d[2]}\n📞 {d[3]}\nℹ️ {d[4] or 'Yo`q'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "ef_photo", AdminEdit.choose_field)
async def cb_edit_photo_field(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminEdit.new_photo)
    rows = [
        [InlineKeyboardButton(text="🗑 Rasmni o'chirish", callback_data="edit_remove_photo")],
        [InlineKeyboardButton(text="❌ Bekor qilish",     callback_data="admin_edit_list")],
    ]
    await safe_edit(cq,
        "📸 *Yangi rasmni yuboring:*\n_(yoki rasmni o'chirish uchun tugmani bosing)_",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
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
    await msg.answer_photo(
        photo=photo_id,
        caption="✅ *Rasm muvaffaqiyatli yangilandi!*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )

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

# ===================== MAIN =====================
async def main():
    init_db()
    print("✅ Database tayyor (users + analytics jadvallar qo'shildi)")
    print("🤖 Shifo Yordamchi Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())