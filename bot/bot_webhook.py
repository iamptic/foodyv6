from fastapi import FastAPI, Request, Header
import os

app = FastAPI(title="Foody Bot")

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
WEBAPP_PUBLIC = os.getenv('WEBAPP_PUBLIC', '')

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/webhook")
async def webhook(request: Request, x_webhook_secret: str = Header(None)):
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        return {"ok": False, "detail": "forbidden"}
    # In production integrate with Telegram; here we just return menu
    return {"ok": True, "menu": [
        {"text": "Открыть витрину", "url": WEBAPP_PUBLIC + "/web/buyer/"},
        {"text": "ЛК партнёра", "url": WEBAPP_PUBLIC + "/web/merchant/"}
    ]}
