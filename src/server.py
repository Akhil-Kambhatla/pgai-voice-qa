"""FastAPI server: places calls, serves TeXML, and hosts the media-stream websocket.

Pipecat and the bot module are imported at module load time on purpose: importing
them lazily inside the websocket handler delays the handshake long enough that
Telnyx closes the stream and the call fails.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, Response

from src import config, telnyx_client
from src.bot import run_bot  # noqa: F401 — must load pipecat at startup, see module docstring

app = FastAPI()


def _call_dir(call_id: str) -> str:
    return os.path.join(config.CALLS_DIR, call_id)


def _call_record_path(call_id: str) -> str:
    return os.path.join(_call_dir(call_id), "call.json")


@app.post("/start")
async def start_call(request: Request) -> JSONResponse:
    data = await request.json()
    phone_number = data.get("phone_number")
    if not phone_number:
        raise HTTPException(status_code=400, detail="Missing 'phone_number' in request body")

    placed_at = datetime.now(timezone.utc)
    result = await telnyx_client.place_call(phone_number)

    call_id = result.get("sid") or result.get("call_control_id") or "unknown"
    record = {
        "call_id": call_id,
        "to": phone_number,
        "from": config.TELNYX_PHONE_NUMBER,
        "placed_at": placed_at.isoformat(),
        "telnyx_response": result,
        "status_events": [],
    }
    os.makedirs(_call_dir(call_id), exist_ok=True)
    with open(_call_record_path(call_id), "w") as f:
        json.dump(record, f, indent=2)

    return JSONResponse({"call_id": call_id, "placed_at": record["placed_at"]})


@app.post("/answer")
async def answer(request: Request) -> Response:
    texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{config.PUBLIC_WS_URL}/ws" bidirectionalMode="rtp"></Stream>
    </Connect>
</Response>"""
    return Response(content=texml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        await run_bot(websocket)
    except Exception as e:
        print(f"Error in websocket handler: {e}")


@app.post("/status")
async def status_callback(request: Request) -> JSONResponse:
    form = dict(await request.form())
    form["received_at"] = datetime.now(timezone.utc).isoformat()
    call_id = form.get("CallSid") or form.get("CallSidLegacy")

    record_path = _call_record_path(call_id) if call_id else None
    if record_path and os.path.exists(record_path):
        with open(record_path) as f:
            record = json.load(f)
        record.setdefault("status_events", []).append(form)
        with open(record_path, "w") as f:
            json.dump(record, f, indent=2)
    else:
        print(f"Status callback for unknown call {call_id}: {form.get('CallStatus')}")
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    os.makedirs(config.CALLS_DIR, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=7860)
