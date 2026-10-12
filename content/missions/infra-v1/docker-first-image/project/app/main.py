"""sensor-api: serves the latest reading of each sensor to the dashboards."""
from fastapi import FastAPI

app = FastAPI(title="sensor-api")

LATEST = {
    "greenhouse-1": {"temperature_c": 21.4, "humidity_pct": 63},
    "greenhouse-2": {"temperature_c": 19.8, "humidity_pct": 71},
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"service": "sensor-api", "sensors": len(LATEST)}


@app.get("/sensors/{sensor_id}")
def reading(sensor_id: str) -> dict:
    return LATEST.get(sensor_id, {})
