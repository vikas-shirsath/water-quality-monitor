# FastAPI backend

Create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, then run `uvicorn app.main:app --reload`. The development default is SQLite; set `DATABASE_URL` to the Supabase PostgreSQL connection string for hosted PostgreSQL. Tables are created on startup for prototype use. `python seed.py` creates three days of sample measurements. For production, apply managed schema migrations before startup and keep database credentials server-side.

The API accepts sensor data at `POST /api/readings`, serves REST resources under `/api`, and broadcasts `reading.created` and `alert.created` JSON messages over `/ws`. Readings must include `device_id`, `ph`, `tds`, `turbidity`, and `temperature`; timestamps are UTC ISO-8601. Use `GET /docs` for the interactive API schema.
