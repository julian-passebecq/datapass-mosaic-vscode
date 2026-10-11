# sensor-api

A small FastAPI service. Locally it runs with:

    pip install -r requirements.txt
    uvicorn app.main:app --port 8000

It answers `GET /`, `GET /health` and `GET /sensors/<id>` on port 8000. There is no Dockerfile yet.
