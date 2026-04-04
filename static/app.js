const form = document.getElementById("form-settings");
const btnSave = document.getElementById("btn-save");
const btnTest = document.getElementById("btn-test");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const btnNotify = document.getElementById("btn-notify");
const btnDownloadLog = document.getElementById("btn-download-log");
const logEl = document.getElementById("log");
const btnClearLog = document.getElementById("btn-clear-log");
const msgEl = document.getElementById("settings-msg");
const testResultEl = document.getElementById("test-result");
const statusStrip = document.getElementById("status-strip");
const statusText = document.getElementById("status-text");
const appointmentPanel = document.getElementById("appointment-panel");
const apptCurrent = document.getElementById("appt-current");
const apptCurrentLocation = document.getElementById("appt-current-location");
const apptLatestFound = document.getElementById("appt-latest-found");
const apptLatestLocation = document.getElementById("appt-latest-location");
const apptLastRescheduled = document.getElementById("appt-last-rescheduled");
const apptLastLocation = document.getElementById("appt-last-location");
const rowCurrent = document.getElementById("row-current");
const rowCurrentLocation = document.getElementById("row-current-location");
const rowLatestFound = document.getElementById("row-latest-found");
const rowLatestLocation = document.getElementById("row-latest-location");
const rowLastRescheduled = document.getElementById("row-last-rescheduled");
const rowLastLocation = document.getElementById("row-last-location");

let prevRescheduled = false;
let statusInitialized = false;

function setMsg(text, kind) {
  msgEl.textContent = text || "";
  msgEl.className = "msg" + (kind ? " " + kind : "");
}

function formatDetail(detail) {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .join("; ");
  }
  return String(detail);
}

function setConfiguredUi(configured) {
  btnStart.disabled = !configured;
  btnTest.disabled = !configured;
}

function updateStatusStrip(d) {
  const running = d.running === true;
  const token = d.has_session_token === true;
  const parts = [];
  if (running) {
    parts.push("Monitoring active");
    parts.push(`check #${d.lookup_count ?? 0}`);
  } else {
    parts.push("Idle");
  }
  parts.push(token ? "session token saved" : "no session token yet");
  if (d.rescheduled) parts.push("reschedule succeeded this run");
  statusText.textContent = parts.join(" · ");
  statusStrip.classList.toggle("running", running);
  statusStrip.classList.toggle("ok", d.rescheduled === true);

}

function updateAppointmentDetails(d) {
  if (!appointmentPanel) return;
  const appt = d.appointment || {};
  const hasFetchedDetails = d.response_id_set === true;

  const showCurrent = !!appt.current_datetime;
  const showCurrentLocation = !!appt.current_location;
  const showLatestFound = !!appt.latest_found_datetime;
  const showLatestLocation = !!appt.latest_found_location;
  const showLastRescheduled = !!appt.last_rescheduled_datetime;
  const showLastLocation = !!appt.last_rescheduled_location;

  if (rowCurrent) rowCurrent.hidden = !showCurrent;
  if (rowCurrentLocation) rowCurrentLocation.hidden = !showCurrentLocation;
  if (rowLatestFound) rowLatestFound.hidden = !showLatestFound;
  if (rowLatestLocation) rowLatestLocation.hidden = !showLatestLocation;
  if (rowLastRescheduled) rowLastRescheduled.hidden = !showLastRescheduled;
  if (rowLastLocation) rowLastLocation.hidden = !showLastLocation;

  if (showCurrent && apptCurrent) apptCurrent.textContent = appt.current_datetime;
  if (showCurrentLocation && apptCurrentLocation) {
    apptCurrentLocation.textContent = appt.current_location;
  }
  if (showLatestFound && apptLatestFound) {
    apptLatestFound.textContent = appt.latest_found_datetime;
  }
  if (showLatestLocation && apptLatestLocation) {
    apptLatestLocation.textContent = appt.latest_found_location;
  }
  if (showLastRescheduled && apptLastRescheduled) {
    apptLastRescheduled.textContent = appt.last_rescheduled_datetime;
  }
  if (showLastLocation && apptLastLocation) {
    apptLastLocation.textContent = appt.last_rescheduled_location;
  }

  const hasAnyValue =
    showCurrent ||
    showCurrentLocation ||
    showLatestFound ||
    showLatestLocation ||
    showLastRescheduled ||
    showLastLocation;
  appointmentPanel.hidden = !(hasFetchedDetails && hasAnyValue);
}

async function loadSettings() {
  try {
    const r = await fetch("/api/settings");
    const d = await r.json();
    if (!d.configured) {
      setConfiguredUi(false);
      return;
    }
    form.email.value = d.email || "";
    form.first_name.value = d.first_name || "";
    form.last_name.value = d.last_name || "";
    form.date_of_birth.value = d.date_of_birth || "";
    form.zipcode.value = d.zipcode || "";
    form.type_id.value = String(d.type_id || 71);
    form.distance.value = d.distance ?? 10;
    form.check_interval.value = d.check_interval ?? 60;
    form.origin_host.value = d.origin_host === "www" ? "www" : "public";
    form.stop_after_reschedule.checked = d.stop_after_reschedule === true;
    form.clear_session_token.checked = false;
    setConfiguredUi(true);
    setMsg(
      d.has_session_token
        ? "Settings loaded (re-enter last 4 SSN to update; session token kept on server)."
        : "Settings loaded — add Session token from the scheduler site, then Test connection.",
      ""
    );
  } catch {
    setMsg("Could not load settings.", "err");
  }
}

btnSave.addEventListener("click", async () => {
  setMsg("Saving…", "");
  testResultEl.hidden = true;
  testResultEl.textContent = "";
  const body = {
    email: form.email.value.trim(),
    first_name: form.first_name.value.trim(),
    last_name: form.last_name.value.trim(),
    date_of_birth: form.date_of_birth.value.trim(),
    last4ssn: form.last4ssn.value.trim(),
    zipcode: form.zipcode.value.trim(),
    type_id: Number(form.type_id.value),
    distance: Number(form.distance.value),
    check_interval: Number(form.check_interval.value),
    authorization_token: form.authorization_token.value.trim(),
    clear_session_token: form.clear_session_token.checked,
    origin_host: form.origin_host.value,
    stop_after_reschedule: form.stop_after_reschedule.checked,
  };
  try {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const t = await r.text();
    if (!r.ok) {
      let detail = t;
      try {
        detail = formatDetail(JSON.parse(t).detail);
      } catch {
        /* ignore */
      }
      setMsg(detail || t || "Save failed", "err");
      return;
    }
    form.clear_session_token.checked = false;
    form.authorization_token.value = "";
    setMsg("Saved. Run Test connection, then Start monitoring.", "ok");
    setConfiguredUi(true);
  } catch (e) {
    setMsg("Network error: " + e.message, "err");
  }
});

btnTest.addEventListener("click", async () => {
  setMsg("Testing…", "");
  testResultEl.hidden = true;
  testResultEl.textContent = "";
  try {
    const r = await fetch("/api/test-connection", { method: "POST" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = formatDetail(data.detail) || r.statusText;
      setMsg(detail || "Test failed", "err");
      return;
    }
    const lines = (data.logs || []).join("\n");
    testResultEl.textContent = lines || "(no log lines)";
    testResultEl.hidden = false;
    setMsg(
      data.ok
        ? "Connection OK — Eligibility succeeded. You can Start monitoring."
        : "Connection failed — read the test log below and fix token or identity.",
      data.ok ? "ok" : "err"
    );
  } catch (e) {
    setMsg("Network error: " + e.message, "err");
  }
});

btnStart.addEventListener("click", async () => {
  setMsg("", "");
  prevRescheduled = false;
  try {
    const r = await fetch("/api/start", { method: "POST" });
    const t = await r.text();
    if (!r.ok) {
      let detail = t;
      try {
        detail = formatDetail(JSON.parse(t).detail);
      } catch {
        /* ignore */
      }
      setMsg(detail || t || "Start failed", "err");
      return;
    }
    btnStart.disabled = true;
    btnStop.disabled = false;
    btnSave.disabled = true;
    btnTest.disabled = true;
  } catch (e) {
    setMsg("Network error: " + e.message, "err");
  }
});

btnStop.addEventListener("click", async () => {
  try {
    await fetch("/api/stop", { method: "POST" });
  } catch {
    /* ignore */
  }
});

btnNotify.addEventListener("click", async () => {
  if (typeof Notification === "undefined") {
    setMsg("This browser does not support notifications.", "err");
    return;
  }
  const p = await Notification.requestPermission();
  setMsg(
    p === "granted"
      ? "Alerts enabled — you’ll get a desktop notice if a reschedule succeeds."
      : "Notifications not allowed — you can still use the activity log.",
    p === "granted" ? "ok" : ""
  );
});

btnClearLog.addEventListener("click", async () => {
  try {
    const r = await fetch("/api/logs/clear", { method: "POST" });
    if (r.ok) {
      logEl.textContent = "";
      logEl.classList.add("log-empty");
    }
  } catch {
    /* ignore */
  }
});

btnDownloadLog.addEventListener("click", () => {
  const text = logEl.textContent || "";
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `dps-monitor-log-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
});

async function pollStatus() {
  try {
    const r = await fetch("/api/status");
    const d = await r.json();
    const lines = d.logs || [];
    const text = lines.join("\n");
    const stickToBottom =
      logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 64 ||
      logEl.textContent.trim() === "";
    const placeholder = d.running
      ? "Waiting for log output…"
      : "Log will show login, each check, and any earlier slots found. Use Test connection first if you have not started yet.";
    const display = text.trim() ? text : placeholder;
    logEl.textContent = display;
    logEl.classList.toggle("log-empty", !text.trim());
    if (stickToBottom && text.trim()) {
      logEl.scrollTop = logEl.scrollHeight;
    }
    updateStatusStrip(d);
    updateAppointmentDetails(d);
    if (!statusInitialized) {
      prevRescheduled = d.rescheduled === true;
      statusInitialized = true;
    } else if (
      d.rescheduled &&
      !prevRescheduled &&
      typeof Notification !== "undefined" &&
      Notification.permission === "granted"
    ) {
      try {
        new Notification("DPS slot monitor", {
          body: "Reschedule may have succeeded — check the log and your email.",
        });
      } catch {
        /* ignore */
      }
    }
    prevRescheduled = d.rescheduled === true;
    const configured = d.configured === true;
    if (!d.running) {
      btnStart.disabled = !configured;
      btnTest.disabled = !configured;
      btnStop.disabled = true;
      btnSave.disabled = false;
    } else {
      btnStart.disabled = true;
      btnTest.disabled = true;
      btnStop.disabled = false;
      btnSave.disabled = true;
    }
  } catch {
    /* keep UI stable */
  }
}

loadSettings();
setInterval(pollStatus, 1500);
pollStatus();
