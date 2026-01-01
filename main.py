import os
from dotenv import load_dotenv
from aiogram import Bot
from fastapi import FastAPI, Request

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/") + WEBHOOK_PATH

bot = Bot(token=TOKEN)
app = FastAPI()

@app.on_event("startup")
async def startup():
    print(f"Setting webhook to: {WEBHOOK_URL}")
    result = await bot.set_webhook(WEBHOOK_URL)
    print("Webhook set:", result)

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    print("✅ Webhook received!")
    update = await request.json()
    print("Update:", update.get("update_id"))
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok"}