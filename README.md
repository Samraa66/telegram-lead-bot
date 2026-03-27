# Telegram CRM Monorepo

This repository is now organized into clear top-level folders:

- `backend/` — FastAPI Telegram bot backend (webhook, mirroring, CRM, DB)
- `frontend/` — frontend UI app (to be added/wired next)

## Backend quick start

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Main backend docs are in `backend/README.md`.

## Frontend

Place your frontend files under `frontend/`.
Once you share them, we will wire them to backend APIs in `backend/app/main.py`.
