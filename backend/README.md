# FastAPI backend

Create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, and set `DATABASE_URL` to the Supabase PostgreSQL connection URI (use the Session pooler on IPv4-only networks). The backend requires PostgreSQL and uses psycopg 3 with SSL. Run `uvicorn app.main:app --reload`. Tables are created on startup for prototype use. `python seed.py` creates three days of sample measurements. Keep database credentials server-side. For production, apply managed schema migrations before startup.

The API accepts sensor data at `POST /api/readings`, serves REST resources under `/api`, and broadcasts `reading.created` and `alert.created` JSON messages over `/ws`. Readings must include `device_id`, `ph`, `tds`, `turbidity`, and `temperature`; timestamps are UTC ISO-8601. Use `GET /docs` for the interactive API schema.
