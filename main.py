import os
import json
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardButton, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

# === ЗАГРУЗКА НАСТРОЕК ===
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

if not WEBHOOK_URL:
    raise ValueError("❌ WEBHOOK_URL не задан в Variables")
if not WEBHOOK_URL.startswith("https://"):
    raise ValueError("❌ WEBHOOK_URL должен начинаться с https://")

# === ПУТИ ===
CHANNELS_FILE = "channels.json"
GALLERY_FILE = "gallery.json"
PDF_DIR = Path("pdfs")
PDF_DIR.mkdir(exist_ok=True)

# === ЗАГРУЗКА ДАННЫХ ===
with open(CHANNELS_FILE, encoding="utf-8") as f:
    CHANNELS = json.load(f)

try:
    with open(GALLERY_FILE, encoding="utf-8") as f:
        GALLERY = json.load(f)
except:
    GALLERY = {}

def save_gallery():
    with open(GALLERY_FILE, "w", encoding="utf-8") as f:
        json.dump(GALLERY, f, ensure_ascii=False, indent=2)

# === ПОИСК ===
STOP_WORDS = {"телеканал", "тв", "канал", "смотреть", "хочу", "найти", "покажи", "дать", "мне"}

def normalize(text: str) -> list[str]:
    text = text.lower()
    text = text.replace("а", "a").replace("х", "x").replace("е", "e").replace("о", "o")
    words = [w for w in text.split() if w.isalnum()]
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]

def search_channels(query: str) -> list[str]:
    q_words = normalize(query)
    matches = []
    for key, data in CHANNELS.items():
        all_words = set()
        for alias in data["aliases"]:
            all_words.update(normalize(alias))
        if q_words and all_words and set(q_words) & all_words:
            matches.append(key)
    return matches

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
async def send_pdf(bot, chat_id: int, user_id: str):
    selected = GALLERY.get(user_id, {}).get("selected", [])
    if not selected:
        await bot.send_message(chat_id, "📭 Подборка пуста. Найди канал → нажми «➕ Добавить».")
        return

    selected = [k for k in selected if k in CHANNELS][:10]
    pdf_path = PDF_DIR / f"{user_id}_tv_logos.pdf"

    try:
        c = canvas.Canvas(str(pdf_path), pagesize=A4)
        width, height = A4
        rows, cols = 2, 5
        cell_w = width / cols
        cell_h = height / rows

        for i, key in enumerate(selected):
            logo_path = CHANNELS[key]["logos"][0]
            if not Path(logo_path).exists():
                continue
            img = ImageReader(logo_path)
            img_w, img_h = img.getSize()
            scale = min((cell_w * 0.8) / img_w, (cell_h * 0.75) / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            col = i % cols
            row = i // cols
            x = col * cell_w + (cell_w - draw_w) / 2
            y = height - (row + 1) * cell_h + (cell_h - draw_h) / 2
            c.drawImage(logo_path, x, y, draw_w, draw_h, preserveAspectRatio=True)

        c.save()

        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(pdf_path),
            caption=f"🖨️ А4 (2×5): {len(selected)} логотипов"
        )

    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка PDF: {e}")

async def show_clear_confirmation(bot, chat_id: int, user_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, очистить", callback_data=f"clear_confirm:{user_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data="clear_cancel")
    )
    await bot.send_message(
        chat_id,
        "⚠️ Подборка заполнена (10/10). Очистить, чтобы добавить новый?",
        reply_markup=builder.as_markup()
    )

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

@router.message(Command("start"))
async def start(m: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🖨️ Моя подборка", callback_data="show_pdf_now")
    builder.button(text="🧹 Очистить подборку", callback_data="clear_now")
    builder.adjust(1)
    await m.answer(
        "📺 Просто напиши: *дождь*, *тнт4*, *матчпремьер*, *«телеканал звезда»* — и выбери действие!\n\n"
        "Управление подборкой:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@router.message(Command("pdf"))
async def cmd_pdf(m: Message):
    await send_pdf(bot, m.chat.id, str(m.from_user.id))

@router.message()
async def search(m: Message):
    query = m.text.strip()
    matches = search_channels(query)

    if not matches:
        await m.answer("❓ Не найдено. Попробуй: *дождь*, *тнт*, *матчпремьер*, *2х2*.", parse_mode="Markdown")
        return

    if len(matches) == 1:
        key = matches[0]
        data = CHANNELS[key]
        logo_path = data["logos"][0]
        if not Path(logo_path).exists():
            await m.answer(f"⚠️ Логотип отсутствует: {logo_path}")
            return

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="➕ Добавить в PDF", callback_data=f"add:{key}"),
            InlineKeyboardButton(text="🖨️ Показать PDF", callback_data="show_pdf")
        )
        await m.answer_photo(
            FSInputFile(logo_path),
            caption=f"✅ {data['name']}",
            reply_markup=builder.as_markup()
        )
        return

    builder = InlineKeyboardBuilder()
    for key in matches[:10]:
        name = CHANNELS[key]["name"]
        builder.add(InlineKeyboardButton(text=name, callback_data=f"select:{key}"))
    builder.adjust(1)
    await m.answer("Найдено несколько вариантов. Выбери:", reply_markup=builder.as_markup())

# === CALLBACK-ОБРАБОТЧИКИ ===

@router.callback_query(lambda c: c.data.startswith("select:"))
async def select_channel(callback, bot):
    key = callback.data.split(":", 1)[1]
    if key not in CHANNELS:
        await callback.answer("❌ Ошибка", show_alert=True)
        return

    data = CHANNELS[key]
    logo_path = data["logos"][0]
    if not Path(logo_path).exists():
        await callback.message.answer(f"⚠️ Логотип отсутствует: {logo_path}")
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить в PDF", callback_data=f"add:{key}"),
        InlineKeyboardButton(text="🖨️ Показать PDF", callback_data="show_pdf")
    )
    await bot.send_photo(
        chat_id=callback.message.chat.id,
        photo=FSInputFile(logo_path),
        caption=f"✅ {data['name']}",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("add:"))
async def add_to_gallery(callback, bot):
    user_id = str(callback.from_user.id)
    key = callback.data.split(":", 1)[1]

    if user_id not in GALLERY:
        GALLERY[user_id] = {"selected": []}

    selected = GALLERY[user_id]["selected"]

    if len(selected) >= 10:
        await callback.answer()
        await show_clear_confirmation(bot, callback.message.chat.id, user_id)
        return

    if key not in selected:
        selected.append(key)
        save_gallery()
        name = CHANNELS[key]["name"]
        count = len(selected)

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="➕ Добавить ещё", callback_data=f"add:{key}"),
            InlineKeyboardButton(text="🖨️ Показать PDF", callback_data="show_pdf")
        )
        if count == 10:
            builder.row(InlineKeyboardButton(text="🧹 Очистить подборку", callback_data="clear_now"))

        await callback.message.edit_caption(
            caption=f"✅ *{name}* добавлен ({count}/10)",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        await callback.answer("ℹ️ Уже добавлен", show_alert=True)

@router.callback_query(lambda c: c.data == "show_pdf")
async def show_pdf(callback, bot):
    await callback.answer()
    await send_pdf(bot, callback.message.chat.id, str(callback.from_user.id))

@router.callback_query(lambda c: c.data == "show_pdf_now")
async def show_pdf_now(callback, bot):
    await callback.answer()
    await send_pdf(bot, callback.message.chat.id, str(callback.from_user.id))

@router.callback_query(lambda c: c.data == "clear_now")
async def clear_now(callback, bot):
    await callback.answer()
    user_id = str(callback.from_user.id)

    if user_id in GALLERY:
        count = len(GALLERY[user_id]["selected"])
        GALLERY[user_id]["selected"] = []
        save_gallery()
        await callback.message.answer(f"🧹 Подборка очищена ({count} логотипов удалено).")
    else:
        await callback.message.answer("📭 Подборка и так пуста.")

@router.callback_query(lambda c: c.data.startswith("clear_confirm:"))
async def clear_confirm(callback, bot):
    user_id = callback.data.split(":", 1)[1]
    if str(callback.from_user.id) != user_id:
        await callback.answer("🔒 Не ваша подборка", show_alert=True)
        return

    GALLERY[user_id]["selected"] = []
    save_gallery()
    await callback.message.edit_text("🧹 Подборка очищена. Можешь добавлять новые!")
    await callback.answer()

@router.callback_query(lambda c: c.data == "clear_cancel")
async def clear_cancel(callback, bot):
    await callback.message.edit_text("🆗 Оставлено как есть.")
    await callback.answer()

dp.include_router(router)

# === LIFESPAN (вместо on_event) ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_url = WEBHOOK_URL + WEBHOOK_PATH
    print(f"🔧 Устанавливаю вебхук: {webhook_url}")
    try:
        # 🔑 Ключевой вызов — без него Telegram не знает URL
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        info = await bot.get_webhook_info()
        print(f"✅ Вебхук активен: {info.url}")
        print(f"📥 pending_update_count: {info.pending_update_count}")
        if info.last_error_message:
            print(f"⚠️ Последняя ошибка: {info.last_error_message}")
    except Exception as e:
        print(f"❌ Ошибка установки вебхука: {e}")
    yield
    # Очистка при остановке
    await bot.delete_webhook(drop_pending_updates=True)

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    update_obj = Update.model_validate(update)
    await dp.feed_update(bot, update_obj)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok", "message": "Bot is running"}

@app.get("/ping")
async def ping():
    return {"pong": True}

# === ЗАПУСК ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)