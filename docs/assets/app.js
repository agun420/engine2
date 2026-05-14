const SIGNALS_URL = "data/signals.json";
const EXECUTION_URL = "data/execution.json";
const PAPER_ACCOUNT_URL = "data/paper_account.json";

function safe(value, fallback = "N/A") {
  if (value === undefined || value === null || value === "") return fallback;
  return value;
}

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `${n.toFixed(2)}%`;
}

function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
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
    const notes = Array.isArray(s.notes)
      ? s.notes
      : Array.isArray(s.reasons)
      ? s.reasons
      : [];

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
        "Scanner signal.",
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

function pillClass(decision) {
  if (decision === "BUY SETUP") return "buy";
  if (decision === "WAIT") return "wait";
  if (decision === "AVOID") return "avoid";
  return "watch";
}

function getGeneratedAt(payload) {
  return (
    payload.generated_at ||
    payload.updated_at ||
    payload.last_updated ||
    payload.timestamp ||
    payload.as_of ||
    payload.scanner_meta?.generated_at ||
    payload.meta?.generated_at ||
    payload.meta?.updated_at ||
    "No timestamp yet"
  );
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

function renderSimpleTable(allSignals) {
  if (!allSignals.length) {
    return `
      <section class="card">
        <h2>Simple Table</h2>
        <p class="muted">No scanner signals available yet.</p>
      </section>
    `;
  }

  const rows = allSignals.map((s) => `
    <tr>
      <td>${s.symbol}</td>
      <td><span class="pill ${pillClass(s.decision)}">${s.decision}</span></td>
      <td>${money(s.price)}</td>
      <td>${money(s.entry)}</td>
      <td>${money(s.betterEntry)}</td>
      <td>${money(s.stopLoss)}</td>
      <td>${money(s.target1)}</td>
      <td>${safe(s.rr)}</td>
      <td>${safe(s.reason)}</td>
    </tr>
  `).join("");

  return `
    <section class="card">
      <div class="table-title">
        <div>
          <h2>Simple Table</h2>
          <p class="muted">Showing all signals: BUY SETUP, WAIT, WATCH ONLY, and AVOID.</p>
        </div>
        <span class="small-badge">${allSignals.length} total</span>
      </div>
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
              <th>RR</th>
              <th>Why</th>
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
    wide: wideMax ? `${safe(wideUsed, 0)}/${wideMax}` : safe(wideUsed),
    deep: deepMax ? `${safe(deepUsed, 0)}/${deepMax}` : safe(deepUsed),
    calls: callsMax ? `${safe(callsUsed, 0)}/${callsMax}` : safe(callsUsed),
    callsUsed: num(callsUsed),
    callsMax: num(callsMax),
  };
}

function renderHealthPanel(payload, execution, allSignals) {
  const api = apiDisplay(payload.api_budget || payload.api || {});
  const dataHealth = payload.data_health || payload.data_status || "OK";
  const generatedAt = getGeneratedAt(payload);
  const buyCount = allSignals.filter((s) => s.decision === "BUY SETUP").length;
  const waitCount = allSignals.filter((s) => s.decision === "WAIT").length;

  const apiPct = api.callsMax > 0 ? Math.min(100, Math.round((api.callsUsed / api.callsMax) * 100)) : 0;

  return `
    <section class="card health-card">
      <div class="table-title">
        <div>
          <h2>Dashboard Health</h2>
          <p class="muted">Checks if the scanner, data, API budget, Telegram, and paper mode look healthy.</p>
        </div>
        <span class="status-dot ${String(dataHealth).toUpperCase() === "OK" ? "ok" : "warn"}">${safe(dataHealth)}</span>
      </div>

      <div class="health-grid">
        <div><span>Last Update</span><strong>${generatedAt}</strong></div>
        <div><span>Data Health</span><strong>${safe(dataHealth)}</strong></div>
        <div><span>API Budget</span><strong>${api.calls}</strong><div class="bar"><i style="width:${apiPct}%"></i></div></div>
        <div><span>Buy Setups</span><strong>${buyCount}</strong></div>
        <div><span>Wait Signals</span><strong>${waitCount}</strong></div>
        <div><span>Telegram Policy</span><strong>${safe(execution.telegram_policy || "BUY SETUP ONLY")}</strong></div>
        <div><span>Auto Paper</span><strong>${execution.auto_paper_trade === true ? "ON" : "OFF"}</strong></div>
        <div><span>Paper Orders This Run</span><strong>${safe(execution.paper_orders_this_run || execution.orders_this_run || 0)}</strong></div>
      </div>
    </section>
  `;
}

function renderLearningPanel(payload) {
  const learning =
    payload.learning ||
    payload.self_learning ||
    payload.outcome_summary ||
    payload.performance ||
    {};

  const sample = num(
    learning.sample_size ??
    learning.closed_signals ??
    learning.total_closed ??
    payload.outcome_sample ??
    0
  );

  const winRate = num(
    learning.win_rate ??
    learning.target_hit_rate ??
    learning.success_rate ??
    0
  );

  const targetHits = num(learning.target_hits ?? learning.wins ?? 0);
  const stops = num(learning.stop_hits ?? learning.losses ?? 0);
  const expired = num(learning.expired ?? 0);

  const scoreThreshold = safe(
    learning.min_entry_score ||
    learning.current_entry_threshold ||
    learning.entry_threshold ||
    "80"
  );

  const confidenceText =
    sample < 20
      ? "Learning mode is collecting data. Do not trust win rate yet."
      : "Enough sample is starting to build. Review before changing thresholds.";

  return `
    <section class="card learning-card">
      <div class="table-title">
        <div>
          <h2>Self-Learning Process</h2>
          <p class="muted">Tracks closed signals. Adaptive learning should only start after 20–30 closed outcomes.</p>
        </div>
        <span class="small-badge">${sample} closed</span>
      </div>

      <div class="learning-layout">
        <div class="donut" style="--value:${Math.min(100, Math.max(0, winRate))}">
          <div>
            <strong>${winRate ? `${winRate.toFixed(1)}%` : "N/A"}</strong>
            <span>Success Rate</span>
          </div>
        </div>

        <div class="learning-bars">
          <div>
            <span>Target Hits</span>
            <strong>${targetHits}</strong>
            <div class="bar"><i style="width:${sample ? Math.min(100, (targetHits / sample) * 100) : 0}%"></i></div>
          </div>
          <div>
            <span>Stops</span>
            <strong>${stops}</strong>
            <div class="bar danger"><i style="width:${sample ? Math.min(100, (stops / sample) * 100) : 0}%"></i></div>
          </div>
          <div>
            <span>Expired / EOD</span>
            <strong>${expired}</strong>
            <div class="bar neutral"><i style="width:${sample ? Math.min(100, (expired / sample) * 100) : 0}%"></i></div>
          </div>
        </div>
      </div>

      <div class="health-grid compact">
        <div><span>Learning Status</span><strong>${sample >= 20 ? "Ready for guardrails" : "Collecting data"}</strong></div>
        <div><span>Current Entry Threshold</span><strong>${scoreThreshold}</strong></div>
        <div><span>Next Action</span><strong>${sample >= 20 ? "Review adaptive guard" : "Keep collecting"}</strong></div>
      </div>

      <p class="muted learning-note">${confidenceText}</p>
    </section>
  `;
}

function renderAlpacaPanel(account, execution) {
  const acct = account?.account || account || {};
  const positions = Array.isArray(account?.positions) ? account.positions : [];
  const orders = Array.isArray(account?.orders) ? account.orders : [];

  const equity = acct.equity ?? acct.portfolio_value ?? account?.equity;
  const cash = acct.cash ?? account?.cash;
  const buyingPower = acct.buying_power ?? account?.buying_power;
  const pnl = acct.unrealized_pl ?? account?.unrealized_pl ?? account?.pnl;
  const pnlPct = acct.unrealized_plpc ?? account?.unrealized_plpc;

  const successRate =
    account?.success_rate ??
    account?.paper_success_rate ??
    execution?.success_rate ??
    execution?.paper_success_rate ??
    null;

  const positionRows = positions.slice(0, 5).map((p) => `
    <tr>
      <td>${safe(p.symbol)}</td>
      <td>${safe(p.qty)}</td>
      <td>${money(p.market_value)}</td>
      <td>${money(p.unrealized_pl)}</td>
    </tr>
  `).join("");

  return `
    <section class="card alpaca-card">
      <div class="table-title">
        <div>
          <h2>Alpaca Paper Dashboard</h2>
          <p class="muted">Shows account value, cash, buying power, open positions, and paper performance when data is exported.</p>
        </div>
        <span class="status-dot ok">Paper</span>
      </div>

      <div class="health-grid">
        <div><span>Equity</span><strong>${money(equity)}</strong></div>
        <div><span>Cash</span><strong>${money(cash)}</strong></div>
        <div><span>Buying Power</span><strong>${money(buyingPower)}</strong></div>
        <div><span>Open P/L</span><strong>${money(pnl)}</strong></div>
        <div><span>Open P/L %</span><strong>${pnlPct === null || pnlPct === undefined ? "N/A" : pct(Number(pnlPct) * 100)}</strong></div>
        <div><span>Success Rate</span><strong>${successRate === null || successRate === undefined ? "N/A" : pct(successRate)}</strong></div>
        <div><span>Open Positions</span><strong>${positions.length}</strong></div>
        <div><span>Recent Orders</span><strong>${orders.length}</strong></div>
      </div>

      <div class="table-wrap mini-table">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Qty</th>
              <th>Value</th>
              <th>Open P/L</th>
            </tr>
          </thead>
          <tbody>
            ${positionRows || `<tr><td colspan="4">No open paper positions exported yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function render(payload, execution, paperAccount) {
  const all = normalizeSignals(payload);
  const buys = all.filter((s) => s.decision === "BUY SETUP");
  const waitCount = all.filter((s) => s.decision === "WAIT").length;
  const watchCount = all.filter((s) => s.decision === "WATCH ONLY").length;
  const avoidCount = all.filter((s) => s.decision === "AVOID").length;

  const market = payload.market_context || payload.market || {};
  const api = apiDisplay(payload.api_budget || payload.api || {});
  const updated = getGeneratedAt(payload);

  const cards = buys.length
    ? buys.map(renderCard).join("")
    : `
      <section class="empty-state card">
        <h2>No BUY SETUP right now</h2>
        <p>The scanner is working, but nothing currently meets the buy rules.</p>
        <p>WAIT, WATCH ONLY, and AVOID names are still shown in the Simple Table below.</p>
      </section>
    `;

  document.getElementById("app").innerHTML = `
    <section class="hero">
      <div>
        <p class="eyebrow">Paper-only research dashboard</p>
        <h1>Elite Scanner 100/100</h1>
        <p>Main cards show <strong>BUY SETUP only</strong>. Simple Table shows every scanner signal.</p>
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
          <div><span>Auto Paper</span><strong>${execution.auto_paper_trade === true ? "ON" : "OFF"}</strong></div>
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
          <div><span>Wait</span><strong>${waitCount}</strong></div>
          <div><span>Watch</span><strong>${watchCount}</strong></div>
          <div><span>Avoid</span><strong>${avoidCount}</strong></div>
        </div>
      </div>
    </section>

    ${renderHealthPanel(payload, execution, all)}

    <section class="two-col">
      ${renderLearningPanel(payload)}
      ${renderAlpacaPanel(paperAccount, execution)}
    </section>

    <section class="section-head">
      <h2>Signal Cards</h2>
      <p>Showing BUY SETUP only.</p>
    </section>

    <section class="cards-grid">
      ${cards}
    </section>

    ${renderSimpleTable(all)}
  `;
}

async function loadJson(url, fallback) {
  try {
    const res = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`Could not load ${url}`, err);
    return fallback;
  }
}

async function init() {
  const [signals, execution, paperAccount] = await Promise.all([
    loadJson(SIGNALS_URL, { paper_only: true, signals: [] }),
    loadJson(EXECUTION_URL, { paper_only: true }),
    loadJson(PAPER_ACCOUNT_URL, { paper_only: true, positions: [], orders: [] }),
  ]);

  render(signals, execution, paperAccount);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
