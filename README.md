# Smart Water Quality Monitoring and Alert System

A full-stack IoT monitoring prototype for pH, total dissolved solids (TDS), turbidity, and temperature. The dashboard is designed for engineering demonstrations and preliminary observation. Its configurable thresholds are project monitoring limits, not certified drinking-water standards.

## Architecture

```text
ESP32 / Wokwi → HTTP(S) → FastAPI → SQLAlchemy → PostgreSQL (Supabase)
                                      ↓ REST + WebSocket
                                  React dashboard
```

The browser never connects to Supabase or PostgreSQL. All application reads and writes pass through FastAPI. Supabase PostgreSQL is the only supported database.

## Stack and layout

- Frontend: React, Vite, TypeScript, React Router, Recharts, Lucide icons
- Backend: FastAPI, Pydantic, SQLAlchemy, Uvicorn
- `src/`: dashboard pages, reusable UI, API client and types
- `backend/app/main.py`: API, ORM models, alert evaluation and WebSocket hub
- `backend/seed.py`: sample telemetry for development

## Local setup

1. Install Node.js 20+ and Python 3.11+.
2. In the repository root, run `npm install`, copy `.env.example` to `.env`, then run `npm run dev`.
3. In `backend`, create/activate a virtual environment, run `pip install -r requirements.txt`, copy `.env.example` to `.env`, then run `uvicorn app.main:app --reload`.
4. Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`.
5. To seed historical readings, run `python seed.py` from `backend`.

For a frontend-only demo without an active backend, set `VITE_ENABLE_MOCK_DATA=true`. This generates slowly varying readings in one shared data hook and produces a populated dashboard. The normal integration flow remains ESP32 → FastAPI → database → React.

## Supabase PostgreSQL

Create a Supabase project and copy its PostgreSQL connection string into `backend/.env` as `DATABASE_URL`. Use the pooled connection option when appropriate for your deployment, and keep the password exclusively in the backend environment. Tables are created automatically on startup for prototype development; production deployments should use versioned migrations and managed secrets.

## Configuration

Frontend `.env`:

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | FastAPI base URL, default `http://localhost:8000` |
| `VITE_ENABLE_MOCK_DATA` | Enable local generated demo values (`true`/`false`) |

Backend `backend/.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase PostgreSQL connection URL (Session pooler for IPv4-only networks) |
| `CORS_ORIGINS` | Comma-separated allowed browser origins |
| `APP_ENV` | Environment name |
| `LOG_LEVEL` | Python log level |

## API overview

- `GET /api/health`, `GET /api/dashboard`
- `GET|POST /api/readings`, `GET /api/readings/export.csv`
- `GET /api/analytics?parameter=ph&range=24H`
- `GET /api/alerts`, `POST /api/alerts/{id}/acknowledge`, `POST /api/alerts/{id}/resolve`
- `GET|POST /api/devices`
- `GET|PUT /api/thresholds`
- `WS /ws`

ESP32 JSON example:

```json
{"device_id":"WQM-001","ph":7.12,"tds":245,"turbidity":2.8,"temperature":26.4,"created_at":"2026-09-27T10:30:00Z"}
```

WebSocket events use JSON objects such as `{"type":"reading.created","reading":{...}}` and `{"type":"alert.created","alert":{...}}`.

## Data model

`devices` stores identity, connectivity, firmware, and sampling interval. `readings` stores timestamped sensor values, indexed by device and time. `alerts` stores threshold events and acknowledgement/resolution state. `thresholds` stores the current configurable project limits. Foreign keys associate readings with devices.

## Build

Run `npm run build` for a production frontend bundle. Start the API with `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Configure HTTPS termination, CORS origins, database secrets, and a migration step in a production deployment. The API currently has no user authentication; expose it only in a trusted demonstration network until authentication and device authorization are added.
