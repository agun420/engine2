/* ═══════════════════════════════════════════════════════
   Engine2 — Elite Scanner Dashboard  app.js
   ═══════════════════════════════════════════════════════ */

"use strict";

const SIGNALS_URL      = "data/signals.json";
const EXECUTION_URL    = "data/execution.json";
const PAPER_ACCT_URL   = "data/paper_account.json";
const REFRESH_SEC      = 90;
const CIRC             = 69.1;   // 2π × r (r=11) for SVG arc

/* ─── State ────────────────────────────────────────────── */
let _prevBuySymbols = new Set();
let _refreshTimer   = null;
let _countdown      = REFRESH_SEC;
let _sortCol        = "opportunity_score";
let _sortDir        = -1;
let _activeFilter   = "ALL";

/* ─── Utility helpers ──────────────────────────────────── */
const safe = (v, fb = "N/A") => (v === null || v === undefined || v === "") ? fb : v;
const num  = (v, fb = 0)     => { const n = Number(v); return isFinite(n) ? n : fb; };

function money(v) {
  const n = num(v, null);
  if (n === null) return "N/A";
  return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(v, { sign = true } = {}) {
  const n = num(v, null);
  if (n === null) return "N/A";
  const s = sign && n > 0 ? "+" : "";
  return s + n.toFixed(2) + "%";
}

function scoreGrade(s) {
  const n = num(s);
  if (n >= 90) return "s-a";
  if (n >= 80) return "s-b";
  if (n >= 65) return "s-c";
  if (n >= 50) return "s-d";
  return "s-f";
}

function scoreGradeLetter(s) {
  const n = num(s);
  if (n >= 90) return "A";
  if (n >= 80) return "B";
  if (n >= 65) return "C";
  if (n >= 50) return "D";
  return "F";
}

function factorColor(score) {
  const n = num(score);
  if (n >= 80) return "var(--green)";
  if (n >= 65) return "var(--accent)";
  if (n >= 50) return "var(--yellow)";
  return "var(--red)";
}

function decClass(d) {
  if (d === "BUY SETUP")  return "buy";
  if (d === "WAIT")       return "wait";
  if (d === "AVOID")      return "avoid";
  return "watch";
}

function chgClass(v) {
  const n = num(v);
  if (n > 0)  return "chg-up";
  if (n < 0)  return "chg-dn";
  return "";
}

/* ─── Data normalisation ───────────────────────────────── */
function gv(obj, keys, fb = null) {
  if (!obj || typeof obj !== "object") return fb;
  for (const k of keys) {
    if (obj[k] !== undefined && obj[k] !== null && obj[k] !== "") return obj[k];
  }
  if (obj.levels) {
    for (const k of keys) {
      if (obj.levels[k] !== undefined && obj.levels[k] !== null && obj.levels[k] !== "") return obj.levels[k];
    }
  }
  return fb;
}

function normalise(payload) {
  const raw = payload?.signals || payload?.picks || [];
  if (!Array.isArray(raw)) return [];

  return raw.map(s => {
    const lv  = s.levels || {};
    const adv = s.advanced_breakdown || {};
    const fac = adv.factors || {};
    const out = s.outcome_stats || {};
    const reasons = Array.isArray(s.reasons) ? s.reasons : [];

    return {
      symbol:       String(gv(s, ["symbol","ticker"], "?")).toUpperCase(),
      decision:     String(gv(s, ["decision","status","action"], "")).trim().toUpperCase() || "WATCH ONLY",
      price:        num(gv(s, ["price","last_price"], 0)),
      dayMove:      num(gv(s, ["day_change_pct","change_pct"], 0)),
      entry:        num(gv(s, ["entry"], lv.entry || 0)),
      betterEntry:  num(gv(s, ["better_entry"], lv.better_entry || 0)),
      stop:         num(gv(s, ["stop","stop_loss"], lv.stop || 0)),
      target1:      num(gv(s, ["target1","target_1"], lv.target1 || 0)),
      target2:      num(gv(s, ["target2","target_2"], lv.target2 || 0)),
      rr:           num(gv(s, ["risk_reward","rr"], lv.risk_reward || 0)),
      t1Source:     gv(s, ["target1_source"], lv.target1_source || ""),
      oppScore:     num(gv(s, ["opportunity_score","score"], 0)),
      entScore:     num(gv(s, ["entry_score","trade_score"], 0)),
      confidence:   gv(s, ["confidence_label","confidence"], "N/A"),
      chaseRisk:    gv(s, ["chase_risk"], "N/A"),
      tradeability: gv(s, ["tradeability"], "N/A"),
      lifecycle:    gv(s, ["lifecycle"], ""),
      atrPct:       num(gv(s, ["atr_pct"], 0)),
      dollarVol:    num(gv(s, ["dollar_volume"], 0)),
      dataAge:      num(gv(s, ["data_age_minutes"], 0)),
      // pipeline enrichment
      lgbmProba:    num(s.lightgbm_proba, 0),
      lgbmFlagged:  !!s.lightgbm_flagged,
      s3Squeeze:    num(s.s3_squeeze_risk, 0),
      s3Crowded:    num(s.s3_crowded_score, 0),
      s3Diverge:    num(s.s3_divergence, 0),
      s3Active:     !!s.s3_loophole_active,
      lcGalaxy:     num(s.lc_galaxy_score, 0),
      lcSentiment:  num(s.lc_sentiment, 0),
      lcVolume:     num(s.lc_social_volume, 0),
      scVelocity:   num(s.simcluster_velocity, 0),
      scBridging:   !!s.simcluster_bridging,
      vixScaled:    num(s.vix_scaled_sentiment, 0),
      svcScore:     num(s.svc_score, 0),
      vixRegime:    gv(s, ["vix_regime"], ""),
      fearGreed:    num(s.fear_greed_index, 0),
      // outcomes
      globalWinRate:  num(out.global_target1_rate_pct, 0),
      symbolWinRate:  num(out.symbol_target1_rate_pct, 0),
      globalSample:   num(out.global_sample_size, 0),
      // panel
      panelVerdict:   gv(s, ["panel_verdict"], ""),
      panelConf:      num(s.panel_confidence, 0),
      // text
      reason: gv(s, ["action_text","reason","why"], null) || reasons.slice(0,3).join("; ") || "Scanner signal.",
      reasons,
      factors: fac,
      advGrade: adv.grade || "",
      advComposite: num(adv.composite, 0),
    };
  });
}

/* ─── Topbar: clock + phase + VIX ─────────────────────── */
function startClock() {
  const el = document.getElementById("tb-clock");
  if (!el) return;
  function tick() {
    const now = new Date().toLocaleString("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    });
    el.textContent = now + " ET";
  }
  tick();
  setInterval(tick, 1000);
}

function updateTopbarMeta(payload) {
  const phase  = payload.market_phase || "";
  const pip    = payload.pipeline_status || {};
  const vix    = num(pip.vix, 0);
  const regime = pip.vix_regime || "";

  const phaseEl = document.getElementById("tb-phase");
  if (phaseEl) {
    phaseEl.textContent = phase || "—";
    phaseEl.className   = "tb-chip " + phaseClass(phase);
  }

  const vixEl = document.getElementById("tb-vix");
  if (vixEl) {
    vixEl.textContent = vix ? "VIX " + vix.toFixed(1) : "VIX —";
    vixEl.className   = "tb-chip vix-chip " + vixClass(regime);
  }
}

function phaseClass(p) {
  if (p.includes("BEST"))    return "on-green";
  if (p.includes("OPENING")) return "on-yellow";
  if (p.includes("CLOSED") || p.includes("PREMARKET")) return "";
  if (p.includes("LATE"))    return "on-yellow";
  return "";
}

function vixClass(r) {
  if (!r) return "";
  if (r === "LOW_VOL_BULL")  return "low";
  if (r === "NORMAL")        return "norm";
  if (r === "ELEVATED")      return "high";
  if (r === "HIGH_FEAR" || r === "CRISIS") return "fear";
  return "norm";
}

/* ─── Ticker strip ─────────────────────────────────────── */
function renderTicker(market) {
  const etfs = market.etf_changes || {};
  const always = {
    SPY: market.spy_change_pct,
    QQQ: market.qqq_change_pct,
    IWM: market.iwm_change_pct,
    ...etfs
  };

  const items = Object.entries(always)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([sym, chg]) => {
      const n = num(chg);
      const cls = n > 0 ? "t-up" : n < 0 ? "t-dn" : "t-flat";
      const sign = n > 0 ? "▲" : n < 0 ? "▼" : "●";
      return `<span class="ticker-item"><span class="t-sym">${sym}</span> <span class="${cls}">${sign}${Math.abs(n).toFixed(2)}%</span></span>`;
    });

  const inner = document.getElementById("ticker-inner");
  if (inner && items.length) inner.innerHTML = items.join("") + "&nbsp;&nbsp;&nbsp;&nbsp;" + items.join("");
}

/* ─── Pipeline status ──────────────────────────────────── */
function renderPipeline(payload) {
  const pip  = payload.pipeline_status || {};
  const mode = payload.scanner_mode || "";

  const phases = [
    { label: "Phase 1 · Data", on: true,                               tip: "yfinance · FINRA · Reddit · StockTwits · Fear&Greed" },
    { label: "Phase 2 · NLP",  on: mode.includes("MemeBERT"),          tip: "MemeBERT-LSTM temporal fusion" },
    { label: "Phase 3 · ReAct", on: false,                             tip: "Autonomous factor discovery (runs offline)" },
    { label: "Phase 4 · LightGBM", on: pip.lgbm_model_loaded === true, tip: "GOSS+EFB aggregation" },
    { label: "Phase 4 · Panel", on: pip.panel_review_enabled === true,  tip: "Multi-agent consensus" },
    { label: "Phase 5 · Backtest", on: false,                          tip: "Purged walk-forward (offline)" },
  ];

  return `
    <div class="pipeline-strip">
      ${phases.map(p => `
        <div class="phase-pill ${p.on ? "on" : ""}" title="${p.tip}">
          <i class="phase-dot"></i>${p.label}
        </div>
      `).join("")}
    </div>
  `;
}

/* ─── Stats strip ──────────────────────────────────────── */
function renderStats(all, payload, execution) {
  const buy   = all.filter(s => s.decision === "BUY SETUP").length;
  const wait  = all.filter(s => s.decision === "WAIT").length;
  const watch = all.filter(s => s.decision === "WATCH ONLY").length;
  const ab    = payload.api_budget || {};
  const out   = payload.summary   || {};
  const pip   = payload.pipeline_status || {};
  const vix   = num(pip.vix, 0);
  const sample = num(out.outcome_sample_size, 0);
  const winRate = num(out.target1_rate_pct, 0);
  const wide  = num(ab.wide_symbols_returned || ab.wide_symbols_requested, 0);
  const deep  = num(ab.deep_symbols_selected, 0);

  return `
    <div class="stats-strip">
      <div class="stat-box buy">
        <div class="s-label">BUY SETUP</div>
        <div class="s-value">${buy}</div>
        <div class="s-sub">Active picks</div>
      </div>
      <div class="stat-box wait">
        <div class="s-label">WAIT / WATCH</div>
        <div class="s-value">${wait + watch}</div>
        <div class="s-sub">On watchlist</div>
      </div>
      <div class="stat-box info">
        <div class="s-label">Win Rate</div>
        <div class="s-value">${winRate ? winRate.toFixed(1) + "%" : "—"}</div>
        <div class="s-sub">${sample} closed signals</div>
      </div>
      <div class="stat-box info">
        <div class="s-label">Scanned</div>
        <div class="s-value">${wide}</div>
        <div class="s-sub">${deep} deep-analysed</div>
      </div>
      <div class="stat-box ${vixClass(pip.vix_regime) === "fear" ? "warn" : "info"}">
        <div class="s-label">VIX</div>
        <div class="s-value">${vix ? vix.toFixed(1) : "—"}</div>
        <div class="s-sub">${pip.vix_regime || "—"}</div>
      </div>
      <div class="stat-box info">
        <div class="s-label">API Budget</div>
        <div class="s-value">${num(ab.estimated_data_calls, 0)}<span style="font-size:13px;color:var(--muted)">/${num(ab.max_data_calls_per_run, 0)}</span></div>
        <div class="s-sub">${ab.status || "OK"}</div>
      </div>
    </div>
  `;
}

/* ─── R:R bar ──────────────────────────────────────────── */
function renderRR(s) {
  const { entry, stop, target1, target2, rr } = s;
  if (!entry || !stop || !target1) return "";

  const risk   = Math.abs(entry - stop);
  const reward = Math.abs(target1 - entry);
  const total  = risk + reward;
  if (total === 0) return "";

  const riskPct   = (risk / total * 100).toFixed(1);
  const rewardPct = (reward / total * 100).toFixed(1);
  const stopChg   = ((stop / entry - 1) * 100).toFixed(2);
  const t1Chg     = ((target1 / entry - 1) * 100).toFixed(2);

  return `
    <div class="rr-section">
      <h4>Risk · Reward Visualisation</h4>
      <div class="rr-bar-wrap">
        <div class="rr-risk" style="width:${riskPct}%">
          <span>${money(stop)}</span>
        </div>
        <div class="rr-reward">
          <span>${money(target1)}</span>
        </div>
        <div class="rr-entry-pin" style="left:${riskPct}%" data-label="${money(entry)}"></div>
      </div>
      <div class="rr-footer">
        <span style="color:var(--red)">Stop ${stopChg}%</span>
        <span class="rr-ratio">R:R ${rr > 0 ? rr.toFixed(2) : "N/A"}:1</span>
        <span style="color:var(--green)">T1 +${t1Chg}%${target2 ? " · T2 " + money(target2) : ""}</span>
      </div>
    </div>
  `;
}

/* ─── Score bars ───────────────────────────────────────── */
function renderScores(s) {
  const items = [
    { label: "Opportunity",  val: s.oppScore },
    { label: "Entry Score",  val: s.entScore },
    { label: "Composite",    val: s.advComposite },
    { label: "LGBM Proba",   val: s.lgbmProba * 100 },
  ];

  return `
    <div class="score-section">
      ${items.map(it => {
        const g = scoreGrade(it.val);
        const n = num(it.val);
        return `
          <div class="score-item">
            <div class="sc-header">
              <span>${it.label}</span>
              <strong class="${g}">${n.toFixed(0)}${it.label === "LGBM Proba" ? "%" : "/100"}</strong>
            </div>
            <div class="sc-track"><div class="sc-fill ${g}" style="width:${Math.min(n,100)}%"></div></div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

/* ─── Enrichment chips ─────────────────────────────────── */
function renderEnrich(s) {
  const chips = [];

  // S3 squeeze loophole
  if (s.s3Active) {
    chips.push(`<span class="enrich-chip on-green"><i class="ec-icon">⚡</i>Squeeze +${s.s3Diverge.toFixed(1)}</span>`);
  } else if (s.s3Squeeze > 0) {
    chips.push(`<span class="enrich-chip"><i class="ec-icon">⚡</i>Squeeze ${s.s3Squeeze.toFixed(0)}</span>`);
  }

  // Social sentiment
  if (s.lcSentiment !== 0) {
    const cls = s.lcSentiment > 0.2 ? "on-green" : s.lcSentiment < -0.2 ? "on-red" : "on-blue";
    const lbl = s.lcSentiment > 0.2 ? "Bullish" : s.lcSentiment < -0.2 ? "Bearish" : "Neutral";
    chips.push(`<span class="enrich-chip ${cls}"><i class="ec-icon">💬</i>Social ${lbl}</span>`);
  }

  // SimClusters bridging
  if (s.scBridging) {
    chips.push(`<span class="enrich-chip on-purple"><i class="ec-icon">🌐</i>Bridging ×${s.scVelocity.toFixed(1)}/min</span>`);
  }

  // VIX regime
  if (s.vixRegime) {
    const vcls = { "LOW_VOL_BULL":"on-green","NORMAL":"on-blue","ELEVATED":"on-yellow","HIGH_FEAR":"on-red","CRISIS":"on-red" };
    chips.push(`<span class="enrich-chip ${vcls[s.vixRegime]||""}"><i class="ec-icon">📊</i>${s.vixRegime.replace("_"," ")}</span>`);
  }

  // Fear & Greed
  if (s.fearGreed > 0) {
    const fgCls = s.fearGreed >= 60 ? "on-green" : s.fearGreed <= 30 ? "on-red" : "on-blue";
    const fgLbl = s.fearGreed >= 70 ? "Greed" : s.fearGreed >= 55 ? "Neutral+" : s.fearGreed <= 25 ? "Fear" : "Neutral";
    chips.push(`<span class="enrich-chip ${fgCls}"><i class="ec-icon">😱</i>F&G ${s.fearGreed.toFixed(0)} · ${fgLbl}</span>`);
  }

  // Panel verdict
  if (s.panelVerdict && s.panelVerdict !== "ERROR") {
    const pCls = s.panelVerdict === "BUY" ? "on-green" : s.panelVerdict === "PASS" ? "on-red" : "on-yellow";
    chips.push(`<span class="enrich-chip ${pCls}"><i class="ec-icon">🤖</i>Panel ${s.panelVerdict} ${s.panelConf ? (s.panelConf*100).toFixed(0)+"%" : ""}</span>`);
  }

  // Symbol win rate
  if (s.symbolWinRate > 0) {
    const wCls = s.symbolWinRate >= 55 ? "on-green" : s.symbolWinRate <= 35 ? "on-red" : "";
    chips.push(`<span class="enrich-chip ${wCls}"><i class="ec-icon">📈</i>Sym win ${s.symbolWinRate.toFixed(0)}% (n=${num(s.globalSample)})</span>`);
  }

  // Data age warning
  if (s.dataAge > 30) {
    chips.push(`<span class="enrich-chip on-yellow"><i class="ec-icon">⚠</i>Data ${s.dataAge.toFixed(0)}m old</span>`);
  }

  if (!chips.length) return "";
  return `<div class="enrich-section">${chips.join("")}</div>`;
}

/* ─── Factor breakdown ─────────────────────────────────── */
function renderFactors(s, id) {
  const fac = s.factors;
  const keys = ["technical","volume_liquidity","relative_strength","catalyst","sector_market","risk_quality","execution_timing"];
  const labels = { technical:"Technical", volume_liquidity:"Vol / Liq", relative_strength:"Rel Strength", catalyst:"Catalyst", sector_market:"Sector", risk_quality:"Risk", execution_timing:"Timing" };

  const rows = keys.map(k => {
    const f = fac[k];
    if (!f) return "";
    const score = num(f.score || f.value, 0);
    const grade = f.grade || scoreGradeLetter(score);
    const notes = (f.notes || []).slice(0,2).join(" · ");
    return `
      <div class="factor-row" title="${notes}">
        <span class="f-name">${labels[k] || k}</span>
        <div class="f-track"><div class="f-fill" style="width:${score}%;background:${factorColor(score)}"></div></div>
        <span class="f-grade" style="color:${factorColor(score)}">${grade}</span>
      </div>
    `;
  }).join("");

  if (!rows) return "";

  return `
    <button class="breakdown-toggle" onclick="toggleBreakdown('${id}',this)">
      <i class="bd-arrow">▶</i> Advanced Factor Breakdown <span style="color:var(--muted);font-size:11px;margin-left:auto">Composite ${s.advComposite}/100 · ${s.advGrade}</span>
    </button>
    <div class="breakdown-body" id="${id}">
      ${rows}
    </div>
  `;
}

function toggleBreakdown(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  const open = el.classList.toggle("open");
  btn.classList.toggle("open", open);
}

/* ─── Tags ─────────────────────────────────────────────── */
function renderTags(s) {
  const tags = s.reasons.slice(0, 8);
  if (!tags.length) return "";
  return `<div class="card-tags">${tags.map(t => `<span class="c-tag">${t}</span>`).join("")}</div>`;
}

/* ─── Full BUY SETUP card ──────────────────────────────── */
function renderBuyCard(s, idx) {
  const bdId = `bd-${idx}`;
  const decCls = decClass(s.decision);
  const chgCls = chgClass(s.dayMove);

  return `
    <article class="sig-card buy-card">
      <div class="card-header">
        <div>
          <div class="card-symbol">${s.symbol}</div>
          <div class="card-meta">
            <span class="price-val">${money(s.price)}</span>
            &nbsp;
            <span class="${chgCls}">${s.dayMove > 0 ? "▲" : s.dayMove < 0 ? "▼" : "●"}${Math.abs(s.dayMove).toFixed(2)}%</span>
            &nbsp;·&nbsp; ${s.lifecycle || "SETUP"}
            ${s.chaseRisk && s.chaseRisk !== "N/A" ? ` &nbsp;·&nbsp; Chase: ${s.chaseRisk}` : ""}
          </div>
        </div>
        <div class="card-right">
          <span class="dec-badge ${decCls}">${s.decision}</span>
          <div class="lgbm-row">
            <span>LGBM</span>
            <div class="lgbm-track">
              <div class="lgbm-fill" style="width:${(s.lgbmProba*100).toFixed(0)}%"></div>
              <div class="lgbm-threshold" style="left:65%"></div>
            </div>
            <strong>${(s.lgbmProba*100).toFixed(0)}%</strong>
          </div>
        </div>
      </div>

      <div class="card-reason buy-reason">${safe(s.reason)}</div>

      ${renderRR(s)}

      <div class="levels-grid">
        <div class="lv-box lv-stop">  <span class="lv-label">Stop</span>   <span class="lv-val">${money(s.stop)}</span></div>
        <div class="lv-box lv-entry"> <span class="lv-label">Entry</span>  <span class="lv-val">${money(s.entry)}</span></div>
        <div class="lv-box lv-t1">    <span class="lv-label">Target 1</span><span class="lv-val">${money(s.target1)}</span></div>
        <div class="lv-box lv-t2">    <span class="lv-label">Target 2</span><span class="lv-val">${money(s.target2)}</span></div>
        <div class="lv-box lv-rr">    <span class="lv-label">R:R</span>    <span class="lv-val">${num(s.rr) ? s.rr.toFixed(2) : "N/A"}</span></div>
      </div>

      ${renderScores(s)}
      ${renderEnrich(s)}
      ${renderFactors(s, bdId)}
      ${renderTags(s)}
    </article>
  `;
}

/* ─── Compact WAIT card ────────────────────────────────── */
function renderWaitCard(s) {
  const chgCls = chgClass(s.dayMove);
  const decCls = decClass(s.decision);

  return `
    <div class="wait-card">
      <div>
        <div class="wc-sym">${s.symbol}</div>
        <span class="dec-badge ${decCls} wc-dec" style="font-size:9px;padding:3px 8px">${s.decision}</span>
      </div>
      <div class="wc-right">
        <div class="wc-price">
          ${money(s.price)}
          <span class="${chgCls}" style="font-size:11px;font-weight:700;margin-left:6px">${s.dayMove > 0 ? "▲" : "▼"}${Math.abs(s.dayMove).toFixed(2)}%</span>
        </div>
        ${s.betterEntry ? `<div class="wc-entry">Better entry: <strong>${money(s.betterEntry)}</strong></div>` : ""}
        <div class="wc-reason">${safe(s.reason)}</div>
        <div class="wc-scores">
          <span class="wc-score-chip">Opp ${s.oppScore}</span>
          <span class="wc-score-chip">Entry ${s.entScore}</span>
          ${s.rr ? `<span class="wc-score-chip">R:R ${s.rr.toFixed(2)}</span>` : ""}
          ${s.s3Active ? `<span class="wc-score-chip" style="color:var(--green)">⚡SQ</span>` : ""}
        </div>
      </div>
    </div>
  `;
}

/* ─── Win / outcome tracker ────────────────────────────── */
function renderOutcomes(payload) {
  const sum  = payload.summary || {};
  const win  = num(sum.target1_rate_pct, 0);
  const n    = num(sum.outcome_sample_size, 0);
  const avgPnl = num(sum.avg_pnl_pct_est, 0);

  // derive stop/expired roughly from signals state
  const closed = payload.signals
    ? payload.signals.filter(s => s.outcome === "closed" || s.lifecycle === "CLOSED")
    : [];

  const totalBars = 100;
  const winDash  = (win / 100 * Math.PI * 36 * 2).toFixed(1);
  const circumf  = (Math.PI * 36 * 2).toFixed(1);
  const winColor = win >= 55 ? "var(--green)" : win >= 40 ? "var(--yellow)" : "var(--red)";

  return `
    <div class="panel-card">
      <h3>Win Rate Tracker</h3>
      <p class="panel-sub">Closed signals only. Need 30+ for statistical confidence.</p>
      <div class="outcome-layout">
        <div>
          <svg class="win-ring" width="120" height="120" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="46" fill="none" stroke="var(--surface-3)" stroke-width="8"/>
            <circle cx="60" cy="60" r="46" fill="none" stroke="${winColor}" stroke-width="8"
              stroke-dasharray="${winDash} ${circumf}"
              stroke-linecap="round"
              transform="rotate(-90 60 60)"/>
            <text x="60" y="56" text-anchor="middle" fill="${winColor}" font-size="20" font-weight="900" font-family="Inter,sans-serif">${win ? win.toFixed(1)+"%" : "—"}</text>
            <text x="60" y="72" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="Inter,sans-serif">WIN RATE</text>
          </svg>
        </div>
        <div class="outcome-bars">
          <div>
            <div class="ob-header"><span>Target Hit</span><strong>${n ? (win/100*n).toFixed(0) : "—"}</strong></div>
            <div class="ob-track"><div class="ob-fill win" style="width:${win}%"></div></div>
          </div>
          <div>
            <div class="ob-header"><span>Stop Hit</span><strong>—</strong></div>
            <div class="ob-track"><div class="ob-fill lose" style="width:${win ? Math.max(0,100-win-20) : 0}%"></div></div>
          </div>
          <div>
            <div class="ob-header"><span>Expired / EOD</span><strong>—</strong></div>
            <div class="ob-track"><div class="ob-fill exp" style="width:20%"></div></div>
          </div>
        </div>
      </div>
      <div class="outcome-meta">
        <div class="om-item">
          <div class="om-label">Closed Signals</div>
          <div class="om-val">${n || "—"}</div>
        </div>
        <div class="om-item">
          <div class="om-label">Avg P&L Est.</div>
          <div class="om-val" style="color:${avgPnl >= 0 ? "var(--green)" : "var(--red)"}">
            ${avgPnl ? (avgPnl > 0 ? "+" : "") + avgPnl.toFixed(2) + "%" : "—"}
          </div>
        </div>
      </div>
      ${n < 30 ? `<p style="font-size:11px;color:var(--muted);margin-top:12px">⚠ ${n}/30 signals needed for statistical confidence. Keep running.</p>` : ""}
    </div>
  `;
}

/* ─── Paper account panel ──────────────────────────────── */
function renderAccount(account, execution) {
  const acct = account?.account || account || {};
  const positions = Array.isArray(account?.positions) ? account.positions : [];
  const equity = acct.equity ?? acct.portfolio_value;
  const cash   = acct.cash;
  const bp     = acct.buying_power;
  const pnl    = acct.unrealized_pl;
  const pnlPct = acct.unrealized_plpc;

  const pnlN  = num(pnl, null);
  const pnlCls = pnlN === null ? "" : pnlN >= 0 ? "pnl-up" : "pnl-dn";

  const posRows = positions.slice(0, 6).map(p => {
    const pl = num(p.unrealized_pl, null);
    const plCls = pl === null ? "" : pl >= 0 ? "pnl-up" : "pnl-dn";
    return `<tr>
      <td>${safe(p.symbol)}</td>
      <td>${safe(p.qty)}</td>
      <td>${money(p.market_value)}</td>
      <td class="${plCls}">${money(p.unrealized_pl)}</td>
    </tr>`;
  }).join("");

  const orders = num(execution?.orders_submitted_this_run || execution?.paper_orders_this_run, 0);
  const waitSent = num(execution?.wait_alerts_sent_this_run, 0);

  return `
    <div class="panel-card">
      <h3>Paper Account</h3>
      <p class="panel-sub">Alpaca paper trading — read-only snapshot.</p>
      <div class="acct-grid">
        <div class="ag-item"><div class="ag-label">Equity</div><div class="ag-val">${money(equity)}</div></div>
        <div class="ag-item"><div class="ag-label">Cash</div><div class="ag-val">${money(cash)}</div></div>
        <div class="ag-item"><div class="ag-label">Buying Power</div><div class="ag-val">${money(bp)}</div></div>
        <div class="ag-item"><div class="ag-label">Open P&L</div><div class="ag-val ${pnlCls}">${money(pnl)}</div></div>
        <div class="ag-item"><div class="ag-label">P&L %</div><div class="ag-val ${pnlCls}">${pnlPct !== undefined && pnlPct !== null ? pct(num(pnlPct)*100) : "N/A"}</div></div>
        <div class="ag-item"><div class="ag-label">Orders This Run</div><div class="ag-val">${orders}</div></div>
      </div>
      ${positions.length ? `
        <table class="positions-table">
          <thead><tr><th>Symbol</th><th>Qty</th><th>Value</th><th>P&L</th></tr></thead>
          <tbody>${posRows}</tbody>
        </table>
      ` : `<p style="font-size:12px;color:var(--muted);margin-top:12px">No open paper positions.</p>`}
      ${waitSent ? `<p style="font-size:11px;color:var(--muted);margin-top:10px">📨 ${waitSent} WAIT alert(s) sent this run.</p>` : ""}
    </div>
  `;
}

/* ─── All signals table ────────────────────────────────── */
function renderTable(all) {
  const filtered = _activeFilter === "ALL"
    ? all
    : all.filter(s => s.decision === _activeFilter);

  const sorted = [...filtered].sort((a, b) => {
    const va = a[_sortCol]; const vb = b[_sortCol];
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * _sortDir;
    return String(va).localeCompare(String(vb)) * _sortDir;
  });

  const counts = { "BUY SETUP": 0, "WAIT": 0, "WATCH ONLY": 0, "ALL": all.length };
  all.forEach(s => { if (counts[s.decision] !== undefined) counts[s.decision]++; });

  function sortTh(col, label) {
    const isSorted = _sortCol === col;
    return `<th onclick="setSort('${col}')" class="${isSorted ? "sorted" : ""}">${label}<span class="sort-arrow">${isSorted ? (_sortDir > 0 ? "▲" : "▼") : "⇅"}</span></th>`;
  }

  const rows = sorted.map(s => {
    const decCls = decClass(s.decision);
    const chgCls = chgClass(s.dayMove);
    return `<tr>
      <td class="td-sym">${s.symbol}</td>
      <td><span class="dec-badge ${decCls}" style="font-size:9px;padding:3px 8px">${s.decision}</span></td>
      <td class="td-mono">${money(s.price)}</td>
      <td class="td-mono ${chgCls}">${s.dayMove > 0 ? "+" : ""}${s.dayMove.toFixed(2)}%</td>
      <td class="td-mono">${money(s.entry)}</td>
      <td class="td-mono">${money(s.stop)}</td>
      <td class="td-mono">${money(s.target1)}</td>
      <td class="td-mono">${s.rr ? s.rr.toFixed(2) : "—"}</td>
      <td class="td-mono">${s.oppScore || "—"}</td>
      <td class="td-mono">${s.entScore || "—"}</td>
      <td class="td-mono">${(s.lgbmProba*100).toFixed(0)}%</td>
      <td class="td-why">${safe(s.reason).substring(0,120)}</td>
    </tr>`;
  }).join("");

  return `
    <div class="table-card">
      <div class="table-head">
        <h3>All Signals <span style="color:var(--muted);font-weight:500;font-size:12px">${filtered.length} showing</span></h3>
        <div class="filter-btns">
          ${["ALL","BUY SETUP","WAIT","WATCH ONLY"].map(f => `
            <button class="f-btn ${f === "BUY SETUP" ? "f-buy" : f === "WAIT" ? "f-wait" : ""} ${_activeFilter === f ? "active" : ""}"
              onclick="setFilter('${f}')">${f} ${counts[f] !== undefined ? "("+counts[f]+")" : ""}</button>
          `).join("")}
        </div>
      </div>
      <div class="sig-table-wrap">
        <table class="sig-table">
          <thead>
            <tr>
              ${sortTh("symbol",    "Symbol")}
              ${sortTh("decision",  "Decision")}
              ${sortTh("price",     "Price")}
              ${sortTh("dayMove",   "Day %")}
              ${sortTh("entry",     "Entry")}
              ${sortTh("stop",      "Stop")}
              ${sortTh("target1",   "Target 1")}
              ${sortTh("rr",        "R:R")}
              ${sortTh("oppScore",  "Opp")}
              ${sortTh("entScore",  "Entry Sc")}
              ${sortTh("lgbmProba", "LGBM %")}
              <th>Why</th>
            </tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="12" style="text-align:center;color:var(--muted);padding:24px">No signals match this filter.</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

/* sort / filter exposed on window for onclick handlers */
window.setSort = function(col) {
  if (_sortCol === col) _sortDir *= -1; else { _sortCol = col; _sortDir = -1; }
  reRenderTable();
};

window.setFilter = function(f) {
  _activeFilter = f;
  reRenderTable();
};

window.toggleBreakdown = toggleBreakdown;

let _lastAll = [];
function reRenderTable() {
  const el = document.getElementById("all-signals-table");
  if (el) el.innerHTML = renderTable(_lastAll);
}

/* ─── Notice bar ───────────────────────────────────────── */
function renderNotice(payload) {
  const phase = payload.market_phase || "";
  const dh    = payload.data_health || "OK";
  const warn  = payload.phase_warning || "";

  if (dh === "STALE WARNING") {
    return `<div class="notice-bar warn">⚠ Stale data — scanner may be outside market hours. Signals are reference only.</div>`;
  }
  if (phase.includes("CLOSED") || phase.includes("PREMARKET")) {
    return `<div class="notice-bar info">ℹ ${warn}</div>`;
  }
  return "";
}

/* ─── Main render ──────────────────────────────────────── */
function render(signals, execution, account) {
  const all  = normalise(signals);
  const buys = all.filter(s => s.decision === "BUY SETUP");
  const waits = all.filter(s => s.decision === "WAIT" || s.decision === "WATCH ONLY");
  _lastAll   = all;

  // Toast on new BUY SETUP
  const nowBuys = new Set(buys.map(s => s.symbol));
  nowBuys.forEach(sym => {
    if (!_prevBuySymbols.has(sym)) toast(`🔔 New BUY SETUP: ${sym}`, "t-buy");
  });
  _prevBuySymbols = nowBuys;

  const market = signals.market_context || {};
  const updAt  = signals.updated_at_et || signals.generated_at || signals.updated_at || "—";

  const buySection = buys.length
    ? `<div class="cards-grid">${buys.map((s,i) => renderBuyCard(s,i)).join("")}</div>`
    : `<div class="empty-card">
         <span class="ec-icon">🔍</span>
         <h3>No BUY SETUP right now</h3>
         <p>Scanner is running every 10 min. Check the watchlist below for WAIT signals approaching entry.</p>
       </div>`;

  const waitSection = waits.length ? `
    <div class="sec-head">
      <h2>Watchlist</h2>
      <span class="sec-count">${waits.length}</span>
      <p>WAIT / WATCH ONLY — monitor for entry</p>
    </div>
    <div class="wait-grid">${waits.map(renderWaitCard).join("")}</div>
  ` : "";

  document.getElementById("app").innerHTML = `
    ${renderNotice(signals)}

    ${renderPipeline(signals)}

    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:12px;flex-wrap:wrap">
      <div>
        <h1 style="font-size:22px;font-weight:900;letter-spacing:-.5px;margin:0">Engine2 Elite Scanner</h1>
        <p style="font-size:12px;color:var(--muted);margin:4px 0 0">Updated: <span style="color:var(--text-2)">${updAt}</span> &nbsp;·&nbsp; Paper-only research</p>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:11px;color:var(--muted)">${signals.scanner_mode ? "Mode: "+signals.scanner_mode.split("→")[0].trim() : ""}</span>
      </div>
    </div>

    ${renderStats(all, signals, execution)}

    <div class="sec-head">
      <h2>Active BUY SETUPs</h2>
      <span class="sec-count">${buys.length}</span>
    </div>
    ${buySection}

    ${waitSection}

    <div class="two-col" style="margin-top:24px">
      ${renderOutcomes(signals)}
      ${renderAccount(account, execution)}
    </div>

    <div id="all-signals-table">
      ${renderTable(all)}
    </div>
  `;

  renderTicker(market);
  updateTopbarMeta(signals);
}

/* ─── Toast system ─────────────────────────────────────── */
function toast(msg, cls = "t-info", dur = 5000) {
  const c  = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => {
    el.style.animation = "fade-out .3s ease forwards";
    setTimeout(() => el.remove(), 300);
  }, dur);
}

/* ─── Refresh countdown ring ───────────────────────────── */
function startRefreshRing() {
  _countdown = REFRESH_SEC;
  const arc = document.getElementById("refresh-arc");
  if (!arc) return;

  clearInterval(_refreshTimer);
  _refreshTimer = setInterval(() => {
    _countdown--;
    if (arc) {
      const progress = _countdown / REFRESH_SEC;
      arc.setAttribute("stroke-dashoffset", (CIRC * (1 - progress)).toFixed(2));
    }
    if (_countdown <= 0) {
      clearInterval(_refreshTimer);
      fetchAndRender().then(() => startRefreshRing());
    }
  }, 1000);
}

/* ─── Data fetching ────────────────────────────────────── */
async function loadJson(url, fb) {
  try {
    const r = await fetch(`${url}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } catch (e) {
    console.warn("load failed:", url, e);
    return fb;
  }
}

async function fetchAndRender() {
  const [signals, execution, account] = await Promise.all([
    loadJson(SIGNALS_URL,   { paper_only: true, signals: [] }),
    loadJson(EXECUTION_URL, { paper_only: true }),
    loadJson(PAPER_ACCT_URL,{ paper_only: true, positions: [], orders: [] }),
  ]);
  render(signals, execution, account);
}

/* ─── Boot ─────────────────────────────────────────────── */
async function init() {
  startClock();
  await fetchAndRender();
  startRefreshRing();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
