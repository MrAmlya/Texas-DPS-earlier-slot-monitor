"""
Texas DPS scheduler client — mirrors the public scheduler API usage pattern
from the reference script. Run the web app locally only; credentials are sensitive.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import requests

# Production SPA (public.txdpsscheduler.com) uses apptapi. publicapi often has
# no public DNS (NameResolutionError on many networks).
# Override: export DPS_API_BASE="https://apptapi.txdpsscheduler.com/api"
BASE_URL = os.environ.get(
    "DPS_API_BASE", "https://apptapi.txdpsscheduler.com/api"
).rstrip("/")

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _site_origin(cfg: BookerConfig) -> tuple[str, str]:
    """Origin/Referer must match where you copied the session token from."""
    if (cfg.origin_host or "public").lower() == "www":
        o = "https://www.txdpsscheduler.com"
        return o, f"{o}/"
    o = "https://public.txdpsscheduler.com"
    return o, f"{o}/"


def api_headers(cfg: BookerConfig) -> dict[str, str]:
    """Headers aligned with official scheduler + session token."""
    origin, referer = _site_origin(cfg)
    h = {
        **DEFAULT_HEADERS,
        "Origin": origin,
        "Referer": referer,
    }
    h["IsMFAEnabled"] = "N"
    tok = (cfg.authorization_token or "").strip()
    if tok:
        h["Authorization"] = tok
    return h


@dataclass
class BookerConfig:
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""  # MM/DD/YYYY
    last4ssn: str = ""
    zipcode: str = ""
    type_id: int = 71
    distance: float = 10.0
    check_interval: int = 60
    # Paste full value from DevTools → Network → apptapi request → Authorization header
    authorization_token: str = ""
    # "public" = public.txdpsscheduler.com, "www" = www.txdpsscheduler.com (match token source)
    origin_host: str = "public"
    stop_after_reschedule: bool = False
    allow_today_booking: bool = False


@dataclass
class BookerState:
    running: bool = False
    response_id: Optional[str] = None
    cur_appointment_date: Optional[datetime] = None
    has_existing_appointment: bool = False
    current_appointment_raw: Optional[str] = None
    current_appointment_display: Optional[str] = None
    current_location_name: Optional[str] = None
    latest_found_slot_raw: Optional[str] = None
    latest_found_slot_display: Optional[str] = None
    latest_found_location_name: Optional[str] = None
    last_rescheduled_slot_raw: Optional[str] = None
    last_rescheduled_slot_display: Optional[str] = None
    last_rescheduled_location_name: Optional[str] = None
    rescheduled: bool = False
    lookup_count: int = 0
    logs: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        with self._lock:
            self.logs.append(line)
            if len(self.logs) > 500:
                self.logs = self.logs[-400:]

    def snapshot_logs(self) -> list[str]:
        with self._lock:
            return list(self.logs)

    def clear_logs(self) -> None:
        with self._lock:
            self.logs.clear()


class DPSBooker:
    def __init__(self, state: BookerState):
        self.state = state

    def login(self, cfg: BookerConfig) -> bool:
        payload = {
            "DateOfBirth": cfg.date_of_birth,
            "FirstName": cfg.first_name,
            "LastName": cfg.last_name,
            "LastFourDigitsSsn": cfg.last4ssn,
            "CardNumber": "",
        }
        self.state.log("Logging in…")
        try:
            res = requests.post(
                f"{BASE_URL}/Eligibility",
                json=payload,
                headers=api_headers(cfg),
                timeout=60,
            )
            res.raise_for_status()
            data = res.json()
            if not data or not isinstance(data, list) or "ResponseId" not in data[0]:
                self.state.log(f"Login failed: unexpected response: {data!r}")
                return False
            self.state.response_id = data[0]["ResponseId"]
            self.state.log(f"Login succeeded (ResponseId={self.state.response_id})…")

            res = requests.post(
                f"{BASE_URL}/Booking",
                json=payload,
                headers=api_headers(cfg),
                timeout=60,
            )
            res.raise_for_status()
            appointments = res.json()
            self.state.cur_appointment_date = self._default_future_appointment_date()
            if not appointments:
                self.state.log("No existing appointment found.")
                self.state.has_existing_appointment = False
                self.state.current_appointment_raw = None
                self.state.current_appointment_display = None
                self.state.current_location_name = None
            else:
                self._set_current_appointment(appointments[0])
            return True
        except (requests.RequestException, ValueError, TypeError) as e:
            self.state.log(f"Login failed: {e}")
            if isinstance(e, requests.RequestException):
                resp = e.response
                if resp is not None:
                    if resp.status_code == 401:
                        if not (cfg.authorization_token or "").strip():
                            self.state.log(
                                "401: No active session token. In the app click "
                                "“Connect DPS session”, complete captcha/login in the opened browser, "
                                "then test again. Manual token paste is optional fallback only."
                            )
                        else:
                            self.state.log(
                                "401: Session token rejected or expired. Re-run “Connect DPS session” "
                                "to capture a fresh token (manual paste is fallback)."
                            )
                    try:
                        self.state.log(resp.text[:500])
                    except Exception:
                        pass
            return False

    @staticmethod
    def _default_future_appointment_date() -> datetime:
        """Return a safe fallback date roughly one year out, including leap-day safety."""
        cur = datetime.now()
        try:
            return datetime(cur.year + 1, cur.month, cur.day)
        except ValueError:
            # Handles Feb 29 -> use Feb 28 in non-leap target years.
            return datetime(cur.year + 1, cur.month, 28)

    @staticmethod
    def _format_slot(slot_value: str) -> str:
        parsed = DPSBooker._parse_slot_datetime(slot_value)
        if parsed is None:
            return slot_value
        return parsed.strftime("%Y-%m-%d %I:%M %p")

    @staticmethod
    def _parse_slot_datetime(slot_value: str) -> Optional[datetime]:
        candidate = (slot_value or "").strip()
        if not candidate:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(candidate[:26], fmt)
            except ValueError:
                continue
        return None

    def _set_current_appointment(self, booking: dict[str, Any]) -> None:
        raw = str(booking.get("BookingDateTime", "")).strip()
        display = self._format_slot(raw) if raw else None
        location_name = (
            booking.get("SiteName")
            or booking.get("LocationName")
            or booking.get("Name")
            or None
        )
        self.state.has_existing_appointment = bool(raw)
        self.state.current_appointment_raw = raw or None
        self.state.current_appointment_display = display
        self.state.current_location_name = str(location_name).strip() if location_name else None
        if raw:
            self.state.log(f"Existing appointment: {raw}")
            parsed = self._parse_slot_datetime(raw)
            if parsed is not None:
                self.state.cur_appointment_date = datetime(parsed.year, parsed.month, parsed.day)

    def _refresh_booking(self, cfg: BookerConfig) -> None:
        payload = {
            "DateOfBirth": cfg.date_of_birth,
            "FirstName": cfg.first_name,
            "LastName": cfg.last_name,
            "LastFourDigitsSsn": cfg.last4ssn,
            "CardNumber": "",
        }
        self.state.log("Fetching current appointment…")
        res = requests.post(
            f"{BASE_URL}/Booking",
            json=payload,
            headers=api_headers(cfg),
            timeout=60,
        )
        res.raise_for_status()
        appointments = res.json()
        if not appointments:
            self.state.log("No existing appointment found.")
            self.state.has_existing_appointment = False
            self.state.current_appointment_raw = None
            self.state.current_appointment_display = None
            self.state.current_location_name = None
        else:
            self._set_current_appointment(appointments[0])

    def check_availability(self, cfg: BookerConfig) -> None:
        if self.state.response_id is None:
            self.state.log("Not logged in; skip check.")
            return

        data = {
            "TypeId": cfg.type_id,
            "ZipCode": cfg.zipcode,
            "CityName": "",
            "PreferredDay": 0,
        }
        credential = {
            "FirstName": cfg.first_name,
            "LastName": cfg.last_name,
            "DateOfBirth": cfg.date_of_birth,
            "Last4Ssn": cfg.last4ssn,
        }

        res = requests.post(
            f"{BASE_URL}/AvailableLocation",
            json=data,
            headers=api_headers(cfg),
            timeout=60,
        )
        res.raise_for_status()
        locations = res.json()
        if not isinstance(locations, list):
            self.state.log("[Error] failed to request available locations.")
            return

        locations.sort(
            key=lambda loc: datetime.strptime(loc["NextAvailableDate"], "%m/%d/%Y")
        )
        locations = [loc for loc in locations if loc["Distance"] < cfg.distance]

        if self.state.rescheduled:
            try:
                self._refresh_booking(cfg)
            except requests.RequestException as e:
                self.state.log(f"Refresh booking failed: {e}")

        cur_date = self.state.cur_appointment_date
        if cur_date is None:
            self.state.log("No current appointment date set.")
            return
        current_appointment_dt = self._parse_slot_datetime(
            self.state.current_appointment_raw or ""
        )
        if current_appointment_dt is None:
            current_appointment_dt = cur_date

        today = datetime.now().date()
        best_location: Optional[dict[str, Any]] = None
        best_slot: Optional[dict[str, Any]] = None
        best_slot_dt: Optional[datetime] = None

        for location in locations:
            try:
                next_available = datetime.strptime(
                    location["NextAvailableDate"], "%m/%d/%Y"
                )
            except (KeyError, ValueError, TypeError):
                continue

            if next_available.date() > current_appointment_dt.date():
                continue

            availability = location.get("Availability")
            if not availability:
                self.state.log("Fetching availability…")
                dates_body: dict[str, Any] = {
                    "TypeId": cfg.type_id,
                    "LocationId": location["Id"],
                    "SameDay": False,
                    "StartDate": None,
                    "PreferredDay": 0,
                }
                res = requests.post(
                    f"{BASE_URL}/AvailableLocationDates",
                    json=dates_body,
                    headers=api_headers(cfg),
                    timeout=60,
                )
                res.raise_for_status()
                availability = res.json()

            if not availability or not availability.get("LocationAvailabilityDates"):
                continue

            location_dates = availability.get("LocationAvailabilityDates", [])
            for date_block in location_dates:
                slots = date_block.get("AvailableTimeSlots", [])
                for slot in slots:
                    slot_start = str(slot.get("StartDateTime", "")).strip()
                    slot_dt = self._parse_slot_datetime(slot_start)
                    if slot_dt is None:
                        continue
                    if not cfg.allow_today_booking and slot_dt.date() == today:
                        continue
                    if slot_dt >= current_appointment_dt:
                        continue
                    if best_slot_dt is None or slot_dt < best_slot_dt:
                        best_slot_dt = slot_dt
                        best_location = location
                        best_slot = slot

        if best_location is None or best_slot is None or best_slot_dt is None:
            self.state.log("No earlier slot found this round.")
            return

        scheduled_time = str(best_slot["StartDateTime"])
        selected_slot_id = best_slot["SlotId"]
        location_name = str(best_location.get("Name", "Unknown location"))
        location_distance = best_location.get("Distance")
        self.state.log(
            f"Earliest slot candidate at {location_name} ({location_distance} mi) "
            f"on {best_slot_dt.strftime('%m/%d/%Y %I:%M %p')}"
        )
        formatted_slot = self._format_slot(scheduled_time)
        self.state.latest_found_slot_raw = scheduled_time
        self.state.latest_found_slot_display = formatted_slot
        self.state.latest_found_location_name = location_name
        self.state.log(f"Holding slot {selected_slot_id} at {scheduled_time}…")

        hold_res = requests.post(
            f"{BASE_URL}/HoldSlot",
            json={**credential, "SlotId": selected_slot_id},
            headers=api_headers(cfg),
            timeout=60,
        )
        hold_res.raise_for_status()
        hold_json = hold_res.json()
        held = hold_json.get("SlotHeldSuccessfully", False)
        self.state.log(f"Hold status: {held}")

        if not held:
            self.state.log("Hold slot failed.")
            return

        self.state.log("Rescheduling…")
        payload = {
            **credential,
            "Email": cfg.email,
            "ServiceTypeId": cfg.type_id,
            "BookingDateTime": scheduled_time,
            "BookingDuration": best_slot["Duration"],
            "SpanishLanguage": "N",
            "SiteId": best_location["Id"],
            "ResponseId": self.state.response_id,
            "CardNumber": "",
            "CellPhone": "",
            "HomePhone": "",
        }
        try:
            res = requests.post(
                f"{BASE_URL}/RescheduleBooking",
                json=payload,
                headers=api_headers(cfg),
                timeout=60,
            )
            res.raise_for_status()
            self.state.rescheduled = True
            self.state.last_rescheduled_slot_raw = scheduled_time
            self.state.last_rescheduled_slot_display = formatted_slot
            self.state.last_rescheduled_location_name = location_name
            self.state.has_existing_appointment = True
            self.state.current_appointment_raw = scheduled_time
            self.state.current_appointment_display = formatted_slot
            self.state.current_location_name = location_name
            parsed_slot = self._parse_slot_datetime(scheduled_time)
            if parsed_slot is not None:
                self.state.cur_appointment_date = datetime(
                    parsed_slot.year,
                    parsed_slot.month,
                    parsed_slot.day,
                )
            self.state.log("Reschedule succeeded — check your email.")
            return
        except requests.RequestException as e:
            self.state.log(f"Reschedule failed: {e}")
            if getattr(e, "response", None) is not None and e.response is not None:
                try:
                    self.state.log(e.response.text[:500])
                except Exception:
                    pass

    def run_loop(
        self,
        cfg: BookerConfig,
        should_stop: Callable[[], bool],
    ) -> None:
        self.state.rescheduled = False
        try:
            if not self.login(cfg):
                return

            while not should_stop():
                self.state.lookup_count += 1
                self.state.log(f"Check #{self.state.lookup_count}")
                try:
                    self.check_availability(cfg)
                except requests.RequestException as e:
                    self.state.log(f"Request error: {e}")
                except (KeyError, ValueError, IndexError, TypeError) as e:
                    self.state.log(f"Parse/error: {e}")
                if cfg.stop_after_reschedule and self.state.rescheduled:
                    self.state.log("Stop after reschedule: done.")
                    break
                if should_stop():
                    break
                self.state.log(f"Sleeping {cfg.check_interval}s…")
                for _ in range(cfg.check_interval):
                    if should_stop():
                        break
                    time.sleep(1)
        except Exception as e:
            self.state.log(f"Worker stopped unexpectedly: {e}")
        finally:
            self.state.running = False
            self.state.log("Stopped.")
