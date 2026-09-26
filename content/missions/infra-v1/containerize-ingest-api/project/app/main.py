"""The ingest API: receives order batches from the shops and writes them to Postgres."""
import os

from fastapi import FastAPI

app = FastAPI(title="ingest-api")
DATABASE_URL = os.environ["DATABASE_URL"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"service": "ingest-api"}
