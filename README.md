# Foody — готовый репозиторий

Залей содержимое архива в **пустой репозиторий**, затем подними 3 сервиса на Railway.

## Домены и БД (как ты просил)
- Web: https://foodyweb-production.up.railway.app
- Backend: https://foodyback-production.up.railway.app
- Bot: https://foodybot-production.up.railway.app
- DB: postgresql://postgres:gUgeLLNgbdfBnFmjLoPJNJjPynUvsxmG@postgres.railway.internal:5432/railway

## Railway — 3 сервиса

### backend
- Root Directory: `backend`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port 8080`
- ENV:
  - `DATABASE_URL=postgresql://postgres:gUgeLLNgbdfBnFmjLoPJNJjPynUvsxmG@postgres.railway.internal:5432/railway`
  - `RUN_MIGRATIONS=1`
  - `CORS_ORIGINS=https://foodyweb-production.up.railway.app,https://foodybot-production.up.railway.app`
  - `R2_ENDPOINT=https://c1892812feb332b56b53f2f36d14e95f.r2.cloudflarestorage.com`
  - `R2_BUCKET=foody`  # или твой
  - `R2_ACCESS_KEY_ID=<твоя_ключ>`
  - `R2_SECRET_ACCESS_KEY=<твой_секрет>`
  - `RECOVERY_SECRET=foodyDevRecover123`

### web
- Root Directory: `web`
- Start Command: `node server.js`
- ENV:
  - `FOODY_API=https://foodyback-production.up.railway.app`
- Проверка: `https://foodyweb-production.up.railway.app/config.js` → должен вернуть именно этот URL.

### bot
- Root Directory: `bot`
- Start Command: `uvicorn bot_webhook:app --host 0.0.0.0 --port 8080`
- ENV:
  - `BOT_TOKEN=8222050943:AAGn4jJODAwq5Qw9goY2amRps__NKel5eZ8`
  - `WEBHOOK_SECRET=foodySecret123`
  - `WEBAPP_PUBLIC=https://foodyweb-production.up.railway.app`

## Smoke-тесты
```
curl -sS https://foodyback-production.up.railway.app/health
curl -sS -X POST https://foodyback-production.up.railway.app/api/v1/merchant/register_public   -H "Content-Type: application/json"   -d '{"title":"Пекарня №1","phone":"+79990000000","city":"Москва","address":"Тверская,1"}'
# Открой в браузере:
# https://foodyweb-production.up.railway.app/web/merchant/
# https://foodyweb-production.up.railway.app/web/buyer/
```
