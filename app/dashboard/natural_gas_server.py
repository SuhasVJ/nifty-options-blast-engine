"""Local-only Natural Gas signal dashboard server."""
import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from app.dashboard.natural_gas_publisher import get_payload

app = FastAPI(title="MCX Natural Gas Signals", docs_url=None, redoc_url=None)
HTML = Path(__file__).resolve().parents[2] / "dashboard" / "natural_gas.html"


@app.get("/")
def home():
    return FileResponse(HTML) if HTML.exists() else JSONResponse({"error": f"Missing dashboard file: {HTML}"}, status_code=500)


@app.get("/health")
def health():
    payload = get_payload()["natural_gas"]
    return {"status": payload["status"], "instrument": payload["instrument"], "mode": "signals-only"}


@app.get("/api/state")
def state():
    return get_payload()


@app.websocket("/ws")
async def stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(get_payload())
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass


def start_dashboard(host="127.0.0.1", port=8767):
    import uvicorn
    threading.Thread(
        target=lambda: uvicorn.run(app, host=host, port=port, log_level="warning"),
        name="natural-gas-dashboard", daemon=True
    ).start()
