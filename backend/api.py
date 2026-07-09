# api.py — Shifo Yordamchi Mini App uchun backend (FastAPI)
# Bot (bot_pg.py) bilan BIR XIL PostgreSQL bazasidan foydalanadi (Railway).
#
# Ishga tushirish (lokal):
#   pip install -r requirements-api.txt
#   uvicorn api:app --host 0.0.0.0 --port 8000 --reload
#
# Railway'da: bu faylni bot bilan bir loyihada alohida "service" sifatida
# deploy qiling (Start Command: uvicorn api:app --host 0.0.0.0 --port $PORT)

import os
import hmac
import hashlib
import json
from datetime import datetime
from contextlib import contextmanager
from urllib.parse import parse_qsl

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI

# ===================== SOZLAMALAR =====================
DATABASE_URL     = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
ADMIN_IDS        = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "*").split(",")]
# Masalan: FRONTEND_ORIGIN=https://username.github.io

# Development rejimida (TELEGRAM_TOKEN yo'q bo'lsa) initData tekshiruvi
# o'chirilishi mumkin — bu FAQAT lokal test uchun, productionda albatta
# TELEGRAM_BOT_TOKEN o'rnatilgan bo'lishi kerak.
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Shifo Yordamchi API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== DATABASE =====================
@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def dict_rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

# ===================== TELEGRAM initData TEKSHIRUVI =====================
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
def verify_init_data(init_data: str) -> dict:
    """initData ni tekshiradi va foydalanuvchi ma'lumotini qaytaradi.
    Muvaffaqiyatsiz bo'lsa 401 xato beradi."""
    if DEV_MODE and not init_data:
        # faqat lokal test uchun soxta foydalanuvchi
        return {"id": 0, "first_name": "Dev", "username": "dev"}

    if not init_data:
        raise HTTPException(status_code=401, detail="initData yo'q")

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        raise HTTPException(status_code=401, detail="initData formati noto'g'ri")

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="hash topilmadi")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(status_code=401, detail="initData imzosi noto'g'ri")

    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(status_code=401, detail="foydalanuvchi topilmadi")
    return json.loads(user_json)

async def get_current_user(x_telegram_init_data: str = Header(default="")):
    user = verify_init_data(x_telegram_init_data)
    return user

# ===================== PYDANTIC MODELLARI =====================
class ProfileIn(BaseModel):
    full_name: str
    age_group: str
    region: str
    lang: str = "uz"

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatIn(BaseModel):
    history: list[ChatMessage]
    lang: str = "uz"

# ===================== TARJIMALAR (AI system prompt) =====================
# bot_pg.py dagi TEXTS["system_prompt"] bilan bir xil mantiq
SYSTEM_PROMPTS = {
    "uz": (
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
    "ru": (
        "Ты медицинский ассистент-бот. Отвечай ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.\n"
        "1. Задай 2-3 уточняющих вопроса о симптомах.\n"
        "2. Затем укажи, к какому специалисту обратиться.\n"
        "Доступные специалисты: {specs}\n"
        "Пользователь: {profile}\n"
        "ПРАВИЛА:\n"
        "- НЕ ставь диагнозы — только направляй.\n"
        "- При серьёзных симптомах немедленно советуй вызвать скорую.\n"
        "- Когда соберёшь достаточно данных, добавь в конце:\nTAVSIYA: <специалист>\n"
    ),
    "en": (
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
}

def extract_specialty(text: str):
    for line in text.splitlines():
        if line.strip().startswith("TAVSIYA:"):
            return line.replace("TAVSIYA:", "").strip()
    return None

def clean_ai_text(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("TAVSIYA:")).strip()

# ===================== ENDPOINTS =====================
@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

# ---------- Doktorlar ----------
@app.get("/api/doctors")
def get_doctors(specialty: str | None = None, q: str | None = None):
    with get_conn() as conn:
        cur = conn.cursor()
        if specialty:
            cur.execute(
                "SELECT id,name,specialty,phone,description,photo_id FROM doctors "
                "WHERE is_active=1 AND specialty ILIKE %s ORDER BY name",
                (f"%{specialty}%",)
            )
        else:
            cur.execute(
                "SELECT id,name,specialty,phone,description,photo_id FROM doctors "
                "WHERE is_active=1 ORDER BY name"
            )
        rows = cur.fetchall()

    doctors = []
    for r in rows:
        d = {
            "id": r[0], "name": r[1], "specialty": r[2], "phone": r[3],
            "description": r[4],
            # Telegram file_id ni to'g'ridan-to'g'ri <img> uchun ishlatib bo'lmaydi —
            # kerak bo'lsa alohida /api/doctor-photo/{id} endpoint orqali bot API bilan
            # olish mumkin. Hozircha frontend rasm bo'lmasa ikonka ko'rsatadi.
            "photo_url": None,
        }
        if q:
            ql = q.lower()
            if ql not in d["name"].lower() and ql not in d["specialty"].lower():
                continue
        doctors.append(d)
    return {"doctors": doctors}

@app.get("/api/doctors/{doctor_id}")
def get_doctor(doctor_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id,name,specialty,phone,description,photo_id FROM doctors WHERE id=%s",
            (doctor_id,)
        )
        r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Doktor topilmadi")
    return {"id": r[0], "name": r[1], "specialty": r[2], "phone": r[3], "description": r[4], "photo_url": None}

@app.get("/api/specialties")
def get_specialties():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT specialty FROM doctors WHERE is_active=1 ORDER BY specialty")
        rows = cur.fetchall()
    return {"specialties": [r[0] for r in rows]}

# ---------- Profil ----------
@app.get("/api/profile")
def get_profile(user=Depends(get_current_user)):
    user_id = user["id"]
    is_admin = user_id in ADMIN_IDS
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id,full_name,age_group,region,is_registered,lang FROM users WHERE user_id=%s",
            (user_id,)
        )
        row = cur.fetchone()

    if not row or not row[4]:
        return {"registered": False, "is_admin": is_admin}

    return {
        "registered": True,
        "is_admin": is_admin,
        "profile": {
            "full_name": row[1], "age_group": row[2], "region": row[3], "lang": row[5] or "uz",
        }
    }

@app.post("/api/profile")
def set_profile(payload: ProfileIn, user=Depends(get_current_user)):
    user_id = user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        # Foydalanuvchi mavjudligiga ishonch hosil qilamiz (upsert)
        cur.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET last_seen = CURRENT_TIMESTAMP
        """, (user_id, user.get("username", ""), user.get("first_name", "")))
        cur.execute("""
            UPDATE users SET full_name=%s, age_group=%s, region=%s, lang=%s, is_registered=1
            WHERE user_id=%s
        """, (payload.full_name, payload.age_group, payload.region, payload.lang, user_id))
        cur.execute("""
            INSERT INTO analytics (user_id, event_type) VALUES (%s, 'registered_or_updated_webapp')
        """, (user_id,))

    return {
        "registered": True,
        "is_admin": user_id in ADMIN_IDS,
        "profile": payload.dict(),
    }

@app.get("/api/is-admin")
def is_admin(user=Depends(get_current_user)):
    return {"is_admin": user["id"] in ADMIN_IDS}

# ---------- Statistika (faqat admin) ----------
@app.get("/api/stats")
def get_stats(user=Depends(get_current_user)):
    if user["id"] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Faqat administratorlar uchun")

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM users WHERE DATE(joined_at) = CURRENT_DATE")
        today_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = 1")
        registered = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM analytics WHERE event_type = 'ai_recommendation'")
        total_queries = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM analytics
            WHERE event_type = 'ai_recommendation' AND created_at >= NOW() - INTERVAL '7 days'
        """)
        week_queries = cur.fetchone()[0]

        cur.execute("""
            SELECT specialty, COUNT(*) AS cnt FROM analytics
            WHERE event_type = 'ai_recommendation' AND specialty IS NOT NULL
            GROUP BY specialty ORDER BY cnt DESC LIMIT 5
        """)
        top_specialties = [{"specialty": r[0], "count": r[1]} for r in cur.fetchall()]

        cur.execute("""
            SELECT region, COUNT(*) AS cnt FROM users
            WHERE region IS NOT NULL AND is_registered = 1
            GROUP BY region ORDER BY cnt DESC LIMIT 6
        """)
        region_stats = [{"region": r[0], "count": r[1]} for r in cur.fetchall()]

        cur.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt FROM analytics
            WHERE event_type = 'ai_recommendation' AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY day ORDER BY day
        """)
        daily_stats = [{"day": r[0].strftime("%d.%m"), "count": r[1]} for r in cur.fetchall()]

    return {
        "total_users": total_users, "today_users": today_users, "registered": registered,
        "total_queries": total_queries, "week_queries": week_queries,
        "top_specialties": top_specialties, "region_stats": region_stats, "daily_stats": daily_stats,
    }

# ---------- AI Chat ----------
@app.post("/api/chat")
async def chat(payload: ChatIn, user=Depends(get_current_user)):
    user_id = user["id"]
    lang = payload.lang if payload.lang in SYSTEM_PROMPTS else "uz"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT specialty FROM doctors WHERE is_active=1")
        specs = ", ".join(r[0] for r in cur.fetchall())
        cur.execute(
            "SELECT full_name, age_group, region, is_registered FROM users WHERE user_id=%s",
            (user_id,)
        )
        row = cur.fetchone()

    profile = "Noma'lum"
    if row and row[3]:
        profile = f"Ism: {row[0]}, Yosh: {row[1]}, Viloyat: {row[2]}"

    system_content = SYSTEM_PROMPTS[lang].format(specs=specs or "—", profile=profile)
    messages = [{"role": "system", "content": system_content}] + [m.dict() for m in payload.history]

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY sozlanmagan")

    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, max_tokens=1000
    )
    ai_text = resp.choices[0].message.content
    specialty = extract_specialty(ai_text)
    display = clean_ai_text(ai_text)

    doctors = []
    if specialty:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id,name,specialty,phone,description,photo_id FROM doctors "
                "WHERE is_active=1 AND specialty ILIKE %s",
                (f"%{specialty}%",)
            )
            for r in cur.fetchall():
                doctors.append({"id": r[0], "name": r[1], "specialty": r[2], "phone": r[3], "description": r[4], "photo_url": None})
            cur.execute("""
                INSERT INTO analytics (user_id, symptom_text, specialty, event_type)
                VALUES (%s, %s, %s, 'ai_recommendation')
            """, (user_id, (payload.history[0].content[:300] if payload.history else None), specialty))

    return {"reply": display, "reply_raw": ai_text, "specialty": specialty, "doctors": doctors}