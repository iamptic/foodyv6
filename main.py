import os
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
WEBAPP_PUBLIC = os.getenv("WEBAPP_PUBLIC")  # URL фронтенда

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
app = FastAPI()

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! 🎉 Это Foody бот.\n\n"
        "Здесь ты можешь смотреть акции и заказывать еду со скидками 🍔🥗\n\n"
        f"Открыть витрину: {WEBAPP_PUBLIC}"
    )

@app.post(f"/{WEBHOOK_SECRET}")
async def telegram_webhook(request: Request):
    update = Update(**await request.json())
    await dp.process_update(update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"ok": True}

# Railway старт:
# uvicorn main:app --host 0.0.0.0 --port $PORT
