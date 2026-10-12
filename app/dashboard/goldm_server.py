"""Local-only GOLDM dashboard server, isolated from NIFTY."""
import asyncio
import threading
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from app.dashboard.goldm_publisher import get_payload

app = FastAPI(title="GOLDM Dashboard", docs_url=None, redoc_url=None)
HTML = Path(__file__).resolve().parents[2] / "dashboard" / "goldm.html"

@app.get("/")
def home():
    return FileResponse(HTML) if HTML.exists() else JSONResponse({"error": f"Missing dashboard file: {HTML}"}, status_code=500)

@app.get("/health")
def health():
    return {"status": "ok", "instrument": "GOLDM", "mode": "monitoring-only"}

@app.websocket("/ws")
async def stream(websocket: WebSocket):
    await websocket.accept()
    cursor = 0
    try:
        while True:
            payload = get_payload(cursor)
            await websocket.send_json(payload)
            cursor = payload["latest_event_id"]
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        pass

def start_dashboard(host="127.0.0.1", port=8766):
    import uvicorn
    threading.Thread(target=lambda: uvicorn.run(app, host=host, port=port, log_level="warning"),
                     name="goldm-dashboard", daemon=True).start()
