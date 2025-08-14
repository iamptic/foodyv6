import os, io, csv, json, secrets, datetime as dt
from typing import Optional, Dict, Any, List

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from backend import bootstrap_sql

DB_URL = os.getenv("DATABASE_URL")

app = FastAPI(title="Foody Backend — MVP API")

# CORS
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

_pool: Optional[asyncpg.pool.Pool] = None

async def pool() -> asyncpg.pool.Pool:
    global _pool
    if _pool is None:
        if not DB_URL:
            raise RuntimeError("DATABASE_URL not set")
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=5)
    return _pool

def rid() -> str:
    return "RID_" + secrets.token_hex(4)
def apikey() -> str:
    return "KEY_" + secrets.token_hex(8)
def offid() -> str:
    return "OFF_" + secrets.token_hex(6)

def row_offer(r: asyncpg.Record) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "restaurant_id": r["restaurant_id"],
        "title": r["title"],
        "description": r.get("description"),
        "price_cents": r["price_cents"],
        "original_price_cents": r.get("original_price_cents"),
        "qty_left": r["qty_left"],
        "qty_total": r["qty_total"],
        "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
        "archived_at": r["archived_at"].isoformat() if r.get("archived_at") else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }

async def auth(conn: asyncpg.Connection, key: str, restaurant_id: Optional[str]) -> str:
    if not key:
        return ""
    if restaurant_id:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", restaurant_id, key)
        return r["id"] if r else ""
    r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE api_key=$1", key)
    return r["id"] if r else ""

@app.on_event("startup")
async def _startup():
    # Run migrations
    bootstrap_sql.ensure()
    # Seed data if needed
    try:
        p = await pool()
        async with p.acquire() as conn:
            await seed_if_needed(conn)
    except Exception as e:
        print("Startup seed warn:", repr(e))

@app.middleware("http")
async def guard(request: Request, call_next):
    try:
        resp = await call_next(request)
        return resp
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

@app.get("/health")
async def health():
    # Try to ping DB, but don't fail hard
    try:
        p = await pool()
        async with p.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/v1/merchant/register_public")
async def register_public(raw: Request):
    try:
        if raw.headers.get("content-type","").startswith("application/json"):
            data = await raw.json()
        else:
            txt = await raw.body()
            data = json.loads((txt or b"{}").decode("utf-8"))
    except Exception:
        data = {}
    title = (data.get("title") or "").strip()
    phone = (data.get("phone") or "").strip() or None
    if not title:
        raise HTTPException(422, "title is required")
    p = await pool()
    async with p.acquire() as conn:
        rid_new = rid()
        key_new = apikey()
        await conn.execute(
            "INSERT INTO foody_restaurants(id, api_key, title, phone) VALUES($1,$2,$3,$4)",
            rid_new, key_new, title, phone
        )
    return {"restaurant_id": rid_new, "api_key": key_new}

@app.get("/api/v1/merchant/profile")
async def get_profile(restaurant_id: str, x_foody_key: str = Header(default="")):
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, restaurant_id)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        r = await conn.fetchrow("SELECT id, title, phone, city, address, geo FROM foody_restaurants WHERE id=$1", restaurant_id)
        if not r:
            raise HTTPException(404, "Restaurant not found")
        return {"id": r["id"], "title": r["title"], "phone": r["phone"], "city": r["city"], "address": r["address"], "geo": r["geo"]}

@app.post("/api/v1/merchant/profile")
async def set_profile(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(default="")):
    rid_in = (body.get("restaurant_id") or "").strip()
    title = (body.get("title") or "").strip() or None
    phone = (body.get("phone") or "").strip() or None
    city = (body.get("city") or "").strip() or None
    address = (body.get("address") or "").strip() or None
    geo = (body.get("geo") or "").strip() or None
    if not rid_in:
        raise HTTPException(422, "restaurant_id is required")
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, rid_in)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        await conn.execute(
            "UPDATE foody_restaurants SET title=COALESCE($1,title), phone=$2, city=$3, address=$4, geo=$5 WHERE id=$6",
            title, phone, city, address, geo, rid_in
        )
    return {"ok": True}

@app.get("/api/v1/merchant/offers")
async def merchant_offers(restaurant_id: str, status: Optional[str] = None, x_foody_key: str = Header(default="")):
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, restaurant_id)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        where = ["restaurant_id=$1"]
        params: List[Any] = [restaurant_id]
        if status == "active":
            where.append("(archived_at IS NULL)")
            where.append("(expires_at IS NULL OR expires_at > NOW())")
            where.append("(qty_left IS NULL OR qty_left > 0)")
        sql = f"SELECT * FROM foody_offers WHERE {' AND '.join(where)} ORDER BY expires_at NULLS LAST, id"
        rows = await conn.fetch(sql, *params)
        return [row_offer(r) for r in rows]

@app.post("/api/v1/merchant/offers")
async def create_offer(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(default="")):
    rid_in = (body.get("restaurant_id") or "").strip()
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, rid_in)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        oid = offid()
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(422, "title is required")
        description = (body.get("description") or None)
        price_cents = int(body.get("price_cents") or 0)
        original_price_cents = int(body.get("original_price_cents") or 0) or None
        qty_total = int(body.get("qty_total") or 0)
        qty_left = int(body.get("qty_left") or qty_total)
        expires_at = body.get("expires_at")
        expires_ts = None
        if expires_at:
            try:
                expires_ts = dt.datetime.fromisoformat(expires_at.replace("Z","+00:00"))
            except Exception:
                raise HTTPException(422, "expires_at must be ISO8601")
        await conn.execute(
            """INSERT INTO foody_offers(id, restaurant_id, title, description, price_cents, original_price_cents,
                                        qty_left, qty_total, expires_at)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            oid, rid_in, title, description, price_cents, original_price_cents, qty_left, qty_total, expires_ts
        )
        r = await conn.fetchrow("SELECT * FROM foody_offers WHERE id=$1", oid)
        return row_offer(r)

@app.delete("/api/v1/merchant/offers/{offer_id}")
async def delete_offer(offer_id: str, restaurant_id: Optional[str] = None, x_foody_key: str = Header(default="")):
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, restaurant_id)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        chk = await conn.fetchrow("SELECT id, restaurant_id FROM foody_offers WHERE id=$1", offer_id)
        if not chk:
            raise HTTPException(404, "Offer not found")
        if restaurant_id and chk["restaurant_id"] != restaurant_id:
            raise HTTPException(403, "Offer belongs to another restaurant")
        await conn.execute("UPDATE foody_offers SET archived_at=NOW() WHERE id=$1", offer_id)
        return {"ok": True, "deleted": offer_id}

def with_timer_discount(r: Dict[str, Any]) -> Dict[str, Any]:
    """Compute time-step discount based on expires_at."""
    out = dict(r)
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    expires_at = None
    if r["expires_at"]:
        try:
            expires_at = dt.datetime.fromisoformat(r["expires_at"].replace("Z","+00:00"))
        except Exception:
            expires_at = None
    step = None
    discount_percent = 0
    if expires_at:
        delta = (expires_at - now).total_seconds() / 60.0
        if delta <= 30:
            discount_percent = 70
            step = "-70%"
        elif delta <= 60:
            discount_percent = 50
            step = "-50%"
        elif delta <= 120:
            discount_percent = 30
            step = "-30%"
    original = r.get("original_price_cents") or r.get("price_cents")
    current = r.get("price_cents")
    if (original and original > 0) and discount_percent > 0:
        # Override current price according to discount
        current = int(round(original * (1 - discount_percent/100)))
    out["timer_discount_percent"] = discount_percent
    out["timer_step"] = step
    out["price_cents_effective"] = current
    return out

@app.get("/api/v1/offers")
async def public_offers(limit: int = Query(200, ge=1, le=500)):
    p = await pool()
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM foody_offers
               WHERE (archived_at IS NULL)
                 AND (expires_at IS NULL OR expires_at > NOW())
                 AND (qty_left IS NULL OR qty_left > 0)
               ORDER BY expires_at NULLS LAST, id
               LIMIT $1""", limit
        )
        base = [row_offer(r) for r in rows]
        return [with_timer_discount(o) for o in base]

@app.get("/api/v1/merchant/offers/csv")
async def export_csv(restaurant_id: str):
    p = await pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM foody_offers WHERE restaurant_id=$1 ORDER BY created_at", restaurant_id)
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id","restaurant_id","title","description","price_cents","original_price_cents","qty_left","qty_total","expires_at","archived_at","created_at"])
        for r in rows:
            w.writerow([
                r["id"], r["restaurant_id"], r["title"], r.get("description") or "",
                r["price_cents"], r.get("original_price_cents") or "",
                r["qty_left"], r["qty_total"],
                r["expires_at"].isoformat() if r.get("expires_at") else "",
                r["archived_at"].isoformat() if r.get("archived_at") else "",
                r["created_at"].isoformat() if r.get("created_at") else "",
            ])
        yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=offers_{restaurant_id}.csv"})

@app.get("/api/v1/merchant/kpi")
async def kpi(restaurant_id: str, x_foody_key: str = Header(default="")):
    p = await pool()
    async with p.acquire() as conn:
        rid_ok = await auth(conn, x_foody_key, restaurant_id)
        if not rid_ok:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        return {"reserved": 0, "redeemed": 0, "redemption_rate": 0.0, "revenue_cents": 0, "saved_cents": 0}

@app.post("/api/v1/merchant/redeem")
async def redeem(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(default="")):
    return {"ok": False, "detail": "Reservations are not enabled on this server"}

# ---- Seed logic ----
TEST_RID = "RID_TEST"
TEST_KEY = "KEY_TEST"

async def seed_if_needed(conn: asyncpg.Connection):
    # Ensure columns exist (bootstrap_sql already handled)
    cnt = await conn.fetchval("SELECT COUNT(*) FROM foody_restaurants")
    has_test = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1", TEST_RID)
    if cnt and has_test:
        return  # already ok
    if cnt and not has_test:
        # Clean up old data to avoid conflicts
        try:
            await conn.execute("TRUNCATE foody_offers RESTART IDENTITY CASCADE")
        except Exception:
            pass
        try:
            await conn.execute("TRUNCATE foody_restaurants RESTART IDENTITY CASCADE")
        except Exception:
            pass
    # Insert test restaurant and 3 offers
    await conn.execute(
        "INSERT INTO foody_restaurants(id, api_key, title, phone, city, address, geo) VALUES($1,$2,$3,$4,$5,$6,$7)",
        TEST_RID, TEST_KEY, "Пекарня №1", "+7 900 000-00-00", "Москва", "ул. Пекарная, 10", "55.7558, 37.6173"
    )
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    def exp(minutes): return now + dt.timedelta(minutes=minutes)
    demo = [
        ("Эклеры", "Набор свежих эклеров", 19900, 34900, 5, 5, exp(110)),  # -30%
        ("Пирожки", "Пирожки с мясом", 14900, 29900, 8, 8, exp(55)),       # -50%
        ("Круассаны", "Круассаны с маслом", 9900, 32900, 6, 6, exp(25)),   # -70%
    ]
    for title, desc, price, orig, qty_left, qty_total, expires in demo:
        await conn.execute(
            """INSERT INTO foody_offers(id, restaurant_id, title, description, price_cents, original_price_cents,
                                        qty_left, qty_total, expires_at)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            offid(), TEST_RID, title, desc, price, orig, qty_left, qty_total, expires
        )

# uvicorn backend.main:app --host 0.0.0.0 --port 8080
