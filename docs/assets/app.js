const money = (n) => Number(n || 0).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
const pct = (n) => n === null || n === undefined ? 'N/A' : `${Number(n || 0).toFixed(2)}%`;

function badgeClass(decision) {
  if (decision === 'BUY SETUP') return 'buy';
  if (decision === 'WAIT') return 'wait';
  if (decision === 'AVOID') return 'avoid';
  return 'watch';
}

function safeJoin(list, limit = 5, cls = 'tag') {
  return (list || []).slice(0, limit).map(r => `<span class="${cls}">${r}</span>`).join('');
}


function titleCaseFactor(name) {
  return String(name || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function makeAdvancedBreakdown(s) {
  const adv = s.advanced_breakdown || {};
  const factors = adv.factors || {};
  const rows = Object.entries(factors).map(([name, f]) => {
    const score = Number(f.score || 0);
    const notes = (f.notes || []).slice(0, 2).join(' · ');
    return `
      <div class="factor-row">
        <div class="factor-top">
          <strong>${titleCaseFactor(name)}</strong>
          <span>${f.grade || 'N/A'} · ${score}/100</span>
        </div>
        <div class="factor-bar"><i style="width:${Math.max(0, Math.min(100, score))}%"></i></div>
        <p>${notes || 'No detail available.'}</p>
      </div>
    `;
  }).join('');

  return `
    <details class="advanced" open>
      <summary>Advanced Logic Breakdown <span>${adv.grade || 'N/A'} · ${adv.composite ?? 'N/A'}/100</span></summary>
      <p class="advanced-summary">${adv.summary || 'Advanced factor details show what is driving the signal.'}</p>
      <div class="factor-grid">${rows || '<p class="sub">Advanced factors load after the scanner runs.</p>'}</div>
    </details>
  `;
}

function outcomeText(s) {
  const st = s.outcome_stats || {};
  if (!st.global_sample_size) return 'No outcome history yet. Paper-test before trusting scores.';
  return `${st.global_target1_rate_pct}% target-1 hit rate across ${st.global_sample_size} tracked setups`;
}

function makeCard(s) {
  const reasons = safeJoin(s.reasons, 5, 'tag');
  const warns = safeJoin(s.warnings, 4, 'tag warn');
  const t1Source = s.levels.target1_source ? `<div class="source">Target 1 source: ${s.levels.target1_source}</div>` : '';
  return `
    <article class="card ${badgeClass(s.decision)}-border">
      <div class="card-head">
        <div>
          <div class="symbol">${s.symbol}</div>
          <div class="price">Price ${money(s.price)} · ${pct(s.day_change_pct)} today</div>
        </div>
        <span class="badge ${badgeClass(s.decision)}">${s.decision}</span>
      </div>

      <div class="action">${s.action_text || 'Review setup before acting.'}</div>

      <div class="levels">
        <div class="level main"><span>Entry Area</span><strong>${money(s.levels.entry)}</strong></div>
        <div class="level"><span>Better Entry</span><strong>${money(s.levels.better_entry)}</strong></div>
        <div class="level danger"><span>Stop Loss</span><strong>${money(s.levels.stop)}</strong></div>
        <div class="level"><span>Target 1</span><strong>${money(s.levels.target1)}</strong></div>
        <div class="level"><span>Target 2</span><strong>${money(s.levels.target2)}</strong></div>
      </div>
      ${t1Source}

      <div class="metrics">
        <div class="metric"><span>Opportunity</span><strong>${s.opportunity_score}/100</strong></div>
        <div class="metric"><span>Entry</span><strong>${s.entry_score}/100</strong></div>
        <div class="metric"><span>Confidence</span><strong>${s.confidence_label}</strong></div>
        <div class="metric"><span>RR</span><strong>${s.levels.risk_reward}</strong></div>
        <div class="metric"><span>Chase Risk</span><strong>${s.chase_risk}</strong></div>
        <div class="metric"><span>Tradeability</span><strong>${s.tradeability}</strong></div>
        <div class="metric"><span>VWAP Dist.</span><strong>${pct(s.vwap_distance_pct)}</strong></div>
        <div class="metric"><span>Vol Ratio</span><strong>${Number(s.volume_ratio || 0).toFixed(2)}x</strong></div>
        <div class="metric"><span>Sector ETF</span><strong>${s.sector_context?.sector_etf || 'N/A'}</strong></div>
        <div class="metric"><span>Sector vs SPY</span><strong>${pct(s.sector_context?.sector_vs_spy_pct)}</strong></div>
      </div>

      ${makeAdvancedBreakdown(s)}
      <div class="outcome">${outcomeText(s)}</div>
      <div class="tags">${reasons}${warns}</div>
    </article>
  `;
}

function makeRow(s) {
  const why = [...(s.reasons || []).slice(0, 2), ...(s.warnings || []).slice(0, 1)].join('; ');
  return `
    <tr>
      <td><strong>${s.symbol}</strong></td>
      <td><span class="mini ${badgeClass(s.decision)}">${s.decision}</span></td>
      <td>${money(s.price)}</td>
      <td>${money(s.levels.entry)}</td>
      <td>${money(s.levels.better_entry)}</td>
      <td>${money(s.levels.stop)}</td>
      <td>${money(s.levels.target1)}</td>
      <td>${why}</td>
    </tr>
  `;
}

async function loadSignals() {
  const res = await fetch('data/signals.json?ts=' + Date.now());
  const data = await res.json();

  document.getElementById('updated').textContent = data.updated_at_et || 'Unknown';
  document.getElementById('phase').textContent = data.market_phase || 'Unknown';
  document.getElementById('phaseWarning').textContent = ' ' + (data.phase_warning || '');
  document.getElementById('dataHealth').textContent = data.data_health || 'Unknown';
  document.getElementById('buyCount').textContent = data.summary?.buy_setups ?? 0;
  document.getElementById('waitCount').textContent = data.summary?.wait ?? 0;
  document.getElementById('watchCount').textContent = data.summary?.watch_only ?? 0;
  document.getElementById('outcomeSample').textContent = data.summary?.outcome_sample_size ?? 0;
  document.getElementById('rules').innerHTML = (data.beginner_rules || []).map(x => `<div class="rule">${x}</div>`).join('');

  const api = data.api_budget || {};
  const apiMode = document.getElementById('apiMode');
  if (apiMode) apiMode.textContent = `${api.mode || 'middle_ground'} / ${api.status || 'OK'}`;
  const wideScan = document.getElementById('wideScan');
  if (wideScan) wideScan.textContent = `${api.wide_symbols_returned ?? api.wide_symbols_requested ?? 0}/${api.wide_scan_limit ?? 150}`;
  const deepScan = document.getElementById('deepScan');
  if (deepScan) deepScan.textContent = `${api.deep_symbols_selected ?? data.summary?.deep_symbols_checked ?? 0}/${api.deep_scan_limit ?? 40}`;
  const dataCalls = document.getElementById('dataCalls');
  if (dataCalls) dataCalls.textContent = `${api.estimated_data_calls ?? 0}/${api.max_data_calls_per_run ?? 90}`;

  const market = data.market_context || {};
  document.getElementById('marketRegime').textContent = market.market_regime || 'UNKNOWN';
  document.getElementById('spyChange').textContent = pct(market.spy_change_pct);
  document.getElementById('qqqChange').textContent = pct(market.qqq_change_pct);
  document.getElementById('iwmChange').textContent = pct(market.iwm_change_pct);
  document.getElementById('riskNote').textContent = market.risk_note || 'Market context unavailable. Keep signals conservative.';

  const warningEl = document.getElementById('validationWarning');
  if (warningEl) {
    warningEl.textContent = data.validation_warning || '';
    warningEl.style.display = data.validation_warning ? 'block' : 'none';
  }

  const signals = data.signals || [];
  document.getElementById('cards').innerHTML = signals.length
    ? signals.map(makeCard).join('')
    : `<article class="card"><div class="symbol">No signals yet</div><p class="sub">Run the scanner from GitHub Actions or locally.</p></article>`;
  document.getElementById('tableBody').innerHTML = signals.map(makeRow).join('');
}


async function loadExecution() {
  try {
    const res = await fetch('data/execution.json?ts=' + Date.now());
    if (!res.ok) return;
    const data = await res.json();
    const buyEl = document.getElementById('execBuyCount');
    const orderEl = document.getElementById('execOrderCount');
    const detailsEl = document.getElementById('execDetails');
    if (buyEl) buyEl.textContent = data.buy_setup_count ?? 0;
    if (orderEl) orderEl.textContent = data.orders_submitted_this_run ?? 0;
    if (detailsEl) {
      const lines = (data.results || []).slice(0, 3).map(r => `${r.symbol}: ${r.order?.reason || 'processed'}; Telegram ${r.telegram?.reason || 'not checked'}`);
      detailsEl.textContent = lines.length ? lines.join(' | ') : 'No buy setup execution or alert activity on the latest run.';
    }
  } catch (e) {
    // Execution file is optional on first run.
  }
}

loadExecution();

loadSignals().catch(err => {
  document.getElementById('cards').innerHTML = `<article class="card"><div class="symbol">Load error</div><p class="sub">${err.message}</p></article>`;
});
