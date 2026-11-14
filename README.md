# Fitbit Healthspan — Biological Age & Pace of Aging Dashboard

A local, WHOOP-inspired **Healthspan / Biological Age** dashboard powered by the **Google Health API v4** (`health.googleapis.com/v4`) with Google OAuth 2.0 + PKCE. Zero external Python dependencies required.

## Quick Start

1. Run the local server:
   ```bash
   cd /Users/phanidileep/.gemini/antigravity/scratch/fitbit-healthspan
   python3 app.py
   ```
2. Open [http://localhost:8765](http://localhost:8765) in your browser.
3. Click **Connect Fitbit** in the top right and follow the [Google Health API setup](https://developers.google.com/health/setup):
   - In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **Google Health API**.
   - Configure **OAuth consent screen** (External, Testing mode), add yourself as a **Test user**, and add the read-only `googlehealth` scopes (`activity_and_fitness`, `sleep`, `health_metrics_and_measurements`, `profile`).
   - Under **Credentials → Create OAuth client ID**, select **Web application** and add Authorized redirect URI: `http://localhost:8765/callback`.
   - Paste your **Client ID** and **Client Secret** into the modal and click **Authorize with Google Health**.

## The 9 Healthspan Pillars Tracked

1. **Sleep Consistency** — Bedtime & wake-time regularity
2. **Total Sleep Duration** — Average nightly hours asleep
3. **Daily Steps** — Daily step volume
4. **HR Zones 1–3 (Aerobic)** — Weekly moderate/fat-burn zone minutes
5. **HR Zones 4–5 (Vigorous)** — Weekly vigorous/peak zone minutes
6. **Strength Activities** — Weekly strength/weights workouts logged
7. **VO₂ Max** — Estimated maximal oxygen uptake
8. **Resting Heart Rate (RHR)** — Daily baseline RHR
9. **Lean Body Mass %** — From body fat logs (or optional manual input)
