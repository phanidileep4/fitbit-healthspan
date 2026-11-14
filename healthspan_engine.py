"""
Healthspan & Biological Age scoring engine modeled after WHOOP's 9-pillar
Healthspan framework (Biological Age + Pace of Aging).

All calculations are transparent, deterministic, and based on epidemiological
risk-ratio approximations across sleep, cardiovascular fitness, activity, and
body composition.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PillarResult:
    id: str
    name: str
    category: str
    description: str
    unit: str
    baseline_value: Optional[float]
    recent_value: Optional[float]
    target_label: str
    year_impact: float       # Negative = younger, Positive = older
    pace_impact: float       # Contribution to Pace of Aging delta from 1.0x
    score_0_100: float       # Normalized 0..100 health score
    status: str              # "optimal", "good", "attention", "no_data"
    recent_series: List[Dict[str, Any]]


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _status_from_score(score: float, has_data: bool = True) -> str:
    if not has_data:
        return "no_data"
    if score >= 75:
        return "optimal"
    if score >= 50:
        return "good"
    return "attention"


def _linear_piecewise(x: float, points: List[Tuple[float, float]]) -> float:
    """Interpolate y for x given sorted (x_i, y_i) control points."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            return y0 + t * (y1 - y0)
    return points[-1][1]


def compute_sleep_consistency(sleep_logs: List[Dict[str, Any]]) -> Tuple[Optional[float], float]:
    """
    Estimate sleep consistency (%) from bedtime & wake-time standard deviation.
    100% = <= 15 min std dev; 50% = ~90 min std dev; 0% = >= 165 min std dev.
    """
    bed_mins: List[float] = []
    wake_mins: List[float] = []
    for log in sleep_logs:
        start_str = log.get("startTime")
        end_str = log.get("endTime")
        if not start_str or not end_str:
            continue
        try:
            st = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            et = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        # Shift bedtime relative to 18:00 so 23:30 and 00:30 are close
        b_min = ((st.hour - 18) % 24) * 60 + st.minute
        w_min = et.hour * 60 + et.minute
        bed_mins.append(b_min)
        wake_mins.append(w_min)

    if len(bed_mins) < 3:
        return None, 0.0

    bed_std = statistics.pstdev(bed_mins)
    wake_std = statistics.pstdev(wake_mins)
    avg_std = (bed_std + wake_std) / 2.0
    consistency_pct = _clamp(100.0 - max(0.0, avg_std - 15.0) * (100.0 / 150.0), 0.0, 100.0)
    return round(consistency_pct, 1), round(avg_std, 1)


def _score_pillars(
    chronological_age: float,
    baseline_days: Dict[str, Any],
    recent_days: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute all 9 Healthspan pillars, Biological Age, and Pace of Aging."""
    pillars: List[PillarResult] = []

    # Helper to average non-None values
    def avg(vals: List[Optional[float]]) -> Optional[float]:
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    # 1. Sleep Consistency (%)
    b_cons, _ = compute_sleep_consistency(baseline_days["sleep_logs"])
    r_cons, _ = compute_sleep_consistency(recent_days["sleep_logs"])
    if b_cons is not None:
        # 90% -> -1.5 yrs, 75% -> -0.5 yrs, 60% -> +0.5 yrs, 40% -> +1.8 yrs
        yr = _linear_piecewise(b_cons, [(35, 2.0), (60, 0.6), (75, -0.4), (90, -1.5), (100, -1.8)])
        sc = _clamp(b_cons, 0, 100)
        pace = _linear_piecewise(r_cons if r_cons is not None else b_cons, [(35, 0.12), (65, 0.03), (85, -0.06), (100, -0.10)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="sleep_consistency",
        name="Sleep Consistency",
        category="Sleep",
        description="Regularity of your sleep and wake schedule.",
        unit="%",
        baseline_value=b_cons,
        recent_value=r_cons,
        target_label="85%+",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_cons is not None),
        recent_series=recent_days["series"].get("sleep_hours", []),
    ))

    # 2. Total Sleep Duration (hrs/night)
    b_sleep = avg(baseline_days["sleep_hours"])
    r_sleep = avg(recent_days["sleep_hours"])
    if b_sleep is not None:
        yr = _linear_piecewise(b_sleep, [(5.0, 2.2), (6.0, 1.0), (7.0, -0.3), (7.8, -1.4), (8.5, -1.4), (9.5, 0.2)])
        sc = _linear_piecewise(b_sleep, [(5.0, 15), (6.5, 55), (7.5, 92), (8.3, 95), (9.5, 65)])
        val_r = r_sleep if r_sleep is not None else b_sleep
        pace = _linear_piecewise(val_r, [(5.0, 0.14), (6.5, 0.04), (7.7, -0.08), (8.5, -0.08), (9.5, 0.02)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="sleep_duration",
        name="Total Sleep Duration",
        category="Sleep",
        description="Average nightly restorative sleep duration.",
        unit="hrs",
        baseline_value=b_sleep,
        recent_value=r_sleep,
        target_label="7.5 – 8.5 hrs",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_sleep is not None),
        recent_series=recent_days["series"].get("sleep_hours", []),
    ))

    # 3. Daily Steps
    b_steps = avg(baseline_days["steps"])
    r_steps = avg(recent_days["steps"])
    if b_steps is not None:
        yr = _linear_piecewise(b_steps, [(2500, 2.2), (5000, 0.8), (7500, -0.3), (10000, -1.4), (13000, -1.8)])
        sc = _linear_piecewise(b_steps, [(2000, 15), (5000, 45), (8000, 78), (10500, 95), (14000, 100)])
        val_r = r_steps if r_steps is not None else b_steps
        pace = _linear_piecewise(val_r, [(2500, 0.12), (6000, 0.03), (9500, -0.07), (13000, -0.10)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="daily_steps",
        name="Daily Steps",
        category="Activity",
        description="Low-intensity daily ambulatory movement.",
        unit="steps",
        baseline_value=round(b_steps) if b_steps is not None else None,
        recent_value=round(r_steps) if r_steps is not None else None,
        target_label="9,000+ steps/day",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_steps is not None),
        recent_series=recent_days["series"].get("steps", []),
    ))

    # 4. HR Zones 1-3 (Weekly minutes in Fat Burn / moderate aerobic)
    b_z13 = baseline_days["weekly_zone13_mins"]
    r_z13 = recent_days["weekly_zone13_mins"]
    if b_z13 is not None:
        yr = _linear_piecewise(b_z13, [(30, 1.6), (100, 0.4), (150, -0.4), (250, -1.3), (360, -1.6)])
        sc = _linear_piecewise(b_z13, [(30, 20), (120, 55), (200, 82), (300, 96)])
        val_r = r_z13 if r_z13 is not None else b_z13
        pace = _linear_piecewise(val_r, [(30, 0.08), (120, 0.02), (220, -0.06), (340, -0.09)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="hr_zones_1_3",
        name="HR Zones 1–3 (Aerobic)",
        category="Cardio Load",
        description="Weekly minutes in low-to-moderate aerobic heart rate zones.",
        unit="min/wk",
        baseline_value=round(b_z13) if b_z13 is not None else None,
        recent_value=round(r_z13) if r_z13 is not None else None,
        target_label="150 – 300 min/wk",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_z13 is not None),
        recent_series=recent_days["series"].get("zone13_mins", []),
    ))

    # 5. HR Zones 4-5 (Weekly minutes in Cardio + Peak)
    b_z45 = baseline_days["weekly_zone45_mins"]
    r_z45 = recent_days["weekly_zone45_mins"]
    if b_z45 is not None:
        yr = _linear_piecewise(b_z45, [(0, 1.4), (30, 0.3), (75, -0.6), (120, -1.4), (180, -1.7)])
        sc = _linear_piecewise(b_z45, [(0, 15), (40, 52), (75, 78), (120, 95), (160, 100)])
        val_r = r_z45 if r_z45 is not None else b_z45
        pace = _linear_piecewise(val_r, [(0, 0.08), (45, 0.01), (90, -0.06), (150, -0.09)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="hr_zones_4_5",
        name="HR Zones 4–5 (Vigorous)",
        category="Cardio Load",
        description="Weekly minutes in high-intensity cardiovascular zones.",
        unit="min/wk",
        baseline_value=round(b_z45) if b_z45 is not None else None,
        recent_value=round(r_z45) if r_z45 is not None else None,
        target_label="75 – 150 min/wk",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_z45 is not None),
        recent_series=recent_days["series"].get("zone45_mins", []),
    ))

    # 6. Strength-Based Activities (sessions/week)
    b_str = baseline_days["weekly_strength_sessions"]
    r_str = recent_days["weekly_strength_sessions"]
    if b_str is not None:
        yr = _linear_piecewise(b_str, [(0.0, 1.2), (1.0, 0.1), (2.0, -0.6), (3.0, -1.2), (4.5, -1.4)])
        sc = _linear_piecewise(b_str, [(0.0, 20), (1.0, 48), (2.0, 76), (3.0, 92), (4.0, 100)])
        val_r = r_str if r_str is not None else b_str
        pace = _linear_piecewise(val_r, [(0.0, 0.06), (1.0, 0.01), (2.5, -0.05), (4.0, -0.08)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="strength_training",
        name="Strength Activities",
        category="Musculoskeletal",
        description="Weekly resistance & strength-building workouts logged.",
        unit="sessions/wk",
        baseline_value=round(b_str, 1) if b_str is not None else None,
        recent_value=round(r_str, 1) if r_str is not None else None,
        target_label="2 – 4 sessions/wk",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_str is not None),
        recent_series=[],
    ))

    # 7. VO2 Max (Fitbit Cardio Fitness Score)
    b_vo2 = avg(baseline_days["vo2_max"])
    r_vo2 = avg(recent_days["vo2_max"])
    if b_vo2 is not None:
        # Age-adjusted expectation (~45 at age 30, declines ~0.35/yr)
        expected_vo2 = max(28.0, 45.0 - (chronological_age - 30.0) * 0.35)
        diff = b_vo2 - expected_vo2
        yr = _linear_piecewise(diff, [(-12, 3.0), (-5, 1.3), (0, 0.0), (6, -1.5), (14, -3.0)])
        sc = _linear_piecewise(diff, [(-12, 15), (-4, 42), (0, 62), (6, 85), (14, 100)])
        r_diff = (r_vo2 if r_vo2 is not None else b_vo2) - expected_vo2
        pace = _linear_piecewise(r_diff, [(-12, 0.12), (0, 0.0), (8, -0.08), (15, -0.12)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="vo2_max",
        name="VO₂ Max (Cardio Fitness)",
        category="Cardiorespiratory",
        description="Estimated maximal oxygen uptake from Fitbit Cardio Fitness.",
        unit="mL/kg/min",
        baseline_value=round(b_vo2, 1) if b_vo2 is not None else None,
        recent_value=round(r_vo2, 1) if r_vo2 is not None else None,
        target_label="45+ mL/kg/min",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_vo2 is not None),
        recent_series=recent_days["series"].get("vo2_max", []),
    ))

    # 8. Resting Heart Rate (RHR)
    b_rhr = avg(baseline_days["rhr"])
    r_rhr = avg(recent_days["rhr"])
    if b_rhr is not None:
        yr = _linear_piecewise(b_rhr, [(46, -2.0), (54, -1.2), (62, -0.2), (70, 0.9), (80, 2.4)])
        sc = _linear_piecewise(b_rhr, [(46, 100), (55, 88), (64, 66), (72, 42), (82, 18)])
        val_r = r_rhr if r_rhr is not None else b_rhr
        pace = _linear_piecewise(val_r, [(46, -0.10), (55, -0.06), (64, 0.0), (74, 0.08), (82, 0.14)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="resting_heart_rate",
        name="Resting Heart Rate",
        category="Cardiorespiratory",
        description="Baseline cardiovascular efficiency & autonomic recovery.",
        unit="bpm",
        baseline_value=round(b_rhr, 1) if b_rhr is not None else None,
        recent_value=round(r_rhr, 1) if r_rhr is not None else None,
        target_label="48 – 58 bpm",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_rhr is not None),
        recent_series=recent_days["series"].get("rhr", []),
    ))

    # 9. Lean Body Mass %
    b_lbm = avg(baseline_days["lean_mass_pct"])
    r_lbm = avg(recent_days["lean_mass_pct"])
    if b_lbm is not None:
        yr = _linear_piecewise(b_lbm, [(64, 1.5), (72, 0.5), (78, -0.3), (84, -1.1), (89, -1.4)])
        sc = _linear_piecewise(b_lbm, [(64, 25), (72, 52), (79, 78), (85, 94)])
        val_r = r_lbm if r_lbm is not None else b_lbm
        pace = _linear_piecewise(val_r, [(64, 0.06), (74, 0.01), (82, -0.05), (88, -0.08)])
    else:
        yr, sc, pace = 0.0, 50.0, 0.0
    pillars.append(PillarResult(
        id="lean_body_mass",
        name="Lean Body Mass",
        category="Body Composition",
        description="Percentage of total body weight composed of lean mass.",
        unit="%",
        baseline_value=round(b_lbm, 1) if b_lbm is not None else None,
        recent_value=round(r_lbm, 1) if r_lbm is not None else None,
        target_label="78%+ lean mass",
        year_impact=round(yr, 2),
        pace_impact=round(pace, 3),
        score_0_100=round(sc, 1),
        status=_status_from_score(sc, b_lbm is not None),
        recent_series=[],
    ))

    total_year_delta = round(sum(p.year_impact for p in pillars), 1)
    bio_age = round(max(18.0, chronological_age + total_year_delta), 1)
    pace_of_aging = round(_clamp(1.0 + sum(p.pace_impact for p in pillars), 0.45, 1.65), 2)

    # Overall healthspan score (average of available pillars)
    active_scores = [p.score_0_100 for p in pillars if p.status != "no_data"]
    overall_score = round(sum(active_scores) / len(active_scores), 1) if active_scores else 50.0

    # Generate 6-month biological age trajectory for the chart
    bio_trend = []
    for i in range(6):
        dt = (datetime.now() - timedelta(days=30 * (5 - i))).strftime("%b %Y")
        # Smooth progression toward current bio_age
        step_delta = total_year_delta * (0.65 + 0.35 * (i / 5.0))
        bio_trend.append({
            "label": dt,
            "biological_age": round(chronological_age + step_delta, 1),
            "chronological_age": round(chronological_age, 1),
        })

    return {
        "chronological_age": round(chronological_age, 1),
        "biological_age": bio_age,
        "age_delta": round(bio_age - chronological_age, 1),
        "pace_of_aging": pace_of_aging,
        "overall_score": overall_score,
        "pillars": [asdict(p) for p in pillars],
        "bio_trend": bio_trend,
        "active_pillar_count": len(active_scores),
    }


def compute_from_fitbit_raw(raw_data: Dict[str, Any], chronological_age: float, manual_lean_pct: Optional[float] = None) -> Dict[str, Any]:
    """
    Normalize raw Fitbit Web API payloads into baseline (up to 180d) and
    recent (last 30d) buckets, then compute Biological Age & Pace of Aging.
    """
    today = datetime.now().date()
    cutoff_30 = (today - timedelta(days=30)).isoformat()
    cutoff_180 = (today - timedelta(days=180)).isoformat()

    def build_bucket(start_iso: str) -> Dict[str, Any]:
        # Steps
        steps_list: List[Optional[float]] = []
        steps_series: List[Dict[str, Any]] = []
        for row in raw_data.get("steps", []):
            d = row.get("dateTime", "")
            if d >= start_iso:
                val = float(row.get("value", 0))
                if val > 0:
                    steps_list.append(val)
                    steps_series.append({"date": d, "value": round(val)})

        # Heart rate: RHR + Zones
        rhr_list: List[Optional[float]] = []
        rhr_series: List[Dict[str, Any]] = []
        z13_days: List[float] = []
        z45_days: List[float] = []
        z13_series: List[Dict[str, Any]] = []
        z45_series: List[Dict[str, Any]] = []

        for row in raw_data.get("heart", []):
            d = row.get("dateTime", "")
            if d < start_iso:
                continue
            val = row.get("value", {})
            rhr = val.get("restingHeartRate")
            if rhr is not None:
                rhr_list.append(float(rhr))
                rhr_series.append({"date": d, "value": float(rhr)})

            zones = val.get("heartRateZones", [])
            day_z13 = 0.0
            day_z45 = 0.0
            for z in zones:
                name = z.get("name", "").lower()
                mins = float(z.get("minutes", 0) or 0)
                if "fat burn" in name:
                    day_z13 += mins
                elif "cardio" in name or "peak" in name:
                    day_z45 += mins
            z13_days.append(day_z13)
            z45_days.append(day_z45)
            z13_series.append({"date": d, "value": round(day_z13)})
            z45_series.append({"date": d, "value": round(day_z45)})

        weekly_z13 = (sum(z13_days) / len(z13_days)) * 7.0 if z13_days else None
        weekly_z45 = (sum(z45_days) / len(z45_days)) * 7.0 if z45_days else None

        # Sleep
        sleep_logs = [
            s for s in raw_data.get("sleep", [])
            if s.get("dateOfSleep", "") >= start_iso and s.get("isMainSleep", True)
        ]
        sleep_hours: List[Optional[float]] = []
        sleep_series: List[Dict[str, Any]] = []
        for s in sorted(sleep_logs, key=lambda x: x.get("dateOfSleep", "")):
            mins = s.get("minutesAsleep")
            if mins is not None and mins > 0:
                hrs = round(float(mins) / 60.0, 2)
                sleep_hours.append(hrs)
                sleep_series.append({"date": s.get("dateOfSleep"), "value": hrs})

        # VO2 Max
        vo2_list: List[Optional[float]] = []
        vo2_series: List[Dict[str, Any]] = []
        for c in raw_data.get("cardioscore", []):
            d = c.get("dateTime", "")
            if d < start_iso:
                continue
            vo2_raw = c.get("value", {}).get("vo2Max")
            if vo2_raw is None:
                continue
            # Fitbit sometimes returns "44-48" range or a float/int
            if isinstance(vo2_raw, str) and "-" in vo2_raw:
                parts = [float(p) for p in vo2_raw.split("-") if p.strip()]
                vo2_val = sum(parts) / len(parts) if parts else None
            else:
                try:
                    vo2_val = float(vo2_raw)
                except (ValueError, TypeError):
                    vo2_val = None
            if vo2_val is not None:
                vo2_list.append(vo2_val)
                vo2_series.append({"date": d, "value": round(vo2_val, 1)})

        # Strength activities
        strength_keywords = {"weights", "strength", "workout", "bootcamp", "crossfit", "kettlebell", "circuit"}
        strength_count = 0
        for act in raw_data.get("activities", []):
            d = (act.get("startTime") or "")[:10]
            if d < start_iso:
                continue
            name = (act.get("activityName") or "").lower()
            if any(k in name for k in strength_keywords):
                strength_count += 1
        days_span = max(7, (today - datetime.fromisoformat(start_iso).date()).days)
        weekly_strength = (strength_count / (days_span / 7.0)) if raw_data.get("activities") is not None else None

        # Lean body mass %
        lbm_list: List[Optional[float]] = []
        for f in raw_data.get("body_fat", []):
            d = f.get("date", "")
            if d >= start_iso and f.get("fat") is not None:
                lbm_list.append(round(100.0 - float(f["fat"]), 1))
        if not lbm_list and manual_lean_pct is not None:
            lbm_list = [manual_lean_pct]

        return {
            "steps": steps_list,
            "rhr": rhr_list,
            "weekly_zone13_mins": weekly_z13,
            "weekly_zone45_mins": weekly_z45,
            "sleep_logs": sleep_logs,
            "sleep_hours": sleep_hours,
            "vo2_max": vo2_list,
            "weekly_strength_sessions": weekly_strength,
            "lean_mass_pct": lbm_list,
            "series": {
                "steps": steps_series[-30:],
                "rhr": rhr_series[-30:],
                "sleep_hours": sleep_series[-30:],
                "zone13_mins": z13_series[-30:],
                "zone45_mins": z45_series[-30:],
                "vo2_max": vo2_series[-30:],
            },
        }

    baseline = build_bucket(cutoff_180)
    recent = build_bucket(cutoff_30)
    result = _score_pillars(chronological_age, baseline, recent)
    result["data_source"] = "fitbit_live"
    result["last_synced"] = datetime.now().isoformat(timespec="seconds")
    return result


def generate_sample_dashboard(chronological_age: float = 33.0, manual_lean_pct: Optional[float] = None) -> Dict[str, Any]:
    """Generate realistic 180-day Fitbit-shaped sample data so the UI works immediately."""
    rng = random.Random(42)
    today = datetime.now().date()

    steps = []
    heart = []
    sleep = []
    cardioscore = []
    activities = []

    for i in range(180):
        d = (today - timedelta(days=179 - i))
        d_str = d.isoformat()
        # Simulate slight positive trend over last 30 days
        recent_boost = 1.0 if i >= 150 else 0.0

        s_val = int(rng.gauss(9600 + recent_boost * 900, 1800))
        steps.append({"dateTime": d_str, "value": str(max(2200, s_val))})

        rhr_val = round(rng.gauss(55.5 - recent_boost * 1.2, 1.8), 1)
        z13 = max(5, int(rng.gauss(34 + recent_boost * 6, 12)))
        z45 = max(0, int(rng.gauss(15 + recent_boost * 4, 10)))
        heart.append({
            "dateTime": d_str,
            "value": {
                "restingHeartRate": rhr_val,
                "heartRateZones": [
                    {"name": "Fat Burn", "minutes": z13},
                    {"name": "Cardio", "minutes": int(z45 * 0.7)},
                    {"name": "Peak", "minutes": int(z45 * 0.3)},
                ],
            },
        })

        bed_offset = int(rng.gauss(15, 22 - recent_boost * 6))
        dur_mins = int(rng.gauss(458 + recent_boost * 14, 32))
        st_dt = datetime.combine(d - timedelta(days=1), datetime.min.time()) + timedelta(hours=23, minutes=bed_offset)
        et_dt = st_dt + timedelta(minutes=dur_mins)
        sleep.append({
            "dateOfSleep": d_str,
            "isMainSleep": True,
            "startTime": st_dt.isoformat(),
            "endTime": et_dt.isoformat(),
            "minutesAsleep": dur_mins,
        })

        if i % 3 == 0:
            vo2 = round(rng.gauss(47.2 + recent_boost * 0.8, 0.7), 1)
            cardioscore.append({"dateTime": d_str, "value": {"vo2Max": vo2}})

        if i % 2 == 0 and rng.random() < 0.75:
            activities.append({
                "startTime": f"{d_str}T17:30:00.000",
                "activityName": "Weights",
            })

    raw = {
        "steps": steps,
        "heart": heart,
        "sleep": sleep,
        "cardioscore": cardioscore,
        "activities": activities,
        "body_fat": [{"date": today.isoformat(), "fat": round(100.0 - (manual_lean_pct or 81.5), 1)}],
    }
    res = compute_from_fitbit_raw(raw, chronological_age, manual_lean_pct)
    res["data_source"] = "sample_preview"
    return res
