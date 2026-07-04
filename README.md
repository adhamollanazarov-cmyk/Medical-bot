# 🏥 Tibbiy Yordamchi Telegram Bot
**Aiogram 3.x + ChatGPT (OpenAI)**

## ✨ Imkoniyatlar
- 🤖 **AI suhbat** — ChatGPT simptomlarni so'rab, mutaxassisni tavsiya qiladi
- 👨‍⚕️ **Doktorlar ro'yxati** — mutaxassislik bo'yicha ko'rish
- 📞 **Bog'lanish** — to'g'ridan-to'g'ri qo'ng'iroq tugmasi
- ⚙️ **Admin panel** — doktor qo'shish va o'chirish

---

## 🚀 Ishga tushirish

### 1. Kutubxonalarni o'rnating
```bash
pip install -r requirements.txt
```

### 2. Tokenlarni oling

| Token | Qayerdan |
|-------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegramda `@BotFather` → `/newbot` |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `ADMIN_IDS` | Telegramda `@userinfobot` → `/start` |

### 3. .env faylini yarating
```bash
cp .env.example .env
# .env faylini oching va tokenlarni kiriting
```

### 4. Botni ishga tushiring
```bash
python bot.py
```

---

## 📁 Fayl tuzilishi
```
medical_bot/
├── bot.py              # Asosiy bot kodi (aiogram 3 + OpenAI)
├── requirements.txt    # Kutubxonalar
├── .env.example        # Sozlamalar namunasi
├── .env                # Sizning sozlamalaringiz (o'zingiz yaratasiz)
└── medical_bot.db      # SQLite DB (avtomatik yaratiladi)
```

---

## 🗃️ Namuna doktorlar (birinchi ishga tushirganda qo'shiladi)
Kardiolog, Nevropatolog, Gastroenterolog, Pulmonolog, Ortoped, Endokrinolog, Terapevt, Ginekolog

---

## ⚙️ Admin panel
`.env` dagi `ADMIN_IDS` ga o'z Telegram ID sini yozing.  
Botda qo'shimcha **"⚙️ Admin panel"** tugmasi paydo bo'ladi.

- **➕ Doktor qo'shish** — ism → mutaxassislik → telefon → tavsif
- **🗑 Doktor o'chirish** — ro'yxatdan olib tashlash
