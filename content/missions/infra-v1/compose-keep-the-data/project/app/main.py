"""The ingest API: pulls order batches from the shops and writes them to Postgres."""
import os

from fastapi import FastAPI

app = FastAPI(title="ingest-api")
DATABASE_URL = os.environ["DATABASE_URL"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ingest/run")
def run_ingest() -> dict:
    """Pulls the pending batch (250 orders) and inserts it into the orders table."""
    ...


@app.get("/stats")
def stats() -> dict:
    """How many orders the database holds."""
    ...
