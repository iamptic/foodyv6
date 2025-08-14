import os
import math
import json
import time
import base64
import secrets
import datetime as dt
from typing import Optional, List, Dict, Any

import asyncpg
from fastapi import FastAPI, Request, Body, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware

# ---------- Config ----------
APP_VERSION = "mvp-1.0"
DATABASE_URL = os.getenv("DATABASE_URL", "")
RUN_MIGRATIONS = os.getenv("RUN_MIGRATIONS", "0") == "1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_AK = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SK = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_BASE = os.getenv("R2_PUBLIC_BASE", "")  # optional public base url for view

RECOVERY_SECRET = os.getenv("RECOVERY_SECRET", "")  # dev-only recover

if not DATABASE_URL:
    print("[WARN] DATABASE_URL not set")

app = FastAPI(title="Foody Backend", version=APP_VERSION)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=3600,
    )

_pool: Optional[asyncpg.Pool] = None

async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool

def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"

def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

# ---------- Bootstrap / migrations ----------
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS foody_restaurants(
  id TEXT PRIMARY KEY,
  api_key TEXT NOT NULL,
  title TEXT NOT NULL,
  phone TEXT NULL,
  city TEXT NULL,
  address TEXT NULL,
  lat DOUBLE PRECISION NULL,
  lon DOUBLE PRECISION NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS foody_offers(
  id TEXT PRIMARY KEY,
  restaurant_id TEXT NOT NULL REFERENCES foody_restaurants(id),
  title TEXT NOT NULL,
  description TEXT NULL,
  price_cents INT NOT NULL,
  original_price_cents INT NULL,
  qty_left INT NOT NULL DEFAULT 0,
  qty_total INT NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ NULL,
  archived_at TIMESTAMPTZ NULL,
  photo_url TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS foody_reservations(
  id TEXT PRIMARY KEY,
  offer_id TEXT NOT NULL REFERENCES foody_offers(id),
  restaurant_id TEXT NOT NULL REFERENCES foody_restaurants(id),
  qty INT NOT NULL DEFAULT 1,
  code TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'reserved', -- reserved|canceled|redeemed
  created_at TIMESTAMPTZ DEFAULT NOW(),
  canceled_at TIMESTAMPTZ NULL,
  redeemed_at TIMESTAMPTZ NULL
);

-- Safe add columns if they don't exist
ALTER TABLE foody_restaurants ADD COLUMN IF NOT EXISTS city TEXT NULL;
ALTER TABLE foody_restaurants ADD COLUMN IF NOT EXISTS address TEXT NULL;
ALTER TABLE foody_restaurants ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION NULL;
ALTER TABLE foody_restaurants ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION NULL;
ALTER TABLE foody_offers ADD COLUMN IF NOT EXISTS original_price_cents INT NULL;
ALTER TABLE foody_offers ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL;
ALTER TABLE foody_offers ADD COLUMN IF NOT EXISTS photo_url TEXT NULL;
"""

async def run_migrations():
    if not RUN_MIGRATIONS:
        print("[BOOT] RUN_MIGRATIONS != 1, skipping DDL")
        return
    p = await pool()
    async with p.acquire() as conn:
        for stmt in CREATE_SQL.split(";\n\n"):
            s = stmt.strip()
            if s:
                try:
                    await conn.execute(s)
                except Exception as e:
                    print("[DDL warn]", e)

@app.on_event("startup")
async def on_startup():
    await run_migrations()

# ---------- Helpers ----------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

def discount_step(expires_at: Optional[dt.datetime]) -> int:
    """Return discount percent according to time left to expire: <=120m:30, <=60:50, <=30:70"""
    if not expires_at:
        return 0
    left = (expires_at - now_utc()).total_seconds() / 60.0
    if left <= 0:
        return 0
    if left <= 30:
        return 70
    if left <= 60:
        return 50
    if left <= 120:
        return 30
    return 0

def effective_price(price_cents: int, original_price_cents: Optional[int], expires_at: Optional[dt.datetime]) -> int:
    if original_price_cents and original_price_cents > 0:
        step = discount_step(expires_at)
        if step > 0:
            # apply step to original
            eff = int(round(original_price_cents * (100 - step) / 100))
            return max(0, eff)
    return price_cents

def to_cents_from_rub(rub: Optional[float], default: int = 0) -> int:
    try:
        if rub is None:
            return default
        return int(round(float(rub) * 100))
    except Exception:
        return default

def from_row_offer(row: asyncpg.Record, buyer_lat=None, buyer_lon=None) -> Dict[str, Any]:
    exp = row["expires_at"]
    eff = effective_price(row["price_cents"], row["original_price_cents"], exp)
    dist = None
    if buyer_lat is not None and buyer_lon is not None:
        dist = haversine_km(buyer_lat, buyer_lon, row["r_lat"], row["r_lon"])
    return {
        "id": row["id"],
        "restaurant_id": row["restaurant_id"],
        "title": row["title"],
        "description": row["description"],
        "price_cents": row["price_cents"],
        "original_price_cents": row["original_price_cents"],
        "effective_price_cents": eff,
        "qty_left": row["qty_left"],
        "qty_total": row["qty_total"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "archived_at": row["archived_at"].isoformat() if row["archived_at"] else None,
        "photo_url": row["photo_url"],
        "restaurant": {
            "title": row["r_title"],
            "phone": row["r_phone"],
            "city": row["r_city"],
            "address": row["r_address"],
            "lat": row["r_lat"],
            "lon": row["r_lon"],
        },
        "distance_km": dist,
        "discount_step": discount_step(exp),
    }

def make_qr_png_b64(text: str) -> str:
    try:
        import io, segno
        buf = io.BytesIO()
        segno.make(text, micro=False).save(buf, kind="png", scale=5)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        # 1x1 png fallback
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="

# ---------- Routes ----------
@app.get("/health")
async def health():
    return {"ok": True, "version": APP_VERSION, "time": now_utc().isoformat()}

# Registration
@app.post("/api/v1/merchant/register_public")
async def register_public(req: Request):
    try:
        if req.headers.get("content-type","").startswith("application/json"):
            data = await req.json()
        else:
            body = await req.body()
            data = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid body")
    title = (data.get("title") or "").strip()
    phone = (data.get("phone") or "").strip()
    city = (data.get("city") or "").strip() or None
    address = (data.get("address") or "").strip() or None
    lat = float(data.get("lat")) if data.get("lat") not in (None, "") else None
    lon = float(data.get("lon")) if data.get("lon") not in (None, "") else None
    if not title:
        raise HTTPException(422, "title required")
    rid = new_id("RID")
    key = new_id("KEY")
    p = await pool()
    async with p.acquire() as conn:
        await conn.execute(
            "INSERT INTO foody_restaurants(id, api_key, title, phone, city, address, lat, lon) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            rid, key, title, phone or None, city, address, lat, lon
        )
    return {"restaurant_id": rid, "api_key": key}

def check_auth(key: str, rid: str):
    if not key or not rid:
        raise HTTPException(401, "Auth required")

# Profile
@app.get("/api/v1/merchant/profile")
async def profile_get(restaurant_id: str, x_foody_key: str = Header(None)):
    check_auth(x_foody_key, restaurant_id)
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id, title, phone, city, address, lat, lon FROM foody_restaurants WHERE id=$1 AND api_key=$2", restaurant_id, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        return dict(r)

@app.post("/api/v1/merchant/profile")
async def profile_post(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(None)):
    rid = body.get("restaurant_id")
    check_auth(x_foody_key, rid)
    fields = ["title","phone","city","address","lat","lon"]
    updates = {k: body.get(k) for k in fields}
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", rid, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        await conn.execute(
            "UPDATE foody_restaurants SET title=COALESCE($2,title), phone=$3, city=$4, address=$5, lat=$6, lon=$7 WHERE id=$1",
            rid, updates.get("title"), updates.get("phone"), updates.get("city"), updates.get("address"), updates.get("lat"), updates.get("lon"),
        )
    return {"ok": True}

# Offers (merchant)
@app.get("/api/v1/merchant/offers")
async def merchant_offers(restaurant_id: str, status: str = "active", x_foody_key: str = Header(None)):
    check_auth(x_foody_key, restaurant_id)
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", restaurant_id, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        q = "SELECT * FROM foody_offers WHERE restaurant_id=$1"
        params = [restaurant_id]
        if status == "active":
            q += " AND archived_at IS NULL"
        elif status == "archived":
            q += " AND archived_at IS NOT NULL"
        q += " ORDER BY created_at DESC"
        rows = await conn.fetch(q, *params)
        out = []
        for row in rows:
            out.append({
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "price_cents": row["price_cents"],
                "original_price_cents": row["original_price_cents"],
                "qty_left": row["qty_left"],
                "qty_total": row["qty_total"],
                "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                "archived_at": row["archived_at"].isoformat() if row["archived_at"] else None,
                "photo_url": row["photo_url"],
            })
        return out

@app.post("/api/v1/merchant/offers")
async def merchant_offer_create(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(None)):
    rid = body.get("restaurant_id")
    check_auth(x_foody_key, rid)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "title required")
    description = (body.get("description") or None)
    price_cents = to_cents_from_rub(body.get("price_rub"), body.get("price_cents") or 0)
    original_price_cents = to_cents_from_rub(body.get("original_price_rub"), body.get("original_price_cents") or None) or None
    qty_total = int(body.get("qty_total") or 0)
    qty_left  = int(body.get("qty_left") or qty_total)
    expires_at_s = body.get("expires_at")
    expires_at = None
    if expires_at_s:
        try:
            expires_at = dt.datetime.fromisoformat(expires_at_s.replace("Z","+00:00"))
        except Exception:
            raise HTTPException(422, "invalid expires_at")
    photo_url = body.get("photo_url") or None
    off_id = new_id("OFF")
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", rid, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        await conn.execute("""
            INSERT INTO foody_offers(id, restaurant_id, title, description, price_cents, original_price_cents, qty_left, qty_total, expires_at, photo_url)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """, off_id, rid, title, description, price_cents, original_price_cents, qty_left, qty_total, expires_at, photo_url)
    return {"id": off_id}

@app.delete("/api/v1/merchant/offers/{offer_id}")
async def merchant_offer_delete(offer_id: str, restaurant_id: Optional[str] = None, x_foody_key: str = Header(None)):
    if restaurant_id is None:
        raise HTTPException(422, "restaurant_id required")
    check_auth(x_foody_key, restaurant_id)
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", restaurant_id, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        await conn.execute("UPDATE foody_offers SET archived_at=NOW() WHERE id=$1 AND restaurant_id=$2", offer_id, restaurant_id)
    return {"ok": True}

# Public offers
@app.get("/api/v1/offers")
async def public_offers(lat: Optional[float] = None, lon: Optional[float] = None, sort: str = "new", radius_km: Optional[float] = None):
    p = await pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("""
            SELECT o.*, r.title as r_title, r.phone as r_phone, r.city as r_city, r.address as r_address, r.lat as r_lat, r.lon as r_lon
            FROM foody_offers o
            JOIN foody_restaurants r ON r.id = o.restaurant_id
            WHERE o.archived_at IS NULL
              AND (o.expires_at IS NULL OR o.expires_at > NOW())
              AND o.qty_left > 0
            ORDER BY o.created_at DESC
        """)
        out = [from_row_offer(row, lat, lon) for row in rows]
        # Filter by radius
        if radius_km is not None and lat is not None and lon is not None:
            out = [x for x in out if x["distance_km"] is not None and x["distance_km"] <= radius_km]
        # Sort
        if sort == "price":
            out.sort(key=lambda x: x["effective_price_cents"] if x["effective_price_cents"] is not None else 1e12)
        elif sort == "distance" and lat is not None and lon is not None:
            out.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else 1e12)
        else:  # new
            pass
        return out

# CSV export
@app.get("/api/v1/merchant/offers/csv")
async def merchant_offers_csv(restaurant_id: str, x_foody_key: str = Header(None)):
    check_auth(x_foody_key, restaurant_id)
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", restaurant_id, x_foody_key)
        if not r:
            raise HTTPException(403, "Invalid RID/KEY")
        rows = await conn.fetch("""
            SELECT id, title, description, price_cents, original_price_cents, qty_total, qty_left, expires_at, archived_at, created_at
            FROM foody_offers WHERE restaurant_id=$1 ORDER BY created_at DESC
        """, restaurant_id)
    # Build CSV
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id","title","description","price_cents","original_price_cents","qty_total","qty_left","expires_at","archived_at","created_at"])
    for row in rows:
        w.writerow([row["id"], row["title"], row["description"], row["price_cents"], row["original_price_cents"],
                   row["qty_total"], row["qty_left"],
                   row["expires_at"].isoformat() if row["expires_at"] else "", 
                   row["archived_at"].isoformat() if row["archived_at"] else "",
                   row["created_at"].isoformat() if row["created_at"] else ""])
    csv_data = buf.getvalue().encode("utf-8")
    return Response(content=csv_data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="offers_{restaurant_id}.csv"'})

# Reservations
@app.post("/api/v1/reservations")
async def reservation_create(body: Dict[str, Any] = Body(...)):
    offer_id = (body.get("offer_id") or "").strip()
    qty = int(body.get("qty") or 1)
    if not offer_id or qty <= 0:
        raise HTTPException(422, "offer_id and positive qty required")
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            o = await conn.fetchrow("SELECT id, restaurant_id, qty_left FROM foody_offers WHERE id=$1 AND archived_at IS NULL AND (expires_at IS NULL OR expires_at > NOW())", offer_id)
            if not o:
                raise HTTPException(404, "Offer not available")
            if o["qty_left"] < qty:
                raise HTTPException(409, "Not enough qty")
            await conn.execute("UPDATE foody_offers SET qty_left=qty_left-$2 WHERE id=$1", offer_id, qty)
            code = new_id("RES")
            rid = o["restaurant_id"]
            res_id = new_id("RSV")
            await conn.execute("INSERT INTO foody_reservations(id, offer_id, restaurant_id, qty, code, status) VALUES($1,$2,$3,$4,$5,'reserved')",
                               res_id, offer_id, rid, qty, code)
    return {"code": code, "qrcode_png_base64": make_qr_png_b64(code)}

@app.post("/api/v1/reservations/cancel")
async def reservation_cancel(body: Dict[str, Any] = Body(...)):
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(422, "code required")
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            r = await conn.fetchrow("SELECT id, offer_id, qty, status FROM foody_reservations WHERE code=$1 FOR UPDATE", code)
            if not r:
                raise HTTPException(404, "Not found")
            if r["status"] != "reserved":
                raise HTTPException(409, "Not in reserved status")
            await conn.execute("UPDATE foody_reservations SET status='canceled', canceled_at=NOW() WHERE id=$1", r["id"])
            await conn.execute("UPDATE foody_offers SET qty_left=qty_left+$2 WHERE id=$1", r["offer_id"], r["qty"])
    return {"ok": True}

@app.post("/api/v1/merchant/redeem")
async def merchant_redeem(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(None)):
    code = (body.get("code") or "").strip()
    rid = (body.get("restaurant_id") or "").strip()
    check_auth(x_foody_key, rid)
    if not code:
        raise HTTPException(422, "code required")
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            # auth
            r = await conn.fetchrow("SELECT id FROM foody_restaurants WHERE id=$1 AND api_key=$2", rid, x_foody_key)
            if not r:
                raise HTTPException(403, "Invalid RID/KEY")
            resv = await conn.fetchrow("SELECT id, status FROM foody_reservations WHERE code=$1 AND restaurant_id=$2 FOR UPDATE", code, rid)
            if not resv:
                raise HTTPException(404, "Reservation not found")
            if resv["status"] != "reserved":
                raise HTTPException(409, "Already processed")
            await conn.execute("UPDATE foody_reservations SET status='redeemed', redeemed_at=NOW() WHERE id=$1", resv["id"])
    return {"ok": True}

@app.get("/api/v1/reservations/qr")
async def reservation_qr(code: str):
    if not code:
        raise HTTPException(422, "code required")
    return {"qrcode_png_base64": make_qr_png_b64(code)}

# Dev-only recover by phone
@app.post("/api/v1/merchant/recover")
async def merchant_recover(body: Dict[str, Any] = Body(...)):
    if not RECOVERY_SECRET:
        raise HTTPException(503, "Recovery is not enabled")
    if (body.get("secret") or "") != RECOVERY_SECRET:
        raise HTTPException(403, "Forbidden")
    phone = (body.get("phone") or "").strip()
    if not phone:
        raise HTTPException(422, "phone required")
    p = await pool()
    async with p.acquire() as conn:
        r = await conn.fetchrow("SELECT id, api_key, title FROM foody_restaurants WHERE phone=$1 ORDER BY created_at DESC LIMIT 1", phone)
        if not r:
            raise HTTPException(404, "Not found")
        return {"restaurant_id": r["id"], "api_key": r["api_key"], "title": r["title"]}

# Presign upload to R2
@app.post("/api/v1/merchant/upload_url")
async def upload_url(body: Dict[str, Any] = Body(...), x_foody_key: str = Header(None)):
    # Optional auth check: require RID/KEY to generate upload
    rid = (body.get("restaurant_id") or "").strip()
    check_auth(x_foody_key, rid)
    key = f"photos/{rid}/{new_id('IMG')}.jpg"
    if not (R2_ENDPOINT and R2_BUCKET and R2_AK and R2_SK):
        raise HTTPException(503, "R2 not configured")
    import boto3
    s3 = boto3.client("s3", endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_AK, aws_secret_access_key=R2_SK)
    put_url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": R2_BUCKET, "Key": key, "ContentType": "image/jpeg"},
        ExpiresIn=3600
    )
    if R2_PUBLIC_BASE:
        view_url = f"{R2_PUBLIC_BASE.rstrip('/')}/{key}"
    else:
        view_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": R2_BUCKET, "Key": key},
            ExpiresIn=3600
        )
    return {"put_url": put_url, "key": key, "view_url": view_url}
