
# Foody seeds (curl)
API=https://foodyback-production.up.railway.app
curl -sS $API/health
curl -sS -XPOST $API/api/v1/merchant/register_public -H 'Content-Type: application/json' -d '{"title":"Пекарня №1","phone":"+79991234567","city":"Москва","address":"Тверская, 1"}'
curl -sS $API/api/v1/offers
