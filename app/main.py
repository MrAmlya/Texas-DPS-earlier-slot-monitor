import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from dps_client import BookerConfig, BookerState, DPSBooker

app = FastAPI(title="DPS Slot Booker", version="1.0.0")

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC = ROOT_DIR / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")


class SettingsBody(BaseModel):
    email: str = Field(..., min_length=3)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    date_of_birth: str = Field(..., description="MM/DD/YYYY")
    last4ssn: str = Field(..., min_length=4, max_length=4)
    zipcode: str = Field(..., min_length=5)
    type_id: int = 71
    distance: float = 10.0
    check_interval: int = Field(60, ge=15, le=3600)
    authorization_token: str = Field(default="", max_length=32000)
    clear_session_token: bool = False
    origin_host: Literal["public", "www"] = "public"
    stop_after_reschedule: bool = False

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: str) -> str:
        v = value.strip()
        try:
            datetime.strptime(v, "%m/%d/%Y")
        except ValueError as e:
            raise ValueError("date_of_birth must be a valid date in MM/DD/YYYY format") from e
        return v

    @field_validator("last4ssn")
    @classmethod
    def validate_last4ssn(cls, value: str) -> str:
        v = value.strip()
        if len(v) != 4 or not v.isdigit():
            raise ValueError("last4ssn must be exactly 4 digits")
        return v

    @field_validator("zipcode")
    @classmethod
    def validate_zipcode(cls, value: str) -> str:
        v = value.strip()
        if len(v) != 5 or not v.isdigit():
            raise ValueError("zipcode must be exactly 5 digits")
        return v


state = BookerState()
_worker: Optional[threading.Thread] = None
_stop_flag = threading.Event()
_config: Optional[BookerConfig] = None
_config_lock = threading.Lock()


def _should_stop() -> bool:
    return _stop_flag.is_set()


def _worker_target(cfg: BookerConfig) -> None:
    booker = DPSBooker(state)
    booker.run_loop(cfg, _should_stop)


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "static/index.html missing")
    return FileResponse(index_path)


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    with _config_lock:
        configured = _config is not None
        has_session_token = bool(_config.authorization_token) if _config else False
    return {
        "running": state.running,
        "configured": configured,
        "has_session_token": has_session_token,
        "rescheduled": state.rescheduled,
        "lookup_count": state.lookup_count,
        "response_id_set": state.response_id is not None,
        "appointment": {
            "has_existing": state.has_existing_appointment,
            "current_datetime": state.current_appointment_display,
            "current_location": state.current_location_name,
            "latest_found_datetime": state.latest_found_slot_display,
            "latest_found_location": state.latest_found_location_name,
            "last_rescheduled_datetime": state.last_rescheduled_slot_display,
            "last_rescheduled_location": state.last_rescheduled_location_name,
        },
        "logs": state.snapshot_logs(),
    }


@app.post("/api/logs/clear")
def api_clear_logs() -> dict[str, str]:
    state.clear_logs()
    return {"ok": "cleared"}


@app.post("/api/settings")
def api_settings(body: SettingsBody) -> dict[str, str]:
    global _config
    if state.running:
        raise HTTPException(400, "Stop the monitor before changing settings.")
    with _config_lock:
        prev = _config
        if body.clear_session_token:
            token = ""
        elif body.authorization_token.strip():
            token = body.authorization_token.strip()
        elif prev is not None and prev.authorization_token:
            token = prev.authorization_token
        else:
            token = ""
        _config = BookerConfig(
            email=body.email.strip(),
            first_name=body.first_name.strip(),
            last_name=body.last_name.strip(),
            date_of_birth=body.date_of_birth.strip(),
            last4ssn=body.last4ssn.strip(),
            zipcode=body.zipcode.strip(),
            type_id=body.type_id,
            distance=body.distance,
            check_interval=body.check_interval,
            authorization_token=token,
            origin_host=body.origin_host,
            stop_after_reschedule=body.stop_after_reschedule,
        )
    return {"ok": "saved"}


@app.get("/api/settings")
def api_get_settings() -> dict[str, Any]:
    with _config_lock:
        if _config is None:
            return {"configured": False}
        c = _config
    return {
        "configured": True,
        "email": c.email,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "date_of_birth": c.date_of_birth,
        "last4ssn": "****",
        "zipcode": c.zipcode,
        "type_id": c.type_id,
        "distance": c.distance,
        "check_interval": c.check_interval,
        "has_session_token": bool(c.authorization_token),
        "origin_host": getattr(c, "origin_host", "public") or "public",
        "stop_after_reschedule": getattr(c, "stop_after_reschedule", False),
    }


@app.post("/api/test-connection")
def api_test_connection() -> dict[str, Any]:
    """Validate token + identity with a single Eligibility/Booking round trip (no polling)."""
    if state.running:
        raise HTTPException(400, "Stop monitoring before testing.")
    with _config_lock:
        if _config is None:
            raise HTTPException(400, "Save settings first.")
        cfg = _config
    test_state = BookerState()
    booker = DPSBooker(test_state)
    ok = booker.login(cfg)
    return {
        "ok": ok,
        "response_id_set": test_state.response_id is not None,
        "logs": test_state.snapshot_logs(),
    }


@app.post("/api/start")
def api_start() -> dict[str, str]:
    global _worker
    with _config_lock:
        if _config is None:
            raise HTTPException(400, "Save settings first.")
        cfg = _config
    if state.running:
        raise HTTPException(400, "Already running.")
    _stop_flag.clear()
    state.running = True
    state.clear_logs()
    state.lookup_count = 0
    state.response_id = None
    state.cur_appointment_date = None
    state.has_existing_appointment = False
    state.current_appointment_raw = None
    state.current_appointment_display = None
    state.current_location_name = None
    state.latest_found_slot_raw = None
    state.latest_found_slot_display = None
    state.latest_found_location_name = None
    state.last_rescheduled_slot_raw = None
    state.last_rescheduled_slot_display = None
    state.last_rescheduled_location_name = None
    state.rescheduled = False

    t = threading.Thread(target=_worker_target, args=(cfg,), daemon=True)
    _worker = t
    t.start()
    return {"ok": "started"}


@app.post("/api/stop")
def api_stop() -> dict[str, str]:
    _stop_flag.set()
    return {"ok": "stopping"}
