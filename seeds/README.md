
# Foody seeds (curl)
API=https://<backend>

# health
curl -sS $API/health

# register
curl -sS -XPOST $API/api/v1/merchant/register_public -H 'Content-Type: application/json' -d '{"title":"Пекарня №1","phone":"+79991234567","city":"Москва","address":"Тверская, 1"}'

# public offers
curl -sS $API/api/v1/offers
