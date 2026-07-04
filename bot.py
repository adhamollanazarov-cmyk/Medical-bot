import os
import sqlite3
import asyncio
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
    # Eski bazaga photo_id ustuni qo'shish (agar yo'q bo'lsa)
    try:
        c.execute("ALTER TABLE doctors ADD COLUMN photo_id TEXT")
    except Exception:
        pass
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

# ===================== AI =====================
async def ask_chatgpt(history: list[dict]) -> str:
    doctors    = db_all_doctors()
    specs      = ", ".join(set(d[2] for d in doctors))
    system_msg = {
        "role": "system",
        "content": (
            "Sen tibbiy yordamchi botsan. Vazifang:\n"
            "1. Foydalanuvchidan simptomlar haqida 2-3 savol so'ra.\n"
            "2. Yetarli ma'lumot to'plangach qaysi mutaxassis kerakligini aniqlash.\n"
            f"Mavjud mutaxassislar: {specs}\n\n"
            "QOIDALAR:\n"
            "- Faqat o'zbek tilida gapir.\n"
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
    """Rasmli xabarda edit_text ishlamaydi — o'chirib yangi xabar yuboramiz."""
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
    await msg.answer(
        "👋 *Tibbiy Yordamchi Botga Xush Kelibsiz!*\n\n"
        "Bu bot orqali:\n"
        "• 🤖 AI yordamida simptomlaringizni tahlil qilishingiz\n"
        "• 👨‍⚕️ Kerakli mutaxassisni topishingiz\n"
        "• 📞 Doktor bilan bog'lanishingiz mumkin\n\n"
        "Quyidan bo'limni tanlang:",
        reply_markup=main_kb(msg.from_user.id),
        parse_mode="Markdown"
    )

# ===================== CALLBACK: bosh sahifa =====================
@dp.callback_query(F.data == "main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cq,
        "👋 *Tibbiy Yordamchi Bot*\n\nQuyidan bo'limni tanlang:",
        reply_markup=main_kb(cq.from_user.id),
    )
    await cq.answer()

# ===================== AI CHAT =====================
@dp.callback_query(F.data == "start_ai")
async def cb_start_ai(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AiChat.chatting)
    await state.update_data(history=[])
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
        "👋 *Tibbiy Yordamchi Bot*\n\nQuyidan bo'limni tanlang:",
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
        ai_text  = await ask_chatgpt(history)
        history.append({"role": "assistant", "content": ai_text})
        await state.update_data(history=history)

        specialty = extract_specialty(ai_text)
        display   = clean_ai_text(ai_text)

        await wait.delete()

        if specialty:
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

    no_info  = d[4] or "Ma'lumot yo'q"
    photo_id = d[5] if len(d) > 5 else None
    text = (
        f"👨‍⚕️ *{d[1]}*\n\n"
        f"🔬 Mutaxassislik: {d[2]}\n"
        f"📞 Telefon: {d[3]}\n\n"
        f"ℹ️ {no_info}"
    )
    digits = "".join(ch for ch in d[3] if ch.isdigit())
    rows = [
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"spec_{d[2]}")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    if photo_id:
        # Avval o'chirishga harakat qilamiz, bo'lmasa shunchaki yangi xabar yuboramiz
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
    no_info  = d[4] or "Yo'q"
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
        [InlineKeyboardButton(text="➕ Yangi doktor qo'shish",         callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Doktorni tahrirlash",           callback_data="admin_edit_list")],
        [InlineKeyboardButton(text="📋 Doktorlar ro'yxati (o'chirish)", callback_data="admin_list")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa",                   callback_data="main")],
    ]
    await safe_edit(cq,
        "⚙️ *Admin Panel*\n\nNimani qilmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )

# --- Doktor qo'shish FSM ---
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
    photo_id = msg.photo[-1].file_id  # Eng yuqori sifatli rasm
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
    print("✅ Database tayyor")
    print("🤖 Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
