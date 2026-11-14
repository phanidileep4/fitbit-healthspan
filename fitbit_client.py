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
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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
        st["chronological_age"] = float(chronological_age)
    if manual_lean_pct is not None:
        st["manual_lean_pct"] = float(manual_lean_pct) if manual_lean_pct > 0 else None
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

    st["pkce"] = {
        "code_verifier": code_verifier,
        "state": oauth_state,
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
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google OAuth token error ({e.code}): {err_body}") from e


def exchange_code(st: Dict[str, Any], code: str, returned_state: str, fallback_redirect_uri: str) -> Dict[str, Any]:
    pkce = st.get("pkce", {})
    if not pkce or pkce.get("state") != returned_state:
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
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Health API {path} failed ({e.code}): {err_body}") from e


def _safe_get_paginated(path: str, token: str, max_pages: int = 8) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    for _ in range(max_pages):
        sep = "&" if "?" in path else "?"
        full_path = f"{path}{sep}pageToken={urllib.parse.quote(page_token)}" if page_token else path
        try:
            resp = _api_request("GET", full_path, token)
        except RuntimeError:
            break
        pts = resp.get("dataPoints") or resp.get("items") or []
        items.extend(pts)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _daily_rollup(data_type: str, start_dt: datetime, end_dt: datetime, token: str) -> List[Dict[str, Any]]:
    body = {
        "range": {
            "start": {
                "date": {"year": start_dt.year, "month": start_dt.month, "day": start_dt.day},
                "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0},
            },
            "end": {
                "date": {"year": end_dt.year, "month": end_dt.month, "day": end_dt.day},
                "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0},
            },
        },
        "windowSizeDays": 1,
    }
    try:
        resp = _api_request("POST", f"/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp", token, body)
        return resp.get("rollupDataPoints") or resp.get("dataPoints") or []
    except RuntimeError:
        return []


def _extract_date(dp: Dict[str, Any]) -> str:
    for key in ("startTime", "sampleTime", "dateTime"):
        if isinstance(dp.get(key), str) and len(dp[key]) >= 10:
            return dp[key][:10]
    for container in ("window", "range", "interval"):
        sub = dp.get(container, {})
        st = sub.get("start") or sub.get("startTime")
        if isinstance(st, str) and len(st) >= 10:
            return st[:10]
        if isinstance(st, dict) and "date" in st:
            d = st["date"]
            return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
    return ""


def sync_fitbit_data(st: Dict[str, Any]) -> Tuple[Dict[str, Any], float, Dict[str, Any]]:
    """
    Fetch up to 180 days of data from Google Health API v4 and normalize into
    the Healthspan engine's internal format.
    """
    token, st = _get_valid_access_token(st)
    now = datetime.now(timezone.utc)
    today = now.date()
    start_180 = today - timedelta(days=179)
    mid_90 = today - timedelta(days=90)

    try:
        prof = _api_request("GET", "/users/me/profile", token)
        if prof.get("displayName"):
            st["profile_name"] = prof["displayName"]
        if prof.get("age"):
            st["chronological_age"] = float(prof["age"])
    except RuntimeError:
        pass
    chrono_age = float(st.get("chronological_age", 33.0))

    steps_raw: List[Dict[str, Any]] = []
    for s_d, e_d in [(start_180, mid_90), (mid_90 + timedelta(days=1), today)]:
        for rp in _daily_rollup("steps", datetime.combine(s_d, datetime.min.time()), datetime.combine(e_d, datetime.min.time()), token):
            d_str = _extract_date(rp)
            val = rp.get("steps", {}).get("countSum") or rp.get("countSum") or rp.get("value") or 0
            if d_str:
                steps_raw.append({"dateTime": d_str, "value": str(int(val))})

    rhr_pts = _safe_get_paginated("/users/me/dataTypes/daily-resting-heart-rate/dataPoints?pageSize=200", token)
    zone_pts = _safe_get_paginated("/users/me/dataTypes/time-in-heart-rate-zone/dataPoints?pageSize=200", token)

    heart_by_day: Dict[str, Dict[str, Any]] = {}
    for pt in rhr_pts:
        d_str = _extract_date(pt)
        rhr_val = (
            pt.get("dailyRestingHeartRate", {}).get("beatsPerMinute")
            or pt.get("beatsPerMinute")
            or pt.get("value")
        )
        if d_str and rhr_val is not None:
            heart_by_day.setdefault(d_str, {"dateTime": d_str, "value": {"heartRateZones": []}})
            heart_by_day[d_str]["value"]["restingHeartRate"] = float(rhr_val)

    for pt in zone_pts:
        d_str = _extract_date(pt)
        if not d_str:
            continue
        z_obj = pt.get("timeInHeartRateZone", pt)
        z_type = str(z_obj.get("heartRateZoneType", "")).lower()
        secs = float(z_obj.get("durationSeconds", 0) or 0)
        mins = secs / 60.0
        entry = heart_by_day.setdefault(d_str, {"dateTime": d_str, "value": {"heartRateZones": []}})
        zone_name = "Fat Burn" if ("fat" in z_type or "moderate" in z_type or "light" in z_type) else (
            "Cardio" if "vigorous" in z_type or "cardio" in z_type else (
                "Peak" if "peak" in z_type else "Fat Burn"
            )
        )
        entry["value"]["heartRateZones"].append({"name": zone_name, "minutes": mins})

    heart_raw = sorted(heart_by_day.values(), key=lambda x: x["dateTime"])

    sleep_pts = _safe_get_paginated("/users/me/dataTypes/sleep/dataPoints?pageSize=200", token)
    sleep_raw: List[Dict[str, Any]] = []
    for pt in sleep_pts:
        sl = pt.get("sleep", pt)
        interval = pt.get("interval") or sl.get("interval") or {}
        st_time = interval.get("startTime") or sl.get("startTime")
        en_time = interval.get("endTime") or sl.get("endTime")
        if not st_time or not en_time:
            continue
        d_str = en_time[:10]
        dur_mins = sl.get("minutesAsleep")
        if dur_mins is None:
            try:
                t0 = datetime.fromisoformat(st_time.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(en_time.replace("Z", "+00:00"))
                dur_mins = max(0, int((t1 - t0).total_seconds() / 60.0))
            except ValueError:
                dur_mins = 0
        sleep_raw.append({
            "dateOfSleep": d_str,
            "isMainSleep": True,
            "startTime": st_time,
            "endTime": en_time,
            "minutesAsleep": dur_mins,
        })

    vo2_pts = _safe_get_paginated("/users/me/dataTypes/daily-vo2-max/dataPoints?pageSize=200", token)
    if not vo2_pts:
        vo2_pts = _safe_get_paginated("/users/me/dataTypes/vo2-max/dataPoints?pageSize=200", token)
    cardioscore_raw: List[Dict[str, Any]] = []
    for pt in vo2_pts:
        d_str = _extract_date(pt)
        v = (
            pt.get("dailyVo2Max", {}).get("vo2Max")
            or pt.get("vo2Max", {}).get("vo2Max")
            or pt.get("value")
        )
        if d_str and v is not None:
            cardioscore_raw.append({"dateTime": d_str, "value": {"vo2Max": v}})

    ex_pts = _safe_get_paginated("/users/me/dataTypes/exercise/dataPoints?pageSize=200", token)
    activities_raw: List[Dict[str, Any]] = []
    for pt in ex_pts:
        ex = pt.get("exercise", pt)
        st_time = (pt.get("interval") or {}).get("startTime") or ex.get("startTime") or ""
        ex_type = ex.get("exerciseType") or ex.get("displayName") or "Workout"
        activities_raw.append({"startTime": st_time, "activityName": str(ex_type)})

    fat_pts = _safe_get_paginated("/users/me/dataTypes/body-fat/dataPoints?pageSize=50", token)
    body_fat_raw: List[Dict[str, Any]] = []
    for pt in fat_pts:
        d_str = _extract_date(pt)
        pct = pt.get("bodyFat", {}).get("percentage") or pt.get("percentage")
        if d_str and pct is not None:
            body_fat_raw.append({"date": d_str, "fat": float(pct)})

    raw = {
        "steps": steps_raw,
        "heart": heart_raw,
        "sleep": sleep_raw,
        "cardioscore": cardioscore_raw,
        "activities": activities_raw,
        "body_fat": body_fat_raw,
    }
    st["last_synced"] = datetime.now().isoformat(timespec="seconds")
    return raw, chrono_age, st
