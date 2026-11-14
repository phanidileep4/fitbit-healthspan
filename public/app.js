let currentDashboard = null;
let activeCategory = "All";

const $ = (id) => document.getElementById(id);

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

function renderBioTrendChart(trend, chronoAge) {
  const svg = $("bioTrendChart");
  if (!trend || trend.length === 0) {
    svg.innerHTML = "";
    return;
  }

  const w = 360;
  const h = 140;
  const padX = 28;
  const padY = 20;

  const vals = trend.flatMap((d) => [d.biological_age, d.chronological_age]);
  const minV = Math.min(...vals) - 2;
  const maxV = Math.max(...vals) + 2;
  const span = Math.max(1, maxV - minV);

  const xFor = (i) => padX + (i / Math.max(1, trend.length - 1)) * (w - padX * 2);
  const yFor = (v) => h - padY - ((v - minV) / span) * (h - padY * 2);

  const bioPts = trend.map((d, i) => `${xFor(i).toFixed(1)},${yFor(d.biological_age).toFixed(1)}`).join(" ");
  const chronoY = yFor(chronoAge).toFixed(1);

  const circles = trend
    .map(
      (d, i) =>
        `<circle cx="${xFor(i).toFixed(1)}" cy="${yFor(d.biological_age).toFixed(1)}" r="3.5" fill="#00f19f" />`
    )
    .join("");

  const labels = trend
    .map((d, i) => {
      if (i !== 0 && i !== trend.length - 1 && i !== Math.floor(trend.length / 2)) return "";
      return `<text x="${xFor(i).toFixed(1)}" y="${h - 4}" fill="#8b98ab" font-size="9" text-anchor="middle">${d.label}</text>`;
    })
    .join("");

  svg.innerHTML = `
    <line x1="${padX}" y1="${chronoY}" x2="${w - padX}" y2="${chronoY}" stroke="#607087" stroke-width="1.5" stroke-dasharray="4 4" />
    <polyline fill="none" stroke="#00f19f" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${bioPts}" />
    ${circles}
    ${labels}
  `;
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
              <div class="pillar-cat">${p.category}</div>
              <div class="pillar-name">${p.name}</div>
            </div>
            <span class="impact-chip ${impactClass(p.year_impact)}">${formatImpact(p.year_impact)}</span>
          </div>

          <div class="pillar-metrics">
            <div>
              <span class="pillar-main-val">${valText}</span>
              <span class="pillar-unit">${p.unit}</span>
            </div>
            <span class="pillar-recent">${recText}</span>
          </div>

          <div class="bar-track">
            <div class="bar-fill" style="width: ${p.score_0_100}%; background: ${color};"></div>
          </div>

          ${renderSparkline(p.recent_series, color)}

          <div class="pillar-footer">
            <span>Target: ${p.target_label}</span>
            <span>Score: ${Math.round(p.score_0_100)}/100</span>
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
  if (data.data_source === "fitbit_live") {
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
  if (cfg.manual_lean_pct) $("leanPctInput").value = cfg.manual_lean_pct;
  if (cfg.client_id) $("clientIdInput").value = cfg.client_id;

  // Biological Age Hero
  $("bioAgeValue").textContent = data.biological_age.toFixed(1);
  $("chronoAgeLabel").textContent = data.chronological_age;

  const delta = data.age_delta;
  const deltaPill = $("ageDeltaPill");
  deltaPill.textContent = `${delta > 0 ? "+" : ""}${delta.toFixed(1)} yrs`;
  deltaPill.className = `delta-pill ${delta <= -1 ? "delta-good" : delta <= 1 ? "delta-warn" : "delta-bad"}`;

  // Ring progress (map healthspan score 0..100 to circumference 578)
  const ring = $("bioRingProgress");
  const circ = 578;
  const offset = circ - (Math.min(100, Math.max(0, data.overall_score)) / 100) * circ;
  ring.style.strokeDashoffset = offset.toFixed(1);
  ring.style.stroke = delta <= 0 ? "var(--emerald)" : delta <= 2 ? "var(--amber)" : "var(--coral)";

  renderBioTrendChart(data.bio_trend, data.chronological_age);

  // Pace of Aging Hero
  const pace = data.pace_of_aging;
  $("paceValue").textContent = `${pace.toFixed(2)}x`;
  $("overallScoreValue").textContent = `${data.overall_score} / 100`;
  $("activePillarsValue").textContent = `${data.active_pillar_count} / 9`;

  const pacePill = $("paceStatusPill");
  const paceArc = $("paceArcFg");
  const paceNorm = Math.min(1, Math.max(0, (pace - 0.5) / 1.0)); // 0.5x..1.5x
  paceArc.style.strokeDashoffset = (314 - paceNorm * 314).toFixed(1);

  if (pace < 0.95) {
    pacePill.textContent = "Slowing Aging";
    pacePill.className = "delta-pill delta-good";
    paceArc.style.stroke = "var(--emerald)";
    $("paceDescription").textContent = "Your recent 30-day habits are actively slowing your physiological pace of aging.";
  } else if (pace <= 1.08) {
    pacePill.textContent = "Steady Pace";
    pacePill.className = "delta-pill delta-warn";
    paceArc.style.stroke = "var(--amber)";
    $("paceDescription").textContent = "You are aging at roughly chronological speed. Improving sleep consistency or vigorous cardio will lower this.";
  } else {
    pacePill.textContent = "Accelerated";
    pacePill.className = "delta-pill delta-bad";
    paceArc.style.stroke = "var(--coral)";
    $("paceDescription").textContent = "Recent recovery, sleep, or activity load is elevated—focus on sleep duration and aerobic recovery.";
  }

  renderPillars(data.pillars || []);
}

async function loadDashboard() {
  const hint = $("callbackUriHint");
  if (hint) hint.textContent = `${window.location.origin}/callback`;

  const res = await fetch("/api/dashboard");
  const data = await res.json();
  const params = new URLSearchParams(window.location.search);

  if (data.config && data.config.connected) {
    if (params.get("connected") === "1") {
      window.history.replaceState({}, "", "/");
      renderDashboard(data);
      await syncNow();
      return;
    }
    const cached = localStorage.getItem("gh_cached_dashboard");
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        parsed.config = data.config;
        renderDashboard(parsed);
        return;
      } catch (_) {}
    }
    renderDashboard(data);
    await syncNow();
    return;
  }

  localStorage.removeItem("gh_cached_dashboard");
  renderDashboard(data);
}

async function saveProfile() {
  const chrono = Number($("chronoAgeInput").value) || 33;
  const leanRaw = $("leanPctInput").value;
  const body = {
    chronological_age: chrono,
    manual_lean_pct: leanRaw ? Number(leanRaw) : 0,
  };
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  renderDashboard(data);
}

async function startAuth() {
  const clientId = $("clientIdInput").value.trim();
  const clientSecret = $("clientSecretInput").value.trim();
  const errBox = $("modalError");
  errBox.classList.add("hidden");

  if (!clientId) {
    errBox.textContent = "Please enter your Fitbit OAuth 2.0 Client ID.";
    errBox.classList.remove("hidden");
    return;
  }

  const res = await fetch("/api/auth/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });
  const data = await res.json();
  if (data.error) {
    errBox.textContent = data.error;
    errBox.classList.remove("hidden");
    return;
  }
  window.location.href = data.auth_url;
}

async function syncNow() {
  const btn = $("syncBtn");
  btn.textContent = "Syncing...";
  btn.disabled = true;
  try {
    const res = await fetch("/api/sync", { method: "POST", body: "{}" });
    const data = await res.json();
    if (data.error) {
      alert(`Sync error: ${data.error}`);
    } else {
      localStorage.setItem("gh_cached_dashboard", JSON.stringify(data));
      renderDashboard(data);
    }
  } finally {
    btn.textContent = "Sync Fitbit";
    btn.disabled = false;
  }
}

async function disconnectFitbit() {
  localStorage.removeItem("gh_cached_dashboard");
  const res = await fetch("/api/disconnect", { method: "POST", body: "{}" });
  const data = await res.json();
  $("connectModal").classList.add("hidden");
  renderDashboard(data);
}

// Event listeners
$("saveProfileBtn").addEventListener("click", saveProfile);
$("syncBtn").addEventListener("click", syncNow);
$("connectBtn").addEventListener("click", () => $("connectModal").classList.remove("hidden"));
$("closeModalBtn").addEventListener("click", () => $("connectModal").classList.add("hidden"));
$("authorizeBtn").addEventListener("click", startAuth);
$("disconnectBtn").addEventListener("click", disconnectFitbit);

$("categoryFilters").addEventListener("click", (e) => {
  const btn = e.target.closest(".filter-btn");
  if (!btn) return;
  document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  activeCategory = btn.dataset.cat;
  if (currentDashboard) renderPillars(currentDashboard.pillars || []);
});

loadDashboard();
