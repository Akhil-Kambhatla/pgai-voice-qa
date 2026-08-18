"""FastAPI server: places calls, serves TeXML, and hosts the media-stream websocket.

Pipecat and the bot module are imported at module load time on purpose: importing
them lazily inside the websocket handler delays the handshake long enough that
Telnyx closes the stream and the call fails.
"""

import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, Response

from src import call_counter, config, store, telnyx_client
from src.bot import run_bot  # noqa: F401 — must load pipecat at startup, see module docstring

app = FastAPI()


def _call_record_path(call_id: str) -> str:
    return os.path.join(config.CALLS_DIR, call_id, "call.json")


@app.post("/start")
async def start_call(request: Request) -> JSONResponse:
    data = await request.json()
    phone_number = data.get("phone_number")
    scenario_id = data.get("scenario_id")
    if not phone_number or not scenario_id:
        raise HTTPException(status_code=400, detail="Need 'phone_number' and 'scenario_id'")
    try:
        scenario = store.load_scenario(scenario_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No scenario file for {scenario_id}")

    call_id = call_counter.reserve_call_slot()
    placed_at = datetime.now(timezone.utc)
    result = await telnyx_client.place_call(
        phone_number, body={"scenario_id": scenario_id, "call_id": call_id}
    )

    record = {
        "call_id": call_id,
        "scenario_id": scenario_id,
        "axes": scenario.get("axes"),
        "identity": scenario.get("identity"),
        "telnyx_sid": result.get("sid"),
        "to": phone_number,
        "from": config.TELNYX_PHONE_NUMBER,
        "placed_at": placed_at.isoformat(),
        "status_events": [],
    }
    os.makedirs(os.path.dirname(_call_record_path(call_id)), exist_ok=True)
    with open(_call_record_path(call_id), "w") as f:
        json.dump(record, f, indent=2)

    return JSONResponse({"call_id": call_id, "placed_at": record["placed_at"]})


@app.post("/answer")
async def answer(request: Request) -> Response:
    ws_url = f"{config.PUBLIC_WS_URL}/ws"
    body = request.query_params.get("body")
    if body:
        ws_url = f"{ws_url}?body={urllib.parse.quote(body, safe='')}"
    texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" bidirectionalMode="rtp"></Stream>
    </Connect>
    <Pause length="40"/>
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
    telnyx_sid = form.get("CallSid")

    record = next(
        (r for r in store.list_call_records() if r.get("telnyx_sid") == telnyx_sid), None
    )
    if record:
        record.setdefault("status_events", []).append(form)
        with open(_call_record_path(record["call_id"]), "w") as f:
            json.dump(record, f, indent=2)
    else:
        print(f"Status callback for unknown call {telnyx_sid}: {form.get('CallStatus')}")
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    os.makedirs(config.CALLS_DIR, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=7860)
