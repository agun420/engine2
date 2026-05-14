const SIGNALS_URL = "data/signals.json";
const EXECUTION_URL = "data/execution.json";

function safe(value, fallback = "N/A") {
  if (value === undefined || value === null || value === "") return fallback;
  return value;
}

function number(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "N/A";
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `${n.toFixed(2)}%`;
}

function getValue(obj, keys, fallback = null) {
  if (!obj || typeof obj !== "object") return fallback;

  for (const key of keys) {
    if (obj[key] !== undefined && obj[key] !== null && obj[key] !== "") {
      return obj[key];
    }
  }

  if (obj.levels && typeof obj.levels === "object") {
    for (const key of keys) {
      if (obj.levels[key] !== undefined && obj.levels[key] !== null && obj.levels[key] !== "") {
        return obj.levels[key];
      }
    }
  }

  return fallback;
}

function normalizeDecision(signal) {
  return String(getValue(signal, ["decision", "status", "action", "label"], ""))
    .trim()
    .toUpperCase();
}

function normalizeSignals(payload) {
  const raw =
    payload?.signals ||
    payload?.picks ||
    payload?.opportunities ||
    payload?.rows ||
    [];

  if (!Array.isArray(raw)) return [];

  return raw.map((s) => {
    const advanced = s.advanced_breakdown || s.breakdown || s.scores || {};
    const notes = Array.isArray(s.notes) ? s.notes : Array.isArray(s.reasons) ? s.reasons : [];

    return {
      symbol: String(getValue(s, ["symbol", "ticker"], "UNKNOWN")).toUpperCase(),
      decision: normalizeDecision(s) || "WATCH ONLY",
      price: getValue(s, ["price", "last_price", "current_price"], 0),
      dayMove: getValue(s, ["day_move_pct", "change_pct", "pct_change"], 0),
      entry: getValue(s, ["entry", "entry_goal", "entry_area", "buy_zone"], 0),
      betterEntry: getValue(s, ["better_entry", "pullback_entry", "ideal_entry"], 0),
      stopLoss: getValue(s, ["stop_loss", "stop", "sl"], 0),
      target1: getValue(s, ["target_1", "target1", "tp1", "sell_target_1"], 0),
      target2: getValue(s, ["target_2", "target2", "tp2", "sell_target_2"], 0),
      targetSource: getValue(s, ["target_1_source", "target_source"], "N/A"),
      opportunityScore: getValue(s, ["opportunity_score", "score", "total_score"], "N/A"),
      entryScore: getValue(s, ["entry_score", "trade_score", "setup_score"], "N/A"),
      confidence: getValue(s, ["confidence"], "N/A"),
      rr: getValue(s, ["risk_reward", "rr", "risk_reward_ratio"], "N/A"),
      chaseRisk: getValue(s, ["chase_risk"], "N/A"),
      tradeability: getValue(s, ["tradeability"], "N/A"),
      vwapDistance: getValue(s, ["vwap_distance_pct", "vwap_dist_pct", "vwap_distance"], "N/A"),
      volumeRatio: getValue(s, ["volume_ratio", "vol_ratio", "relative_volume"], "N/A"),
      sectorEtf: getValue(s, ["sector_etf"], "N/A"),
      sectorVsSpy: getValue(s, ["sector_vs_spy_pct", "sector_vs_spy"], "N/A"),
      reason:
        getValue(s, ["reason", "why", "summary"], null) ||
        notes.slice(0, 3).join("; ") ||
        "BUY SETUP found.",
      notes,
      advanced,
    };
  });
}

function grade(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "N/A";
  if (n >= 90) return "A";
  if (n >= 80) return "B";
  if (n >= 65) return "C";
  if (n >= 50) return "D";
  return "F";
}

function advancedRow(label, item) {
  if (!item) {
    return `<div class="adv-row"><span>${label}</span><strong>N/A</strong><p>No data yet</p></div>`;
  }

  if (typeof item === "number") {
    return `<div class="adv-row"><span>${label}</span><strong>${grade(item)} · ${item}/100</strong><p>Score driver</p></div>`;
  }

  if (typeof item === "object") {
    const score = item.score ?? item.value ?? item.points ?? "N/A";
    const text = item.reason || item.note || item.summary || item.label || "Score driver";
    return `<div class="adv-row"><span>${label}</span><strong>${grade(score)} · ${score}/100</strong><p>${safe(text)}</p></div>`;
  }

  return `<div class="adv-row"><span>${label}</span><strong>N/A</strong><p>${safe(item)}</p></div>`;
}

function renderCard(s) {
  const notes = s.notes
    .slice(0, 8)
    .map((note) => `<span class="tag">${note}</span>`)
    .join("");

  return `
    <article class="card signal-card">
      <div class="card-head">
        <div>
          <h3>${s.symbol}</h3>
          <p>${money(s.price)} · ${pct(s.dayMove)} today</p>
        </div>
        <span class="pill buy">BUY SETUP</span>
      </div>

      <p class="action">${safe(s.reason)}</p>

      <div class="levels">
        <div><span>Entry</span><strong>${money(s.entry)}</strong></div>
        <div><span>Better Entry</span><strong>${money(s.betterEntry)}</strong></div>
        <div><span>Stop Loss</span><strong>${money(s.stopLoss)}</strong></div>
        <div><span>Target 1</span><strong>${money(s.target1)}</strong></div>
        <div><span>Target 2</span><strong>${money(s.target2)}</strong></div>
        <div><span>Target Source</span><strong>${safe(s.targetSource)}</strong></div>
      </div>

      <div class="metrics">
        <div><span>Opportunity</span><strong>${safe(s.opportunityScore)}/100</strong></div>
        <div><span>Entry</span><strong>${safe(s.entryScore)}/100</strong></div>
        <div><span>Confidence</span><strong>${safe(s.confidence)}</strong></div>
        <div><span>RR</span><strong>${safe(s.rr)}</strong></div>
        <div><span>Chase Risk</span><strong>${safe(s.chaseRisk)}</strong></div>
        <div><span>Tradeability</span><strong>${safe(s.tradeability)}</strong></div>
      </div>

      <details class="advanced">
        <summary>Advanced Logic Breakdown</summary>
        ${advancedRow("Catalyst", s.advanced.catalyst)}
        ${advancedRow("Technical", s.advanced.technicals || s.advanced.technical)}
        ${advancedRow("Volume / Liquidity", s.advanced.volume_liquidity || s.advanced.volume)}
        ${advancedRow("Relative Strength", s.advanced.relative_strength)}
        ${advancedRow("Sector / Market", s.advanced.sector_market || s.advanced.sector)}
        ${advancedRow("Risk Quality", s.advanced.risk_quality || s.advanced.risk)}
        ${advancedRow("Execution Timing", s.advanced.execution_timing || s.advanced.execution)}
      </details>

      <div class="tags">${notes}</div>
    </article>
  `;
}

function renderTable(signals) {
  if (!signals.length) {
    return `
      <section class="card">
        <h2>Simple Table</h2>
        <p class="muted">No BUY SETUP signals right now.</p>
      </section>
    `;
  }

  const rows = signals.map((s) => `
    <tr>
      <td>${s.symbol}</td>
      <td><span class="pill buy">BUY SETUP</span></td>
      <td>${money(s.price)}</td>
      <td>${money(s.entry)}</td>
      <td>${money(s.betterEntry)}</td>
      <td>${money(s.stopLoss)}</td>
      <td>${money(s.target1)}</td>
    </tr>
  `).join("");

  return `
    <section class="card">
      <h2>Simple Table</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Decision</th>
              <th>Price</th>
              <th>Entry</th>
              <th>Better Entry</th>
              <th>Stop</th>
              <th>Target 1</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function apiDisplay(api) {
  const wideUsed = api.wide_scan_used ?? api.wide_scanned ?? api.wide_scan_count ?? api.wide_scan;
  const wideMax = api.wide_scan_limit ?? api.wide_limit;
  const deepUsed = api.deep_scan_used ?? api.deep_scanned ?? api.deep_scan_count ?? api.deep_scan;
  const deepMax = api.deep_scan_limit ?? api.deep_limit;
  const callsUsed = api.estimated_calls ?? api.est_data_calls ?? api.data_calls;
  const callsMax = api.max_data_calls ?? api.call_limit;

  return {
    mode: api.mode || api.status || "N/A",
    wide: wideMax ? `${wideUsed}/${wideMax}` : safe(wideUsed),
    deep: deepMax ? `${deepUsed}/${deepMax}` : safe(deepUsed),
    calls: callsMax ? `${callsUsed}/${callsMax}` : safe(callsUsed),
  };
}

function render(payload, execution) {
  const all = normalizeSignals(payload);
  const buys = all.filter((s) => s.decision === "BUY SETUP");
  const waitCount = all.filter((s) => s.decision === "WAIT").length;
  const watchCount = all.filter((s) => s.decision === "WATCH ONLY").length;
  const avoidCount = all.filter((s) => s.decision === "AVOID").length;

  const market = payload.market_context || payload.market || {};
  const api = apiDisplay(payload.api_budget || payload.api || {});
  const updated = payload.generated_at || payload.updated_at || payload.last_updated || payload.timestamp || "N/A";

  const cards = buys.length
    ? buys.map(renderCard).join("")
    : `
      <section class="empty-state card">
        <h2>No BUY SETUP right now</h2>
        <p>The scanner is working, but nothing currently meets the buy rules.</p>
        <p>WAIT, WATCH ONLY, and AVOID names are hidden to keep the dashboard clean.</p>
      </section>
    `;

  document.getElementById("app").innerHTML = `
    <section class="hero">
      <div>
        <p class="eyebrow">Paper-only research dashboard</p>
        <h1>Elite Scanner 100/100</h1>
        <p>BUY SETUP-only dashboard. Clean view for action-ready names.</p>
      </div>
      <div class="updated-box">
        <span>Updated</span>
        <strong>${updated}</strong>
      </div>
    </section>

    <section class="notice">
      <strong>Important:</strong> Paper-only research. Auto paper trading only runs when
      <code>AUTO_PAPER_TRADE=true</code>. Never use live keys.
    </section>

    <section class="top-grid">
      <div class="card">
        <h2>Market Context</h2>
        <div class="mini-grid">
          <div><span>Regime</span><strong>${safe(market.regime || payload.regime)}</strong></div>
          <div><span>Phase</span><strong>${safe(market.phase || payload.market_phase)}</strong></div>
          <div><span>Data</span><strong>${safe(payload.data_health || payload.data_status || "OK")}</strong></div>
          <div><span>SPY</span><strong>${pct(market.spy_change_pct ?? market.spy ?? market.SPY)}</strong></div>
          <div><span>QQQ</span><strong>${pct(market.qqq_change_pct ?? market.qqq ?? market.QQQ)}</strong></div>
          <div><span>IWM</span><strong>${pct(market.iwm_change_pct ?? market.iwm ?? market.IWM)}</strong></div>
        </div>
      </div>

      <div class="card">
        <h2>Paper + Telegram</h2>
        <div class="mini-grid">
          <div><span>Policy</span><strong>BUY ONLY</strong></div>
          <div><span>Orders</span><strong>${safe(execution.paper_orders_this_run || execution.orders_this_run || 0)}</strong></div>
          <div><span>Mode</span><strong>Paper only</strong></div>
        </div>
      </div>

      <div class="card">
        <h2>API Budget</h2>
        <div class="mini-grid">
          <div><span>Mode</span><strong>${api.mode}</strong></div>
          <div><span>Wide</span><strong>${api.wide}</strong></div>
          <div><span>Deep</span><strong>${api.deep}</strong></div>
          <div><span>Calls</span><strong>${api.calls}</strong></div>
        </div>
      </div>

      <div class="card">
        <h2>Signal Counts</h2>
        <div class="mini-grid">
          <div><span>Buy</span><strong>${buys.length}</strong></div>
          <div><span>Wait Hidden</span><strong>${waitCount}</strong></div>
          <div><span>Watch Hidden</span><strong>${watchCount}</strong></div>
          <div><span>Avoid Hidden</span><strong>${avoidCount}</strong></div>
        </div>
      </div>
    </section>

    <section class="section-head">
      <h2>Signal Cards</h2>
      <p>Showing BUY SETUP only.</p>
    </section>

    <section class="cards-grid">
      ${cards}
    </section>

    ${renderTable(buys)}
  `;
}

async function loadJson(url, fallback) {
  try {
    const res = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`Failed to load ${url}`, err);
    return fallback;
  }
}

async function init() {
  const [signals, execution] = await Promise.all([
    loadJson(SIGNALS_URL, { paper_only: true, signals: [] }),
    loadJson(EXECUTION_URL, { paper_only: true }),
  ]);

  render(signals, execution);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
