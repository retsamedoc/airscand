## ROADMAP

### Near-term (Phase 1–2 focus)

- Keep the current **single-process** architecture: one asyncio loop running
  - UDP WS-Discovery listener task
  - HTTP server task (currently `aiohttp`)
- Goal: validate that the printer discovers the host and reaches the HTTP endpoint(s) reliably.

### Re-evaluate after Phase 1–2: FastAPI/uvicorn option

If the HTTP surface grows (more SOAP actions, validation, middleware, debug tooling), consider switching the HTTP server from `aiohttp` to **FastAPI + uvicorn**, while still keeping **one asyncio loop** for discovery + HTTP.

#### Why we didn’t do this in Phase 0

- Discovery is a singleton-ish UDP multicast responder; typical web-server scaling (multi-worker) can cause duplicate responses and confusing behavior.
- uvicorn/gunicorn lifecycle + signals are simplest when they own the process; embedding them increases complexity early.
- Phase 0 goal is “starts cleanly” + observability, not framework choice.

#### Decision constraints (when revisiting)

- If using a process manager (gunicorn), ensure **only one** discovery responder exists.
- Prefer **single-worker** HTTP until discovery is split into a separate service/process.
- Ensure graceful shutdown stops both HTTP and discovery cleanly.

