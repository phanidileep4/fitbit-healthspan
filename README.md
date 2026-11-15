# Fitbit Healthspan

A WHOOP-inspired wellness dashboard using Google Health API v4 and Google OAuth + PKCE. It reads Fitbit/Google Health data and displays nine measurable wellness pillars with transparent experimental scoring.

**This is not a validated biological clock, a physiological aging-rate measurement, or WHOOP's proprietary algorithm.** Year impacts and pace coefficients are hand-selected product heuristics. Changing the label does not validate the underlying model.

## Run locally

Requires Python 3.12+:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open http://localhost:8765. Sample mode is immediately available. For live data, enable Google Health API in your Google Cloud project, configure the OAuth consent screen and read-only scopes, and register `http://localhost:8765/callback` as a Web application redirect URI. Either configure server credentials or enter your own credentials in the settings dialog.

## Vercel

Connect this Git repository to the `fitbit-healthspan` project. Static assets live in `public/`; `api/index.py` serves API routes. Python dependencies are installed from `requirements.txt`.

Environment variables:

| Variable | Purpose |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Server-managed Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Server-only Google OAuth client secret |
| `SESSION_ENCRYPTION_KEY` | Optional dedicated Fernet key; otherwise a domain-separated key is derived from the server OAuth secret |
| `APP_ORIGIN` | Optional fixed canonical origin, such as `https://fitbit-healthspan.vercel.app` |

Register `https://fitbit-healthspan.vercel.app/callback` in Google Cloud. Configure separate preview credentials and callback URLs if testing live OAuth on preview deployments. Without stable server secrets, production authorization fails closed. Local development without server secrets uses a process-scoped key, so restarting disconnects local sessions.

**Migration:** v2 rejects old unsigned `gh_session` cookies. Existing users must reconnect once. Rotating the encryption key or OAuth secret also requires reconnecting.

## Data behavior

- Fetches 180 **completed local calendar days**, excluding the current partial day; recent window is 30 days. Device interval offsets preserve local sleep times, including DST changes.
- Steps and moderate/vigorous/peak zone minutes use reconciled daily rollups in closed-open chunks of no more than 90 days. Light/out-of-zone minutes are not treated as moderate exercise. These provider zones are not presented as equivalent to a five-zone system.
- RHR and VO₂ use nested daily dates; body fat uses sample civil time or its offset. Sleep uses `summary.minutesAsleep`, main-sleep metadata, and local start/end offsets. Time in bed is never substituted for time asleep.
- List requests use time filters, actual sleep/exercise page limits, pagination, and a bounded sync budget. Independent metrics fetch concurrently.
- Sync diagnostics distinguish successful, empty, and failed sources. Unavailable sources do not silently imply poor health.
- Explicit zero-step observations are retained. Absent zone data does not imply zero exercise. An empty exercise history does not establish zero strength training; strength values count **logged** recognized resistance sessions. Generic `WORKOUT` and `CARDIO_WORKOUT` are not classified as strength.
- Sleep consistency uses circular clock-time dispersion. Daily pillars require 14 distinct recorded baseline/recent days before contributing; VO₂ requires one observation. Overall age and pace outputs require six available baseline/recent pillars respectively. These are conservative display rules, not scientifically validated thresholds.
- Missing pillars show no score. The composite score averages available pillars and is labeled accordingly. Sparse observations can still bias that average; do not compare it across substantially different coverage.
- The former interpolated age history is removed. Charts now show actual recorded metric series. Historical age tracking would require dated snapshots and model versioning.

## Privacy and security

OAuth sessions use authenticated Fernet encryption, HttpOnly, SameSite=Lax and Secure cookies on HTTPS. Cookies have size and lifetime limits. No health metrics or OAuth tokens are persisted to a server database. Dashboard summaries are cached per OAuth session in the browser tab's `sessionStorage`, with schema checking and stale refresh. Disconnect clears the app session and tab cache; revoke Google's authorization separately in Google Account permissions.

Callback query strings are omitted from app logs; callback error text is escaped. JSON requests have shape/size and profile validation, cross-origin POSTs are blocked, and responses use no-store and security headers. Vercel/platform access logs may still record request URLs; configure platform logging/retention appropriately.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check public/app.js
```

Tests use schema-shaped fixtures and do not require real health data or credentials. Live authentication and data availability must also be checked with the account holder after deployment. API schema reference: https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints

## Next enhancements

1. Per-pillar freshness and coverage calendars, plus deduplication and source provenance across devices.
2. Real daily/monthly snapshots with model versions and coverage-matched comparisons.
3. A methodology page with sourced, age/sex-appropriate reference ranges; scientifically evaluate or replace the age/pace heuristic.
4. User-selected goals and measured progress, optional exports, and clearly attributed manual measurements.
5. Accessibility improvements to modal focus management and charts, plus broader automated browser coverage.
