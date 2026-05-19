# Refactoring server.py — Plan & pattern

`/app/backend/server.py` had grown to ~18 200 lines. The goal of this
refactoring is to extract cohesive, well-bounded pieces into dedicated
modules so the monolith shrinks gradually without breaking production.

## Folder layout

```
/app/backend/
├── server.py             # FastAPI app, supervisor wiring, remaining
│                         # legacy endpoints (decreases over time).
├── routes/               # FastAPI APIRouters grouped by domain.
│   └── __init__.py
├── services/             # Pure business helpers, no FastAPI routing.
│   ├── __init__.py
│   └── alexa.py          # Iter35y — Alexa Voice Monkey notifier.
└── tests/                # Pytest, one file per module ideally.
```

## Pattern used for `services/alexa.py` (Iter35y)

1. The pure helper takes `db` as its first argument (no global imports
   from `server.py` → no circular imports).
2. `server.py` keeps a **thin wrapper** with the same name as before
   (`_alexa_notify`, `_alexa_notify_async`) so every existing call site
   keeps working without edits.
3. The wrapper injects the global `db` from `server.py`.

```python
# services/alexa.py
async def alexa_notify(db, event_type, message): ...

# server.py
from services.alexa import alexa_notify as _alexa_notify_impl

async def _alexa_notify(event_type, message):
    await _alexa_notify_impl(db, event_type, message)
```

This pattern minimises the diff (no need to touch the dozens of call
sites) and keeps the public API of `server.py` stable while moving the
logic out.

## Future modules to extract (P1 backlog)

Priority order — extract the smallest + most isolated first:

1. `services/sms_dispatch.py`        (~200 lines)
2. `services/whatsapp_send.py`       (~300 lines)
3. `routes/welcome_briefing.py`      (~100 lines, recent code)
4. `routes/tickets.py`               (~400 lines)
5. `routes/sms_dashboard.py`         (Iter35z — NEW module)
6. `routes/secrets_vault.py`         (~600 lines, well-bounded)
7. `routes/admin_settings.py`        (the big PUT/GET endpoints)

## Validation checklist after each extraction

- [ ] `python -c "import server"` succeeds (no circular imports).
- [ ] `sudo supervisorctl restart backend` → no error in logs.
- [ ] Existing pytest suite remains green.
- [ ] Run a quick `curl` on the affected endpoint.
