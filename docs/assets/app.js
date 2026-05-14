/* Elite Scanner 100 Dashboard
   Signal card policy: BUY SETUP ONLY
*/

const SIGNALS_URL = "data/signals.json";
const EXECUTION_URL = "data/execution.json";

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

function safe(value, fallback = "N/A") {
  if (value === undefined || value === null || value === "") return fallback;
  return value;
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
  return String(
    getValue(signal, ["decision", "status", "action", "label"], "")
  ).trim().toUpperCase();
}

function isBuySetup(signal) {
  return normalizeDecision(signal) === "BUY SETUP";
}

function normalizeSignals(payload) {
  if (!payload || typeof payload !== "object") return [];

  const raw =
    payload.signals ||
    payload.picks ||
    payload.opportunities ||
    payload.rows ||
    [];

  if (!Array.isArray(raw)) return [];

  return raw.map((signal) => {
    const advanced =
      signal.advanced_breakdown ||
      signal.breakdown ||
      signal.scores ||
      {};

    return {
      raw: signal,
      symbol: String(getValue(signal, ["symbol", "ticker"], "UNKNOWN")).toUpperCase(),
      decision: normalizeDecision(signal) || "WATCH ONLY",
      price: getValue(signal, ["price", "last_price", "current_price"], 0),
      dayMove: getValue(signal, ["day_move_pct", "change_pct", "pct_change"], 0),

      entry: getValue(signal, ["entry", "entry_goal", "entry_area", "buy_zone"], 0),
      betterEntry: getValue(signal, ["better_entry", "pullback_entry", "ideal_entry"], 0),
      stopLoss: getValue(signal, ["stop_loss", "stop", "sl"], 0),
      target1: getValue(signal, ["target_1", "target1", "tp1", "sell_target_1"], 0),
      target2: getValue(signal, ["target_2", "target2", "tp2", "sell_target_2"], 0),
      targetSource: getValue(signal, ["target_1_source", "target_source"], "N/A"),

      opportunityScore: getValue(signal, ["opportunity_score", "score", "total_score"], "N/A"),
      entryScore: getValue(signal, ["entry_score", "trade_score", "setup_score"], "N/A"),
      confidence: getValue(signal, ["confidence"], "N/A"),
      rr: getValue(signal, ["risk_reward", "rr", "risk_reward_ratio"], "N/A"),
      chaseRisk: getValue(signal, ["chase_risk"], "N/A"),
      tradeability: getValue(signal, ["tradeability"], "N/A"),
      vwapDistance: getValue(signal, ["vwap_distance_pct", "vwap_dist_pct", "vwap_distance"], "N/A"),
      volumeRatio: getValue(signal, ["volume_ratio", "vol_ratio", "relative_volume"], "N/A"),
      sectorEtf: getValue(signal, ["sector_etf"], "N/A"),
      sectorVsSpy: getValue(signal, ["sector_vs_spy_pct", "sector_vs_spy"], "N/A"),

      reason: getValue(signal, ["reason", "why", "summary"], "BUY SETUP found."),
      notes: Array.isArray(signal.notes) ? signal.notes : Array.isArray(signal.reasons) ? signal.reasons : [],

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

function scoreRow(label, item) {
  if (!item) {
    return `
      <div class="advanced-row">
        <div>
          <strong>${label}</strong>
          <p>No data yet</p>
        </div>
        <span>N/A</span>
      </div>
    `;
  }

  if (typeof item === "number") {
    return `
      <div class="advanced-row">
        <div>
          <strong>${label}</strong>
          <p>score driver</p>
        </div>
        <span>${grade(item)} · ${item}/100</span>
      </div>
    `;
  }

  if (typeof item === "object") {
    const score = item.score ?? item.value ?? item.points ?? "N/A";
    const text = item.reason || item.note || item.summary || item.label || "score driver";
    return `
      <div class="advanced-row">
        <div>
          <strong>${label}</strong>
          <p>${safe(text)}</p>
        </div>
        <span>${grade(score)} · ${score}/100</span>
      </div>
    `;
  }

  return `
    <div class="advanced-row">
      <div>
        <strong>${label}</strong>
        <p>${safe(item)}</p>
      </div>
      <span>N/A</span>
    </div>
  `;
}

function renderSignalCard(signal) {
  const notes = signal.notes.slice(0, 8).map((note) => `<span class="tag">${note}</span>`).join("");

  return `
    <article class="signal-card buy-only-card">
      <div class="card-top">
        <div>
          <h3>${signal.symbol}</h3>
          <p>Price ${money(signal.price)} · ${pct(signal.dayMove)} today</p>
        </div>
        <span class="decision-pill buy">BUY SETUP</span>
      </div>

      <p class="action-text">${safe(signal.reason)}</p>

      <div class="levels-grid">
        <div>
          <span>Entry Goal</span>
          <strong>${money(signal.entry)}</strong>
        </div>
        <div>
          <span>Better Entry</span>
          <strong>${money(signal.betterEntry)}</strong>
        </div>
        <div>
          <span>Stop Loss</span>
          <strong>${money(signal.stopLoss)}</strong>
        </div>
        <div>
          <span>Sell Target 1</span>
          <strong>${money(signal.target1)}</strong>
        </div>
        <div>
          <span>Sell Target 2</span>
          <strong>${money(signal.target2)}</strong>
        </div>
        <div>
          <span>Target Source</span>
          <strong>${safe(signal.targetSource)}</strong>
        </div>
      </div>

      <div class="score-grid">
        <div><span>Opportunity</span><strong>${signal.opportunityScore}/100</strong></div>
        <div><span>Entry</span><strong>${signal.entryScore}/100</strong></div>
        <div><span>Confidence</span><strong>${signal.confidence}</strong></div>
        <div><span>RR</span><strong>${signal.rr}</strong></div>
        <div><span>Chase Risk</span><strong>${signal.chaseRisk}</strong></div>
        <div><span>Tradeability</span><strong>${signal.tradeability}</strong></div>
        <div><span>VWAP Dist.</span><strong>${safe(signal.vwapDistance)}%</strong></div>
        <div><span>Vol Ratio</span><strong>${safe(signal.volumeRatio)}x</strong></div>
        <div><span>Sector ETF</span><strong>${signal.sectorEtf}</strong></div>
        <div><span>Sector vs SPY</span><strong>${safe(signal.sectorVsSpy)}%</strong></div>
      </div>

      <details class="advanced-box">
        <summary>Advanced Logic Breakdown</summary>
        <div class="advanced-content">
          ${scoreRow("Catalyst", signal.advanced.catalyst)}
          ${scoreRow("Technical", signal.advanced.technicals || signal.advanced.technical)}
          ${scoreRow("Volume / Liquidity", signal.advanced.volume_liquidity || signal.advanced.volume)}
          ${scoreRow("Relative Strength", signal.advanced.relative_strength)}
          ${scoreRow("Sector / Market", signal.advanced.sector_market || signal.advanced.sector)}
          ${scoreRow("Risk Quality", signal.advanced.risk_quality || signal.advanced.risk)}
          ${scoreRow("Execution Timing", signal.advanced.execution_timing || signal.advanced.execution)}
        </div>
      </details>

      <div class="tags">
        ${notes}
      </div>
    </article>
  `;
}

function renderTable(signals) {
  if (!signals.length) {
    return `
      <section class="panel">
        <h2>Simple Table</h2>
        <p class="empty">No BUY SETUP signals for the table right now.</p>
      </section>
    `;
  }

  const rows = signals.map((signal) => `
    <tr>
      <td>${signal.symbol}</td>
      <td><span class="decision-pill buy">BUY SETUP</span></td>
      <td>${money(signal.price)}</td>
      <td>${money(signal.entry)}</td>
      <td>${money(signal.betterEntry)}</td>
      <td>${money(signal.stopLoss)}</td>
      <td>${money(signal.target1)}</td>
      <td>${safe(signal.reason)}</td>
    </tr>
  `).join("");

  return `
    <section class="panel">
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
              <th>Why</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderStats(allSignals, buySignals, payload, execution) {
  const waitCount = allSignals.filter((s) => s.decision === "WAIT").length;
  const watchCount = allSignals.filter((s) => s.decision === "WATCH ONLY").length;
  const avoidCount = allSignals.filter((s) => s.decision === "AVOID").length;

  const market = payload.market_context || payload.market || {};
  const api = payload.api_budget || payload.api || {};
  const generatedAt = payload.generated_at || payload.updated_at || payload.last_updated || "N/A";

  return `
    <section class="hero">
      <div>
        <p class="eyebrow">Paper-only research dashboard</p>
        <h1>Elite Scanner 100/100</h1>
        <p>Signal cards are now filtered to <strong>BUY SETUP only</strong>. WAIT and WATCH names stay hidden from cards.</p>
      </div>
      <div class="hero-meta">
        <span>Updated</span>
        <strong>${generatedAt}</strong>
      </div>
    </section>

    <section class="grid panels">
      <div class="panel">
        <h2>Market Context</h2>
        <div class="mini-grid">
          <div><span>Regime</span><strong>${safe(market.regime || payload.regime)}</strong></div>
          <div><span>Market Phase</span><strong>${safe(payload.market_phase || market.phase)}</strong></div>
          <div><span>Data Health</span><strong>${safe(payload.data_health || "OK")}</strong></div>
        </div>
      </div>

      <div class="panel">
        <h2>Paper Trading + Telegram</h2>
        <div class="mini-grid">
          <div><span>Telegram Policy</span><strong>BUY SETUP ONLY</strong></div>
          <div><span>Paper Orders</span><strong>${safe(execution.paper_orders_this_run || execution.orders_this_run || 0)}</strong></div>
          <div><span>Mode</span><strong>Paper only</strong></div>
        </div>
      </div>

      <div class="panel">
        <h2>API Budget</h2>
        <div class="mini-grid">
          <div><span>Wide scan</span><strong>${safe(api.wide_scan || api.wide_scanned || "N/A")}</strong></div>
          <div><span>Deep scan</span><strong>${safe(api.deep_scan || api.deep_scanned || "N/A")}</strong></div>
          <div><span>Est. calls</span><strong>${safe(api.estimated_calls || api.est_data_calls || "N/A")}</strong></div>
        </div>
      </div>

      <div class="panel">
        <h2>Signal Counts</h2>
        <div class="mini-grid">
          <div><span>Buy Setups</span><strong>${buySignals.length}</strong></div>
          <div><span>Wait Hidden</span><strong>${waitCount}</strong></div>
          <div><span>Watch Hidden</span><strong>${watchCount}</strong></div>
          <div><span>Avoid Hidden</span><strong>${avoidCount}</strong></div>
        </div>
      </div>
    </section>
  `;
}

function renderApp(payload, execution) {
  const allSignals = normalizeSignals(payload);
  const buySignals = allSignals.filter(isBuySetup);

  const root =
    document.getElementById("app") ||
    document.getElementById("dashboard") ||
    document.querySelector("main") ||
    document.body;

  const cards = buySignals.length
    ? buySignals.map(renderSignalCard).join("")
    : `
      <section class="panel empty-panel">
        <h2>No BUY SETUP right now</h2>
        <p>The scanner is working, but nothing currently meets the buy rules.</p>
        <p>WAIT, WATCH ONLY, and AVOID names are hidden from Signal Cards to keep the dashboard clean.</p>
      </section>
    `;

  root.innerHTML = `
    ${renderStats(allSignals, buySignals, payload, execution)}

    <section class="panel explainer">
      <h2>How to read this</h2>
      <p><strong>BUY SETUP</strong> means the scanner found a valid setup with entry, stop loss, and sell targets.</p>
      <p><strong>No card</strong> means the stock is not buy-ready yet. It may still be WAIT or WATCH in the raw data.</p>
      <p>This dashboard is paper-only research. Confirm chart before acting.</p>
    </section>

    <section class="signal-section">
      <div class="section-title">
        <h2>Signal Cards</h2>
        <p>Showing BUY SETUP only.</p>
      </div>
      <div class="signal-grid">
        ${cards}
      </div>
    </section>

    ${renderTable(buySignals)}
  `;
}

async function loadJson(url, fallback = {}) {
  try {
    const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return fallback;
    return await response.json();
  } catch (error) {
    console.error(`Failed to load ${url}`, error);
    return fallback;
  }
}

async function initDashboard() {
  const [signalsPayload, executionPayload] = await Promise.all([
    loadJson(SIGNALS_URL, { signals: [], paper_only: true }),
    loadJson(EXECUTION_URL, { paper_only: true }),
  ]);

  renderApp(signalsPayload, executionPayload);
}

document.addEventListener("DOMContentLoaded", initDashboard);
