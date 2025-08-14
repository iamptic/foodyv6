
from fastapi import FastAPI, Request, Header
import os

app = FastAPI()

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
WEBAPP_PUBLIC = os.getenv('WEBAPP_PUBLIC', '')

@app.get('/')
async def root():
    return {'ok': True}

@app.post('/webhook')
async def webhook(request: Request, x_webhook_secret: str = Header(None)):
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        return {'ok': False, 'detail': 'forbidden'}
    # Just a stub: echo minimal menu (normally you'd call Telegram API here)
    return {'ok': True, 'menu': [{'text':'Витрина','url':WEBAPP_PUBLIC+'/web/buyer/'},{'text':'ЛК партнёра','url':WEBAPP_PUBLIC+'/web/merchant/'}]}
