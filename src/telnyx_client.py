"""Telnyx TeXML REST client: place calls, find and download call recordings.

Recording note (verified against the live API 2026-08-17): recordings on this
account are produced at the trunk level (source "Trunking", channels=2, stereo
mp3) with `call_sid` null and no phone numbers in the metadata, so a recording
cannot be matched to a call by ID. `find_recording` therefore matches by time:
the earliest completed recording whose start_time is at or after the moment
the call was placed, which is necessarily that call's own recording.
"""

import asyncio
import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp

from src import config

TEXML_BASE = f"https://api.telnyx.com/v2/texml/Accounts/{config.TELNYX_ACCOUNT_SID}"
_HEADERS = {"Authorization": f"Bearer {config.TELNYX_API_KEY}"}


async def place_call(to_number: str, body: dict | None = None) -> dict:
    """Place an outbound TeXML call. Returns the Telnyx response body (includes `sid`)."""
    answer_url = f"{config.PUBLIC_BASE_URL}/answer"
    if body:
        encoded = urllib.parse.quote(base64.b64encode(json.dumps(body).encode()).decode(), safe="")
        answer_url = f"{answer_url}?body={encoded}"

    data = {
        "ApplicationSid": config.TELNYX_APPLICATION_SID,
        "To": to_number,
        "From": config.TELNYX_PHONE_NUMBER,
        "Url": answer_url,
        "StatusCallback": f"{config.PUBLIC_BASE_URL}/status",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TEXML_BASE}/Calls",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json=data,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Telnyx call creation failed ({resp.status}): {await resp.text()}")
            return await resp.json()


def _parse_telnyx_time(value: str) -> datetime:
    # Telnyx TeXML timestamps look like "Mon, 17 Aug 2026 19:40:05 +0000"
    return parsedate_to_datetime(value)


async def find_recording(
    call_session_id: str,
    placed_at: datetime,
    timeout_seconds: int = 180,
) -> dict:
    """Poll the recordings list until a recording for this call appears.

    Matches by start time (see module docstring); `call_session_id` is accepted for
    logging/interface stability but cannot be used as a filter because recording
    metadata carries `call_sid: null` on this account.
    """
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=timezone.utc)
    # 30s slack for clock skew between our clock and Telnyx's.
    cutoff = placed_at - timedelta(seconds=30)

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{TEXML_BASE}/Recordings.json",
                headers=_HEADERS,
                params={"PageSize": 20},
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Telnyx recordings list failed ({resp.status}): {await resp.text()}"
                    )
                body = await resp.json()

            candidates = [
                r
                for r in body.get("recordings", [])
                if r.get("status") == "completed"
                and r.get("start_time")
                and _parse_telnyx_time(r["start_time"]) >= cutoff
            ]
            if candidates:
                candidates.sort(key=lambda r: _parse_telnyx_time(r["start_time"]))
                return candidates[0]

            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(
                    f"No recording found for call {call_session_id} within {timeout_seconds}s "
                    f"(looked for completed recordings starting after {cutoff.isoformat()})"
                )
            await asyncio.sleep(10)


async def download_recording(url: str, dest_path: str) -> str:
    """Download the recording mp3 to dest_path. The media_url is pre-signed (no auth)."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Recording download failed ({resp.status})")
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)
    return dest_path
