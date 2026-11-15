"""
Stateless Google Health API v4 client using Google OAuth 2.0 + PKCE (stdlib only).
All session state (tokens, client_id, profile settings) is passed in/out as a
dictionary so the app can run maintenance-free on serverless platforms (Vercel)
using HttpOnly cookies, or locally with zero database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import math
from concurrent.futures import ThreadPoolExecutor
from threading import local
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

_REQUEST_CONTEXT = local()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://health.googleapis.com/v4"
SCOPES = " ".join([
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.profile.readonly",
])


def _effective_credentials(st: Dict[str, Any]) -> Tuple[str, str]:
    cid = (st.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID", "")).strip()
    csec = (st.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET", "")).strip()
    return cid, csec


def get_config(st: Dict[str, Any]) -> Dict[str, Any]:
    env_cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    return {
        "client_id": st.get("client_id", ""),
        "has_client_secret": bool(st.get("client_secret")),
        "has_server_credentials": bool(env_cid),
        "connected": bool(st.get("tokens", {}).get("access_token")),
        "chronological_age": st.get("chronological_age", 33.0),
        "manual_lean_pct": st.get("manual_lean_pct"),
        "user_name": st.get("profile_name", ""),
        "last_synced": st.get("last_synced"),
        "cache_id": st.get("cache_id"),
        "history_id": st.get("history_id", st.get("cache_id")),
    }


def update_config(
    st: Dict[str, Any],
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    chronological_age: Optional[float] = None,
    manual_lean_pct: Optional[float] = None,
) -> Dict[str, Any]:
    if client_id is not None:
        st["client_id"] = client_id.strip()
    if client_secret is not None:
        st["client_secret"] = client_secret.strip()
    if chronological_age is not None:
        age = float(chronological_age)
        if not math.isfinite(age) or not 18 <= age <= 100:
            raise ValueError("Age must be between 18 and 100.")
        st["chronological_age"] = age
    if manual_lean_pct is not None:
        lean = float(manual_lean_pct)
        if not math.isfinite(lean) or (lean != 0 and not 40 <= lean <= 95):
            raise ValueError("Lean mass must be between 40 and 95%, or blank.")
        st["manual_lean_pct"] = lean if lean else None
    return st


def disconnect(st: Dict[str, Any]) -> Dict[str, Any]:
    st.pop("tokens", None)
    st.pop("profile_name", None)
    st.pop("last_synced", None)
    return st


def build_auth_url(st: Dict[str, Any], client_id: str, client_secret: str, redirect_uri: str) -> Tuple[str, Dict[str, Any]]:
    if client_id.strip():
        st["client_id"] = client_id.strip()
    if client_secret.strip():
        st["client_secret"] = client_secret.strip()

    eff_cid, _ = _effective_credentials(st)
    if not eff_cid:
        raise RuntimeError("Google OAuth Client ID is not configured.")

    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    oauth_state = secrets.token_urlsafe(24)

    st["cache_id"] = secrets.token_urlsafe(12)
    st["pkce"] = {
        "code_verifier": code_verifier,
        "state": oauth_state,
        "created_at": time.time(),
        "redirect_uri": redirect_uri,
    }

    params = {
        "client_id": eff_cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": oauth_state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", st


def _post_token(form_data: Dict[str, str]) -> Dict[str, Any]:
    body = urllib.parse.urlencode(form_data).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(TOKEN_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google authorization failed (HTTP {e.code}). Please reconnect.") from e


def exchange_code(st: Dict[str, Any], code: str, returned_state: str, fallback_redirect_uri: str) -> Dict[str, Any]:
    pkce = st.get("pkce", {})
    if not code or not pkce or not secrets.compare_digest(pkce.get("state", ""), returned_state) or time.time() - pkce.get("created_at", 0) > 600:
        raise RuntimeError("OAuth state mismatch. Please restart the Google Health connection flow.")

    client_id, client_secret = _effective_credentials(st)
    redirect_uri = pkce.get("redirect_uri") or fallback_redirect_uri
    form = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": pkce["code_verifier"],
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        form["client_secret"] = client_secret

    token_resp = _post_token(form)
    expires_at = time.time() + int(token_resp.get("expires_in", 3599)) - 60
    st["tokens"] = {
        "access_token": token_resp["access_token"],
        "refresh_token": token_resp.get("refresh_token", ""),
        "expires_at": expires_at,
    }
    st.pop("pkce", None)
    return st


def _get_valid_access_token(st: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    tokens = st.get("tokens")
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError("Google Health is not connected.")

    if time.time() >= tokens.get("expires_at", 0) and tokens.get("refresh_token"):
        client_id, client_secret = _effective_credentials(st)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        }
        if client_secret:
            form["client_secret"] = client_secret
        token_resp = _post_token(form)
        tokens = {
            "access_token": token_resp["access_token"],
            "refresh_token": token_resp.get("refresh_token", tokens["refresh_token"]),
            "expires_at": time.time() + int(token_resp.get("expires_in", 3599)) - 60,
        }
        st["tokens"] = tokens

    return tokens["access_token"], st


def _api_request(method: str, path: str, token: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    remaining = getattr(_REQUEST_CONTEXT, "deadline", time.monotonic() + 12) - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("Sync time budget exceeded; retry sync.")
    try:
        with urllib.request.urlopen(req, timeout=min(12, remaining)) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google Health request failed (HTTP {e.code})." ) from e


def _date_string(value: Dict[str, Any]) -> str:
    try:
        return datetime(int(value["year"]), int(value["month"]), int(value["day"])).date().isoformat()
    except (KeyError, TypeError, ValueError):
        return ""


def _local_time(interval: Dict[str, Any], end: bool = False) -> str:
    prefix = "end" if end else "start"
    stamp = interval.get(prefix + "Time")
    if not stamp:
        return ""
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    offset = interval.get(prefix + "UtcOffset")
    if offset is not None:
        dt = dt.astimezone(timezone(timedelta(seconds=float(offset.rstrip("s")))))
    return dt.isoformat()


def _extract_date(dp: Dict[str, Any]) -> str:
    civil = dp.get("civilStartTime", {})
    if civil:
        return _date_string(civil.get("date", {}))
    for key in ("dailyRestingHeartRate", "dailyVo2Max"):
        if key in dp:
            return _date_string(dp[key].get("date", {}))
    for key in ("bodyFat", "vo2Max"):
        sample = dp.get(key, {}).get("sampleTime", {})
        if sample:
            civil = sample.get("civilTime", {})
            if civil:
                return _date_string(civil.get("date", {}))
            return _local_time({"startTime": sample.get("physicalTime"), "startUtcOffset": sample.get("utcOffset")})[:10]
    return ""


def _list_points(data_type: str, field: str, start: str, end: str, token: str) -> List[Dict[str, Any]]:
    params = {"pageSize": 25 if data_type in ("sleep", "exercise") else 1000,
              "filter": f'{field} >= "{start}" AND {field} < "{end}"'}
    items = []
    for _ in range(30):
        path = f"/users/me/dataTypes/{data_type}/dataPoints?{urllib.parse.urlencode(params)}"
        resp = _api_request("GET", path, token)
        items.extend(resp.get("dataPoints", []))
        if not resp.get("nextPageToken"):
            return items
        params["pageToken"] = resp["nextPageToken"]
    raise RuntimeError("Too many pages; the requested history could not be fully retrieved.")


def _daily_rollup(data_type: str, start: datetime, end: datetime, token: str) -> List[Dict[str, Any]]:
    items = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=90), end)
        def civil(dt):
            return {"date": {"year": dt.year, "month": dt.month, "day": dt.day}}
        body = {"range": {"start": civil(cursor), "end": civil(stop)}, "windowSizeDays": 1, "pageSize": 90}
        for _ in range(5):
            resp = _api_request("POST", f"/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp", token, body)
            items.extend(resp.get("rollupDataPoints", []))
            if not resp.get("nextPageToken"):
                break
            body["pageToken"] = resp["nextPageToken"]
        else:
            raise RuntimeError("Daily rollup pagination did not finish.")
        cursor = stop
    return items


def sync_fitbit_data(st: Dict[str, Any]) -> Tuple[Dict[str, Any], float, Dict[str, Any]]:
    token, st = _get_valid_access_token(st)
    now = datetime.now(ZoneInfo(st.get("timezone", "America/Chicago")))
    end = now.date()
    start = end - timedelta(days=180)
    begin, finish = start.isoformat(), end.isoformat()
    diagnostics = []

    def fetch_metric(name, fn):
        _REQUEST_CONTEXT.deadline = deadline
        try:
            points = fn()
            return points, {"metric": name, "status": "ok" if points else "empty", "records": len(points)}
        except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            return None, {"metric": name, "status": "error", "records": 0,
                          "message": str(exc) if isinstance(exc, RuntimeError) else "Request failed. Retry sync."}

    deadline = time.monotonic() + 40
    jobs = {
        "steps": lambda: _daily_rollup("steps", datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()), token),
        "zones": lambda: _daily_rollup("time-in-heart-rate-zone", datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()), token),
        "rhr": lambda: _list_points("daily-resting-heart-rate", "daily_resting_heart_rate.date", begin, finish, token),
        "sleep": lambda: _list_points("sleep", "sleep.interval.civil_end_time", begin, finish, token),
        "vo2": lambda: _list_points("daily-vo2-max", "daily_vo2_max.date", begin, finish, token),
        "exercise": lambda: _list_points("exercise", "exercise.interval.civil_start_time", begin, finish, token),
        "body_fat": lambda: _list_points("body-fat", "body_fat.sample_time.civil_time", begin, finish, token),
        "profile": lambda: [_api_request("GET", "/users/me/profile", token)],
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(fetch_metric, name, fn) for name, fn in jobs.items()}
        results = {}
        for name, future in futures.items():
            results[name], diag = future.result()
            diagnostics.append(diag)

    profile = (results["profile"] or [{}])[0]
    if profile.get("age") and not st.get("age_override"):
        st["chronological_age"] = float(profile["age"])
    profile_name = profile.get("name", "")
    if profile_name.startswith("users/") and profile_name.endswith("/profile") and profile_name.split("/")[1] != "me":
        st["history_id"] = hashlib.sha256(("healthspan-history:" + profile_name).encode()).hexdigest()[:32]
    chrono_age = float(st.get("chronological_age", 33))
    raw = {"steps": [], "heart": [], "sleep": [], "cardioscore": [], "activities": [], "body_fat": [],
           "diagnostics": diagnostics, "as_of": finish}
    for point in results["steps"] or []:
        if "steps" in point and "countSum" in point["steps"]:
            raw["steps"].append({"dateTime": _extract_date(point), "value": point["steps"]["countSum"]})
    heart = {}
    for point in results["rhr"] or []:
        day = _extract_date(point)
        val = point.get("dailyRestingHeartRate", {}).get("beatsPerMinute")
        if day and val is not None:
            heart.setdefault(day, {"dateTime": day, "value": {}})["value"]["restingHeartRate"] = float(val)
    for point in results["zones"] or []:
        day = _extract_date(point)
        zones = point.get("timeInHeartRateZone", {}).get("timeInHeartRateZones")
        if not day or not zones:
            continue
        normalized = []
        for zone in zones:
            name = {"MODERATE": "Fat Burn", "VIGOROUS": "Cardio", "PEAK": "Peak"}.get(zone.get("heartRateZone"))
            if name:
                normalized.append({"name": name, "minutes": float(zone.get("duration", "0s").rstrip("s")) / 60})
        if normalized:
            heart.setdefault(day, {"dateTime": day, "value": {}})["value"]["heartRateZones"] = normalized
    raw["heart"] = sorted(heart.values(), key=lambda row: row["dateTime"])
    for point in results["sleep"] or []:
        sleep = point.get("sleep", {})
        meta = sleep.get("metadata", {})
        if meta.get("nap") or meta.get("mainSleep") is False or meta.get("processed") is False:
            continue
        interval = sleep.get("interval", {})
        start_time, end_time = _local_time(interval), _local_time(interval, True)
        minutes = sleep.get("summary", {}).get("minutesAsleep")
        # Time in bed must never silently substitute for time asleep.
        if start_time and end_time and minutes is not None:
            raw["sleep"].append({"dateOfSleep": end_time[:10], "isMainSleep": True,
                "startTime": start_time, "endTime": end_time, "minutesAsleep": float(minutes)})
    for point in results["vo2"] or []:
        val = point.get("dailyVo2Max", {}).get("vo2Max")
        if val is not None:
            raw["cardioscore"].append({"dateTime": _extract_date(point), "value": {"vo2Max": float(val)}, "fitness_level": point.get("dailyVo2Max", {}).get("cardioFitnessLevel")})
    for point in results["exercise"] or []:
        exercise = point.get("exercise", {})
        raw["activities"].append({"startTime": _local_time(exercise.get("interval", {})),
            "activityName": exercise.get("exerciseType", ""), "id": point.get("name", "")})
    for point in results["body_fat"] or []:
        val = point.get("bodyFat", {}).get("percentage")
        if val is not None:
            raw["body_fat"].append({"date": _extract_date(point), "fat": float(val)})
    if not any(raw[key] for key in ("steps", "heart", "sleep", "cardioscore", "activities", "body_fat")):
        raise RuntimeError("No usable health data was retrieved. Check Google permissions and device sync, then retry.")
    for key in ("steps", "heart", "sleep", "cardioscore", "activities", "body_fat"):
        day_key = {"sleep": "dateOfSleep", "activities": "startTime", "body_fat": "date"}.get(key, "dateTime")
        raw[key].sort(key=lambda row: row.get(day_key, ""))
    st["last_synced"] = now.isoformat(timespec="seconds")
    return raw, chrono_age, st
