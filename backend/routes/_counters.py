"""Iter38r-fix9o — Counters & ID generation utilities.
Atomic sequential ID generation via the `counters` collection.
"""
from __future__ import annotations
from datetime import datetime, timezone


async def next_seq(db, key: str) -> int:
    """Atomic counter using find_one_and_update with upsert."""
    r = await db.counters.find_one_and_update(
        {"_id": key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    # Brand-new counters need to be initialised properly
    seq = (r or {}).get("seq")
    if not seq:
        await db.counters.update_one({"_id": key}, {"$set": {"seq": 1}})
        seq = 1
    return int(seq)


async def gen_internal_id(db, prefix: str, year_yy: str | None = None, width: int = 6) -> str:
    """Format: PREFIX-YY-NNNNNN (PFX-25-000123)."""
    yy = year_yy or datetime.now(timezone.utc).strftime("%y")
    key = f"{prefix}-{yy}"
    seq = await next_seq(db, key)
    return f"{prefix}-{yy}-{str(seq).zfill(width)}"
