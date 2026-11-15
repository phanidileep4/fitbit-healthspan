let currentDashboard = null;
let activeCategory = "All";

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message, error = false) {
  const el = $("syncNotice"); el.textContent = message; el.classList.toggle("error-box", error);
}
async function request(path, body) {
  const res = await fetch(path, body === undefined ? {cache:"no-store"} : {
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)
  });
  let data;
  try { data = await res.json(); } catch { throw new Error("The server did not return a valid response. Please retry."); }
  if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status}).`);
  return data;
}
function cachedDashboard() {
  try { return JSON.parse(sessionStorage.getItem("gh_dashboard_v2") || "null"); } catch { return null; }
}
function cacheDashboard(data) {
  try { sessionStorage.setItem("gh_dashboard_v2", JSON.stringify(data)); } catch { /* Private browsing can disable storage. */ }
}

function statusColor(status) {
  if (status === "optimal") return "var(--emerald)";
  if (status === "good") return "var(--amber)";
  if (status === "attention") return "var(--coral)";
  return "#475569";
}

function impactClass(yr) {
  if (yr < -0.1) return "delta-good";
  if (yr <= 0.3) return "delta-warn";
  return "delta-bad";
}

function formatImpact(yr) {
  if (yr === 0) return "0.0 yrs";
  return `${yr > 0 ? "+" : ""}${yr.toFixed(1)} yrs`;
}

function renderRecordedTrend(pillars) {
  const select = $("trendMetric");
  const previous = select.value;
  const available = pillars.filter(p => p.recent_series?.length >= 2);
  select.replaceChildren();
  for (const pillar of available) {
    const option = document.createElement("option"); option.value = pillar.id;
    option.textContent = `${pillar.name} (${pillar.unit})`; select.append(option);
  }
  if (available.some(p => p.id === previous)) select.value = previous;
  const pillar = available.find(p => p.id === select.value);
  const svg = $("bioTrendChart");
  if (!pillar) {
    svg.innerHTML = '<text x="180" y="65" text-anchor="middle" fill="#8b98ab" font-size="11">No recorded trend available.</text>';
    return;
  }
  const series = pillar.recent_series;
  const values = series.map(d => Number(d.value));
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(1, max - min);
  const first = Date.parse(series[0].date), last = Date.parse(series.at(-1).date);
  const points = series.map((d, i) => `${(30 + ((Date.parse(d.date)-first)/Math.max(86400000,last-first))*300).toFixed(1)},${(108-(values[i]-min)/span*80).toFixed(1)}`).join(" ");
  svg.innerHTML = `<polyline fill="none" stroke="#00f19f" stroke-width="2.5" points="${points}"/>
    <text x="8" y="20" fill="#8b98ab" font-size="10">${max}</text>
    <text x="8" y="112" fill="#8b98ab" font-size="10">${min}</text>
    <text x="30" y="135" fill="#8b98ab" font-size="10">${escapeHtml(series[0].date)}</text>
    <text x="330" y="135" text-anchor="end" fill="#8b98ab" font-size="10">${escapeHtml(series.at(-1).date)}</text>`;
}

function renderSparkline(series, color) {
  if (!series || series.length < 2) {
    return `<div class="pillar-footer"><span>No 30-day time series</span></div>`;
  }
  const w = 240;
  const h = 36;
  const vals = series.map((s) => Number(s.value));
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const span = Math.max(0.01, maxV - minV);

  const pts = vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - 4 - ((v - minV) / span) * (h - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return `
    <svg viewBox="0 0 ${w} ${h}" class="sparkline" preserveAspectRatio="none">
      <polyline fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${pts}" />
    </svg>
  `;
}

function renderPillars(pillars) {
  const grid = $("pillarsGrid");
  const filtered = activeCategory === "All"
    ? pillars
    : pillars.filter((p) => p.category === activeCategory);

  grid.innerHTML = filtered
    .map((p) => {
      const color = statusColor(p.status);
      const valText = p.baseline_value !== null && p.baseline_value !== undefined
        ? p.baseline_value.toLocaleString()
        : "—";
      const recText = p.recent_value !== null && p.recent_value !== undefined
        ? `${p.recent_value.toLocaleString()} ${p.unit} (30d)`
        : "No recent data";

      return `
        <div class="pillar-card">
          <div class="pillar-top">
            <div>
              <div class="pillar-cat">${escapeHtml(p.category)}</div>
              <div class="pillar-name">${escapeHtml(p.name)}</div>
            </div>
            <span class="impact-chip ${impactClass(p.year_impact)}">${p.status === "no_data" ? "Unavailable" : formatImpact(p.year_impact)}</span>
          </div>

          <div class="pillar-metrics">
            <div>
              <span class="pillar-main-val">${valText}</span>
              <span class="pillar-unit">${p.unit}</span>
            </div>
            <span class="pillar-recent">${recText}</span>
          </div>

          <div class="bar-track">
            <div class="bar-fill" style="width: ${p.score_0_100 ?? 0}%; background: ${color};"></div>
          </div>

          ${renderSparkline(p.recent_series, color)}
          <p class="coverage-detail">${p.baseline_days !== undefined ? `${p.baseline_days} baseline days · ${p.recent_days} recent days` : escapeHtml(p.description)}</p>

          <div class="pillar-footer">
            <span>Target: ${p.target_label}</span>
            <span>Score: ${p.score_0_100 == null ? "—" : Math.round(p.score_0_100) + "/100"}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderDashboard(data) {
  currentDashboard = data;
  const cfg = data.config || {};

  // Topbar status
  const badge = $("sourceBadge");
  if (cfg.connected) {
    badge.textContent = cfg.user_name ? `Fitbit Live · ${cfg.user_name}` : "Fitbit Live";
    badge.className = "badge badge-live";
    $("syncBtn").classList.remove("hidden");
    $("connectBtn").textContent = "Fitbit Settings";
    $("disconnectBtn").classList.remove("hidden");
  } else {
    badge.textContent = "Sample Preview";
    badge.className = "badge badge-preview";
    $("syncBtn").classList.add("hidden");
    $("connectBtn").textContent = "Connect Fitbit";
    $("disconnectBtn").classList.add("hidden");
  }

  $("chronoAgeInput").value = data.chronological_age;
  $("leanPctInput").value = cfg.manual_lean_pct ?? "";
  if (cfg.client_id) $("clientIdInput").value = cfg.client_id;

  // Biological Age Hero
  $("bioAgeValue").textContent = data.biological_age == null ? "—" : data.biological_age.toFixed(1);
  $("chronoAgeLabel").textContent = data.chronological_age;

  const delta = data.age_delta;
  const deltaPill = $("ageDeltaPill");
  deltaPill.textContent = delta == null ? "Insufficient data" : `${delta > 0 ? "+" : ""}${delta.toFixed(1)} yrs`;
  deltaPill.className = `delta-pill ${delta == null ? "delta-warn" : delta <= -1 ? "delta-good" : delta <= 1 ? "delta-warn" : "delta-bad"}`;

  // Ring progress (map healthspan score 0..100 to circumference 578)
  const ring = $("bioRingProgress");
  const circ = 578;
  const offset = circ - (Math.min(100, Math.max(0, data.overall_score)) / 100) * circ;
  ring.style.strokeDashoffset = offset.toFixed(1);
  ring.style.stroke = delta <= 0 ? "var(--emerald)" : delta <= 2 ? "var(--amber)" : "var(--coral)";

  renderRecordedTrend(data.pillars || []);

  // Pace of Aging Hero
  const pace = data.pace_of_aging;
  $("paceValue").textContent = pace == null ? "—" : `${pace.toFixed(2)}x`;
  $("overallScoreValue").textContent = data.overall_score == null ? "—" : `${data.overall_score} / 100 (available data)`;
  $("activePillarsValue").textContent = `${data.active_pillar_count} / 9`;

  const pacePill = $("paceStatusPill");
  const paceArc = $("paceArcFg");
  const paceNorm = Math.min(1, Math.max(0, (pace - 0.5) / 1.0)); // 0.5x..1.5x
  paceArc.style.strokeDashoffset = (314 - paceNorm * 314).toFixed(1);

  if (pace == null) {
    pacePill.textContent = "Insufficient data";
    pacePill.className = "delta-pill delta-warn";
    paceArc.style.strokeDashoffset = "314";
    $("paceDescription").textContent = "More recent measurements are needed before showing an experimental pace index.";
  } else if (pace < 0.95) {
    pacePill.textContent = "Lower index";
    pacePill.className = "delta-pill delta-good";
    paceArc.style.stroke = "var(--emerald)";
    $("paceDescription").textContent = "Recent metrics produce a lower experimental wellness index. This does not measure your physiological aging rate.";
  } else if (pace <= 1.08) {
    pacePill.textContent = "Steady Pace";
    pacePill.className = "delta-pill delta-warn";
    paceArc.style.stroke = "var(--amber)";
    $("paceDescription").textContent = "Recent metrics produce a near-baseline experimental wellness index.";
  } else {
    pacePill.textContent = "Higher index";
    pacePill.className = "delta-pill delta-bad";
    paceArc.style.stroke = "var(--coral)";
    $("paceDescription").textContent = "Recent metrics produce a higher experimental wellness index. Review the measured pillars below.";
  }

  $("coverageNotice").textContent = data.coverage_message || "Sample data for exploring the dashboard.";
  $("syncDetails").replaceChildren();
  for (const item of data.diagnostics || []) {
    const row = document.createElement("li");
    row.textContent = `${item.metric}: ${item.status} · ${item.records} records${item.message ? " · " + item.message : ""}`;
    $("syncDetails").append(row);
  }
  $("dataWindow").textContent = data.data_source === "sample_preview" ? "Illustrative sample data · Connect Google Health for your measurements." : data.window ? `${data.window.start} to ${data.window.end_exclusive} (end exclusive) · Last sync: ${cfg.last_synced || "unknown"}` : "";
  renderPillars(data.pillars || []);
}

async function loadDashboard() {
  $("callbackUriHint").textContent = `${window.location.origin}/callback`;
  // Retire the old persistent cache, which was not scoped to an account.
  try { localStorage.removeItem("gh_cached_dashboard"); } catch {}
  const data = await request("/api/dashboard");
  const params = new URLSearchParams(window.location.search);
  if (data.config?.connected) {
    const cached = cachedDashboard();
    if (cached?.config?.cache_id === data.config.cache_id && cached?.model_version === "wellness-heuristic-v2" && params.get("connected") !== "1") {
      cached.config = data.config; renderDashboard(cached);
      const age = Date.now() - Date.parse(data.config.last_synced || "");
      notice("Showing your last successful sync.");
      if (!Number.isFinite(age) || age > 15 * 60 * 1000) await syncNow();
    } else {
      // Never show fictional sample health scores as a connected account's result.
      renderDashboard({...data, biological_age:null, age_delta:null, pace_of_aging:null, overall_score:null, pillars:[], active_pillar_count:0, bio_trend:[], coverage_message:"Connected. Retrieving your measurements…"});
      await syncNow();
    }
    window.history.replaceState({}, "", "/");
  } else {
    try { sessionStorage.removeItem("gh_dashboard_v2"); } catch {}
    renderDashboard(data);
  }
}

async function saveProfile() {
  const btn = $("saveProfileBtn"); btn.disabled = true;
  try {
    const data = await request("/api/config", {chronological_age:Number($("chronoAgeInput").value),
      manual_lean_pct:$("leanPctInput").value ? Number($("leanPctInput").value) : 0,
      timezone:Intl.DateTimeFormat().resolvedOptions().timeZone});
    if (data.config?.connected) {
      notice("Profile saved. Syncing updated calculations…"); await syncNow();
    } else renderDashboard(data);
  } catch (err) { notice(err.message, true); }
  finally { btn.disabled = false; }
}

async function startAuth(useServerCreds = false) {
  const clientId = useServerCreds ? "" : $("clientIdInput").value.trim();
  const clientSecret = useServerCreds ? "" : $("clientSecretInput").value.trim();
  const errBox = $("modalError");
  if (errBox) errBox.classList.add("hidden");

  if (!useServerCreds && !clientId) {
    errBox.textContent = "Please enter your Google OAuth Client ID.";
    errBox.classList.remove("hidden");
    return;
  }

  const res = await fetch("/api/auth/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone }),
  });
  const data = await res.json();
  if (data.error) {
    if (errBox) {
      errBox.textContent = data.error;
      errBox.classList.remove("hidden");
    } else {
      notice(data.error, true);
    }
    return;
  }
  window.location.href = data.auth_url;
}

async function syncNow() {
  const btn = $("syncBtn"); btn.textContent = "Syncing…"; btn.disabled = true;
  notice("Fetching your measurements…");
  try {
    const data = await request("/api/sync", {});
    cacheDashboard(data); renderDashboard(data);
    const errors = (data.diagnostics || []).filter(d => d.status === "error").length;
    notice(errors ? `Sync completed with ${errors} failed sources. See sync details below.` : "Sync complete. Only recorded measurements contribute to your results.", errors > 0);
  } catch (err) { notice(`Sync failed: ${err.message} Your previous result has been kept.`, true); }
  finally { btn.textContent = "Sync Fitbit"; btn.disabled = false; }
}

async function disconnectFitbit() {
  try {
    const data = await request("/api/disconnect", {});
    try { sessionStorage.removeItem("gh_dashboard_v2"); } catch {}
    $("connectModal").classList.add("hidden"); renderDashboard(data);
    notice("Disconnected and cleared this tab’s cached dashboard. To revoke Google's grant, visit Google Account permissions.");
  } catch (err) { notice(err.message, true); }
}

$("trendMetric").addEventListener("change", () => { if (currentDashboard) renderRecordedTrend(currentDashboard.pillars || []); });

// Event listeners
$("saveProfileBtn").addEventListener("click", saveProfile);
$("syncBtn").addEventListener("click", syncNow);
$("connectBtn").addEventListener("click", () => {
  const cfg = currentDashboard && currentDashboard.config;
  if (cfg && cfg.has_server_credentials && !cfg.connected) {
    startAuth(true).catch(err => notice(err.message, true));
    return;
  }
  $("connectModal").classList.remove("hidden");
});
$("closeModalBtn").addEventListener("click", () => $("connectModal").classList.add("hidden"));
$("authorizeBtn").addEventListener("click", () => startAuth(false).catch(err => notice(err.message, true)));
$("disconnectBtn").addEventListener("click", disconnectFitbit);

$("categoryFilters").addEventListener("click", (e) => {
  const btn = e.target.closest(".filter-btn");
  if (!btn) return;
  document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  activeCategory = btn.dataset.cat;
  if (currentDashboard) renderPillars(currentDashboard.pillars || []);
});

loadDashboard().catch(err => notice(err.message, true));
