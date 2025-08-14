import os
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook")
WEBAPP_PUBLIC = os.getenv("WEBAPP_PUBLIC", "")

# --- aiogram 3.x objects ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

@dp.message(commands=["start"])
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! 🎉 Это Foody бот.\n\n"
        "Здесь ты можешь смотреть акции и заказывать еду со скидками 🍔🥗\n\n"
        f"Открыть витрину: {WEBAPP_PUBLIC}"
    )

@app.post(f"/{WEBHOOK_SECRET}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
