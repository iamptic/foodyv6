
import os, asyncio, asyncpg

DDL_CREATE = [
    """CREATE TABLE IF NOT EXISTS foody_restaurants (
        id TEXT PRIMARY KEY,
        api_key TEXT NOT NULL,
        title TEXT NOT NULL,
        phone TEXT,
        city TEXT,
        address TEXT,
        geo TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS foody_offers (
        id TEXT PRIMARY KEY,
        restaurant_id TEXT NOT NULL REFERENCES foody_restaurants(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        description TEXT,
        price_cents INTEGER NOT NULL,
        original_price_cents INTEGER,
        qty_left INTEGER NOT NULL DEFAULT 0,
        qty_total INTEGER NOT NULL DEFAULT 0,
        expires_at TIMESTAMPTZ,
        archived_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""
]

DDL_ALTER = [
    "ALTER TABLE IF EXISTS foody_restaurants ADD COLUMN IF NOT EXISTS city TEXT",
    "ALTER TABLE IF EXISTS foody_restaurants ADD COLUMN IF NOT EXISTS address TEXT",
    "ALTER TABLE IF EXISTS foody_restaurants ADD COLUMN IF NOT EXISTS geo TEXT",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS original_price_cents INTEGER",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS price_cents INTEGER",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS qty_left INTEGER",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS qty_total INTEGER",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
    "ALTER TABLE IF EXISTS foody_offers ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
]

async def run():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("BOOTSTRAP: DATABASE_URL not set")
        return
    conn = await asyncpg.connect(db_url)
    try:
        for sql in DDL_CREATE:
            await conn.execute(sql)
        for sql in DDL_ALTER:
            try:
                await conn.execute(sql)
                print("BOOTSTRAP ALTER OK:", sql)
            except Exception as e:
                print("BOOTSTRAP ALTER WARN:", sql, "->", repr(e))
    finally:
        await conn.close()

def ensure():
    if os.getenv("RUN_MIGRATIONS", "0") not in ("1", "true", "TRUE", "yes", "on"):
        print("BOOTSTRAP: RUN_MIGRATIONS disabled")
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in an event loop (e.g., uvicorn on Railway)
            loop.create_task(run())
        else:
            loop.run_until_complete(run())
    except RuntimeError:
        asyncio.run(run())
