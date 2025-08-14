# Foody (full repo) — repo-1755183402

## Railway services

### backend
- Root Directory: `backend`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port 8080`
- ENV:
  - `DATABASE_URL=...`
  - `RUN_MIGRATIONS=1`
  - `CORS_ORIGINS=https://web-production-5431c.up.railway.app,https://bot-production-0297.up.railway.app`
  - `R2_ENDPOINT=https://c1892812feb332b56b53f2f36d14e95f.r2.cloudflarestorage.com`
  - `R2_BUCKET=foody`
  - `R2_ACCESS_KEY_ID=...`
  - `R2_SECRET_ACCESS_KEY=...`
  - `RECOVERY_SECRET=foodyDevRecover123`

### web
- Root Directory: `web`
- Start Command: `node server.js`
- ENV: `FOODY_API=https://<backend-domain>`
- Проверка: открой `https://<web-domain>/config.js` → должен быть правильный URL бэка.

### bot
- Root Directory: `bot`
- Start Command: `uvicorn bot_webhook:app --host 0.0.0.0 --port 8080`
- ENV:
  - `BOT_TOKEN=...`
  - `WEBHOOK_SECRET=foodySecret123`
  - `WEBAPP_PUBLIC=https://web-production-5431c.up.railway.app`

## Примечания
- В `web/server.js` включён no-cache для HTML и `/config.js`.
- В `web/web/merchant/index.html` убран RID/KEY из UI, добавлен вход по телефону (dev-recover).
- Логотип: `web/web/logo.png`, фавикон: `web/web/favicon.png`.
