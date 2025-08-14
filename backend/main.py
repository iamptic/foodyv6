
import os
import secrets
import datetime as dt
from typing import Optional, Dict, Any, List

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

import bootstrap_sql

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

def row_restaurant(r: asyncpg.Record) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "api_key": r.get("api_key"),
        "title": r["title"],
        "phone": r.get("phone"),
        "city": r.get("city"),
        "address": r.get("address"),
        "geo": r.get("geo"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }

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
async def on_startup():
    bootstrap_sql.ensure()
    # Optionally seed demo data if empty
    async with (await pool()).acquire() as conn:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM foody_restaurants")
        if cnt == 0:
            rid_test = "RID_TEST"
            key_test = "KEY_TEST"
            await conn.execute(
                "INSERT INTO foody_restaurants(id, api_key, title, phone) VALUES($1,$2,$3,$4) ON CONFLICT (id) DO NOTHING",
                rid_test, key_test, "Тестовая Пекарня", "+7 900 000-00-00"
            )
            # Add a few demo offers
            now = dt.datetime.utcnow()
            demo = [
                ("Эклеры", "Набор свежих эклеров", 19900, 34900, 5, 5, now + dt.timedelta(minutes=110)),
                ("Пирожки", "Пирожки с мясом", 14900, 29900, 8, 8, now + dt.timedelta(minutes=55)),
                ("Круассаны", "Круассаны с маслом", 9900, 32900, 6, 6, now + dt.timedelta(minutes=25)),
            ]
            for title, desc, price, orig, qty_left, qty_total, expires in demo:
                await conn.execute(
                    """INSERT INTO foody_offers(id, restaurant_id, title, description, price_cents, original_price_cents,
                                                qty_left, qty_total, expires_at)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                    offid(), rid_test, title, desc, price, orig, qty_left, qty_total, expires
                )

@app.get("/health")
async def health():
    return {"ok": True, "version": "mvp-fixed"}

# ---- Merchant APIs ----

@app.post("/api/v1/merchant/register_public")
async def register_public(body: Dict[str, Any] = Body(...)):
    title = (body.get("title") or "").strip()
    phone = (body.get("phone") or "").strip() or None
    if not title:
        raise HTTPException(400, "title is required")
    async with (await pool()).acquire() as conn:
        rid_new = rid()
        key_new = apikey()
        await conn.execute(
            "INSERT INTO foody_restaurants(id, api_key, title, phone) VALUES($1,$2,$3,$4)",
            rid_new, key_new, title, phone
        )
        r = await conn.fetchrow("SELECT * FROM foody_restaurants WHERE id=$1", rid_new)
        return {"ok": True, "restaurant": row_restaurant(r), "api_key": key_new}

@app.get("/api/v1/merchant/profile")
async def get_profile(restaurant_id: str = Query(...), x_foody_key: str = Header(default="")):
    async with (await pool()).acquire() as conn:
        rid_auth = await auth(conn, x_foody_key, restaurant_id)
        if not rid_auth:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        r = await conn.fetchrow("SELECT * FROM foody_restaurants WHERE id=$1", restaurant_id)
        if not r:
            raise HTTPException(404, "Restaurant not found")
        return row_restaurant(r)

@app.post("/api/v1/merchant/profile")
async def set_profile(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(default="")):
    rid_in = (body.get("restaurant_id") or "").strip()
    title = (body.get("title") or "").strip() or None
    phone = (body.get("phone") or "").strip() or None
    city = (body.get("city") or "").strip() or None
    address = (body.get("address") or "").strip() or None
    geo = (body.get("geo") or "").strip() or None
    if not rid_in:
        raise HTTPException(400, "restaurant_id is required")
    async with (await pool()).acquire() as conn:
        rid_auth = await auth(conn, x_foody_key, rid_in)
        if not rid_auth:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        await conn.execute(
            """UPDATE foody_restaurants
               SET title=COALESCE($2,title), phone=$3, city=$4, address=$5, geo=$6
               WHERE id=$1""",
            rid_in, title, phone, city, address, geo
        )
        r = await conn.fetchrow("SELECT * FROM foody_restaurants WHERE id=$1", rid_in)
        return {"ok": True, "restaurant": row_restaurant(r)}

@app.post("/api/v1/merchant/offers")
async def create_offer(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(default="")):
    rid_in = (body.get("restaurant_id") or "").strip()
    if not rid_in:
        raise HTTPException(400, "restaurant_id is required")
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    description = (body.get("description") or "").strip() or None
    price_cents = int(body.get("price_cents") or 0)
    original_price_cents = int(body.get("original_price_cents") or 0) or None
    qty_total = int(body.get("qty_total") or 0)
    qty_left = int(body.get("qty_left") or qty_total)
    expires_at_raw = body.get("expires_at")
    expires_at = None
    if expires_at_raw:
        try:
            expires_at = dt.datetime.fromisoformat(expires_at_raw.replace("Z","+00:00"))
        except Exception:
            raise HTTPException(400, "expires_at must be ISO8601")

    async with (await pool()).acquire() as conn:
        rid_auth = await auth(conn, x_foody_key, rid_in)
        if not rid_auth:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        oid = offid()
        await conn.execute(
            """INSERT INTO foody_offers(id, restaurant_id, title, description, price_cents, original_price_cents,
                                        qty_left, qty_total, expires_at)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            oid, rid_in, title, description, price_cents, original_price_cents, qty_left, qty_total, expires_at
        )
        r = await conn.fetchrow("SELECT * FROM foody_offers WHERE id=$1", oid)
        return {"ok": True, "offer": row_offer(r)}

@app.get("/api/v1/merchant/offers/csv")
async def export_offers_csv(restaurant_id: str = Query(...), x_foody_key: str = Header(default="")):
    async with (await pool()).acquire() as conn:
        rid_auth = await auth(conn, x_foody_key, restaurant_id)
        if not rid_auth:
            raise HTTPException(401, "Invalid API key or restaurant_id")
        rows = await conn.fetch(
            "SELECT * FROM foody_offers WHERE restaurant_id=$1 ORDER BY created_at DESC", restaurant_id
        )
        import io, csv
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id","title","price_cents","original_price_cents","qty_left","qty_total","expires_at","created_at"])
        for r in rows:
            w.writerow([
                r["id"], r["title"], r["price_cents"], r.get("original_price_cents"),
                r["qty_left"], r["qty_total"],
                r["expires_at"].isoformat() if r.get("expires_at") else "",
                r["created_at"].isoformat() if r.get("created_at") else ""
            ])
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv")

# ---- Public APIs ----

@app.get("/api/v1/offers")
async def public_offers(city: Optional[str] = Query(default=None)):
    async with (await pool()).acquire() as conn:
        # For MVP, simply list active (non-archived, not expired) offers
        rows = await conn.fetch(
            """SELECT * FROM foody_offers
               WHERE archived_at IS NULL AND (expires_at IS NULL OR expires_at > NOW())
               ORDER BY expires_at NULLS LAST, created_at DESC
            """
        )
        return {"offers": [row_offer(r) for r in rows]}

# uvicorn backend.main:app --host 0.0.0.0 --port 8080
