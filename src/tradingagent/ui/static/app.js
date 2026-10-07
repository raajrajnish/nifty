// Dashboard client. One poll of /api/overview every 3 s renders everything; the system log uses SSE.
// The only writes are: connect Groww, kill, resume, logout.
(() => {
  const CSRF = document.querySelector('meta[name="csrf-token"]').content;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const num = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
  const inr = (v) => v == null || isNaN(v) ? "—" : "₹" + Math.round(Number(v)).toLocaleString("en-IN");
  const sinr = (v) => v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "−") + "₹" + Math.abs(Math.round(v)).toLocaleString("en-IN");
  const spct = (v, d = 2) => v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "−") + Math.abs(Number(v)).toFixed(d) + "%";
  const sign = (v) => v == null ? "" : v >= 0 ? "pos" : "neg";
  const set = (id, html, cls) => { const el = $(id); el.innerHTML = html; if (cls !== undefined) el.className = el.className.replace(/\b(pos|neg)\b/g, "").trim() + " " + cls; };

  async function api(path, body) {
    const opts = body === undefined ? {} : {method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": CSRF}, body: JSON.stringify(body)};
    const r = await fetch(path, opts);
    if (r.status === 401) { location.href = "/login"; throw new Error("logged out"); }
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
    return data;
  }

  // ---- market session (IST) --------------------------------------------------------------
  function istNow() { return new Date(new Date().toLocaleString("en-US", {timeZone: "Asia/Kolkata"})); }
  function session() {
    const n = istNow(), m = n.getHours() * 60 + n.getMinutes(), wd = n.getDay();
    if (wd === 0 || wd === 6) return ["Market closed (weekend)", ""];
    if (m < 9 * 60) return ["Before market", ""];
    if (m < 9 * 60 + 15) return ["Pre-open", "amber"];
    if (m < 15 * 60 + 30) return ["Market OPEN", "ok-pill"];
    return ["Market closed", ""];
  }

  // ---- chart -------------------------------------------------------------------------------
  let chart = null, series = null, lines = {}, lastBarTs = null;
  if (window.LightweightCharts) {
    chart = LightweightCharts.createChart($("chart"), {
      autoSize: true, layout: {background: {color: "transparent"}, textColor: "#c9ced6"},
      grid: {vertLines: {color: "rgba(128,128,128,.1)"}, horzLines: {color: "rgba(128,128,128,.1)"}},
      timeScale: {timeVisible: true, secondsVisible: false},
      // bar times are IST wall-clock encoded as UTC (see PaperEngine.market), so format in UTC
      localization: {timeFormatter: (t) => new Date(t * 1000).toLocaleTimeString("en-IN", {hour: "2-digit", minute: "2-digit", timeZone: "UTC"})},
    });
    series = chart.addCandlestickSeries({upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false});
  }
  function priceLine(key, price, color, style, title) {
    if (!series) return;
    if (lines[key] && lines[key].price === price) return;
    if (lines[key]) series.removePriceLine(lines[key].ref);
    if (price == null) { delete lines[key]; return; }
    lines[key] = {price, ref: series.createPriceLine({price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title})};
  }
  function renderChart(m) {
    const bars = (m.bars || []).map((b) => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]}));
    $("chart-empty").hidden = bars.length > 0;
    if (!series || !bars.length) return;
    const last = bars[bars.length - 1].time;
    if (lastBarTs === null || bars.length < 3 || last < lastBarTs) { series.setData(bars); chart.timeScale().fitContent(); }
    else bars.slice(-3).forEach((b) => series.update(b));
    lastBarTs = last;
    priceLine("pdh", m.pdh, "#a3a3a3", 2, "Yday high");
    priceLine("pdl", m.pdl, "#a3a3a3", 2, "Yday low");
    priceLine("orh", m.or_high, "#60a5fa", 1, "OR high");
    priceLine("orl", m.or_low, "#60a5fa", 1, "OR low");
    priceLine("twap", m.twap, "#f59e0b", 0, "TWAP");
  }

  // ---- sections ----------------------------------------------------------------------------
  function renderTop(o) {
    const s = o.system;
    const [sl, sc] = session();
    $("session").textContent = sl; $("session").className = "pill " + sc;
    $("stage-mode").textContent = `${s.stage} · ${s.mode}`;
    $("stage-mode").className = "pill " + (s.mode === "LIVE" ? "danger" : "amber");
    $("dot-groww").className = "dot " + (s.broker.connected ? "ok" : "bad");
    const rec = s.recorder;
    const recAge = rec && rec.last_write_at ? Math.max(0, (Date.now() - new Date(rec.last_write_at)) / 1000) : null;
    $("dot-rec").className = "dot " + (rec && rec.running && recAge < 30 ? "ok" : "bad");
    $("rec-text").textContent = rec ? (rec.running ? `${Math.round(recAge ?? 0)}s ago` : "stopped") : "off";
    // Live-feed alarm (2026-10-07): during market hours, shout if the recorder has stopped or its data is > 60 s old.
    const now = new Date(), hm = now.getHours() * 60 + now.getMinutes(), wkday = now.getDay() >= 1 && now.getDay() <= 5;
    const mkt = wkday && hm >= 9 * 60 + 15 && hm < 15 * 60 + 30;
    const stale = !rec || !rec.running || recAge == null || recAge > 60;
    $("feed-banner").hidden = !(mkt && stale);
    $("feed-banner").textContent = (mkt && stale) ? "⚠ LIVE FEED STOPPED: last data " +
      (rec && rec.last_write_at ? rec.last_write_at.slice(11, 19) + ` (${Math.round(recAge ?? 0)}s ago)` : "none today") +
      ". Paper engines and U1–U4 are blind. The recorder restarts itself; if this stays, run Start Trading." : "";
    $("dot-engine").className = "dot " + (o.paper.engine_running ? "ok" : "bad");
    $("halt-banner").hidden = !s.halted;
    $("halt-reason").textContent = s.halt ? `${s.halt.reason} (via ${s.halt.source})` : "";
    $("broker-error").hidden = !s.broker.error;
    $("broker-error").textContent = s.broker.error ? "Groww: " + s.broker.error : "";
    $("data-note").hidden = !o.history_note;
    $("data-note").textContent = o.history_note ? "Data: " + o.history_note : "";
  }

  function renderMarket(o) {
    const m = o.market || {};
    $("asof").textContent = o.as_of ? `· data as of ${o.as_of.slice(11, 19)}` : "· no live data (market closed or engine not running)";
    set("m-nifty", num(m.index));
    set("m-change", m.change_pts == null ? "vs yesterday —" : `${m.change_pts >= 0 ? "+" : ""}${num(m.change_pts)} (${spct(m.change_pct)}) vs yesterday`, sign(m.change_pts));
    set("m-range", m.day_low ? `${num(m.day_low, 0)} – ${num(m.day_high, 0)}` : "—");
    set("m-prev", m.pdh ? `Yesterday ${num(m.pdl, 0)} – ${num(m.pdh, 0)} · close ${num(m.prev_close, 0)}` : "—");
    const ce = (m.atm || {}).CE || {}, pe = (m.atm || {}).PE || {};
    set("m-atm", m.atm_strike ?? "—");
    set("m-atm-legs", m.atm_strike ? `CALL ₹${num(ce.ask ?? ce.ltp)} · PUT ₹${num(pe.ask ?? pe.ltp)} <span class="muted">(ask)</span>` : "—");
    set("m-lot", m.lot_size ? `${m.lot_size} units` : "—");
    set("m-lotcost", m.atm_strike ? `1 lot ATM CALL ${inr(ce.one_lot_cost_inr)} · PUT ${inr(pe.one_lot_cost_inr)}` : "—");
    set("m-vix", num(m.vix));
    set("m-expiry", m.expiry || "—");
    if (m.expiry) {
      const days = Math.round((new Date(m.expiry) - new Date(istNow().toDateString())) / 86400000);
      set("m-expiry-sub", `${days} day${days === 1 ? "" : "s"} away · nearest weekly after today`);
    }
    renderChart(m);
  }

  function renderAccount(o) {
    const a = o.account;
    set("a-equity", inr(a.equity));
    set("a-start", `start ${inr(a.start_capital)} · peak ${inr(a.peak_equity)}`);
    set("a-today", sinr(a.today_total_inr), sign(a.today_total_inr));
    set("a-today-sub", `${spct(a.today_total_pct)} · closed ${sinr(a.today_pnl)} + open ${sinr(a.open_mtm_inr)} · limit −${a.daily_loss_limit_pct}% (${inr(a.daily_loss_limit_inr)})`);
    set("a-total", sinr(a.total_pnl_inr), sign(a.total_pnl_inr));
    set("a-total-sub", `${spct(a.total_pnl_pct)} of starting money`);
    set("a-risk", inr(a.per_trade_risk_inr));
    set("a-risk-sub", `${a.per_trade_risk_pct}% of equity`);
    set("a-outlay", inr(a.max_outlay_inr));
    set("a-outlay-sub", `${a.max_outlay_pct}% of equity · max ${a.max_lots} lots`);
    set("a-dd", `${(a.drawdown_pct ?? 0).toFixed(2)}%`);
    set("a-dd-sub", `kill at ${a.drawdown_kill_pct}% (${inr(a.drawdown_kill_inr)} below peak)`);
    $("a-dd-bar").style.width = Math.min(100, (a.drawdown_pct / a.drawdown_kill_pct) * 100) + "%";
    const sz = a.sizing || {};
    $("sizing").innerHTML = ["G1", "G2"].map((k) => {
      const z = sz[k] || {}, stop = k === "G1" ? 50 : 30;
      const lots = z.lots == null ? "—" : z.lots;
      return `<div class="size-row"><div><b>${k}</b> <span class="muted small">stop −${stop}% of premium</span></div>
        <div class="size-lots ${z.lots ? "pos" : "neg"}">${lots} lot${z.lots === 1 ? "" : "s"}</div>
        <div class="muted small">${z.cost_per_lot_inr ? `1 lot costs ${inr(z.cost_per_lot_inr)} · at the stop it loses ${inr(z.risk_per_lot_inr)}` : ""}</div>
        <div class="small">${esc(z.why || "")}</div></div>`;
    }).join("");
  }

  const STATUS = {WAITING_FOR_OPEN: ["Waiting for 09:15", ""], NOT_TODAY: ["Not today", "muted-pill"],
    WATCHING: ["Watching", "info-pill"], IN_TRADE: ["IN TRADE", "amber"], DONE: ["Done for today", ""], SKIPPED: ["Skipped", "danger"]};
  const tick = (v) => v === true ? '<span class="ok-t">✓</span>' : v === false ? '<span class="bad-t">✗</span>' : '<span class="muted">…</span>';

  function renderSetup(name, s, exp, tot) {
    const el = $("setup-" + name);
    if (!s) { el.innerHTML = `<div class="setup-head"><h3>${name}</h3><span class="pill">engine off</span></div>
      <p class="muted">The paper engine is not running today. It starts with Start Trading.cmd.</p>`; return; }
    const [label, cls] = STATUS[s.status] || [s.status, ""];
    const checks = Object.entries(s.checks || {}).map(([k, v]) => `<li>${tick(v)} ${esc(k)}</li>`).join("") || '<li class="muted">Checked at 09:15 / 09:30.</li>';
    const t = s.trade;
    let box = "";
    if (t && s.status === "IN_TRADE") {
      box = `<div class="trade live"><div class="trade-row"><b>${t.side === "CE" ? "CALL" : "PUT"} ${esc(t.strike)}</b> <span class="muted">exp ${esc(t.expiry)}</span></div>
        <div class="trade-row">Bought ₹${num(t.entry_px)} at ${esc((t.entry_ts || "").slice(11, 16))} · now ₹${num(t.mark_px)} · ${t.minutes_held ?? 0} min</div>
        <div class="pnl ${sign(t.pnl_inr)}">${spct(t.pnl_pct_of_premium, 1)} <span class="muted small">of premium · ${sinr(t.pnl_inr)} (${spct(t.pnl_pct_of_equity)} of equity)</span></div>
        <div class="trade-row small">Paid ${inr(t.premium_paid_inr)} · stop ₹${num(t.stop_px)} (−${t.stop_pct_of_premium}%)${t.invalidation ? " · exit if " + esc(t.invalidation) : ""} · out by 15:10</div></div>`;
    } else if (t && s.status === "DONE") {
      box = `<div class="trade"><div class="trade-row"><b>${t.side === "CE" ? "CALL" : "PUT"} ${esc(t.strike)}</b> · ₹${num(t.entry_px)} → ₹${num(t.exit_px)} · ${esc(t.reason)}</div>
        <div class="pnl ${sign(t.net_inr)}">${sinr(t.net_inr)} <span class="muted small">net · ${spct(t.net_pct_of_premium, 1)} of premium · ${spct(t.net_pct_of_equity)} of equity</span></div></div>`;
    }
    const expLine = exp ? `Backtest ${exp.trades} trades, ${sinr(exp.net_per_trade_inr)}/trade` : "";
    const totLine = tot ? ` · Paper so far ${tot.trades} trades, ${sinr(tot.net_inr)}` : " · Paper so far: none";
    el.innerHTML = `<div class="setup-head"><h3>${name}</h3><span class="pill ${cls}">${label}</span></div>
      <p class="summary">${esc(s.summary)}</p><ul class="checks">${checks}</ul>
      ${s.waiting_for ? `<p class="waiting">⏳ ${esc(s.waiting_for)}</p>` : ""}${box}
      <p class="muted small">${expLine}${totLine}</p>
      <details><summary>What it did today (${(s.log || []).length})</summary><ol class="log">${(s.log || []).slice().reverse().map((l) => `<li>${esc(l)}</li>`).join("")}</ol></details>`;
  }

  function renderDays(o) {
    $("days").innerHTML = (o.days || []).length ? o.days.map((d) => `<tr><td>${esc(d.day)}</td><td>${d.trades}</td>
      <td>${esc(d.setups.join(", "))}</td><td class="num ${sign(d.net_inr)}">${sinr(d.net_inr)}</td>
      <td class="num ${sign(d.net_pct)}">${spct(d.net_pct)}</td><td class="num">${inr(d.equity_after)}</td></tr>`).join("")
      : '<tr><td colspan="6" class="muted">No paper trading days yet. G1/G2 fire on about 1 day in 5.</td></tr>';
    const tr = (o.trades || []).slice().reverse();
    $("trades").innerHTML = tr.length ? tr.map((t) => `<tr><td>${esc(t.day)}</td><td>${esc(t.setup)}</td>
      <td>${esc(t.side)} ${esc(t.strike)}</td><td>₹${esc(t.entry_px)} → ₹${esc(t.exit_px)}</td><td>${esc(t.reason)}</td>
      <td class="num">${t.net_pct_of_premium ? esc(t.net_pct_of_premium) + "%" : "—"}</td>
      <td class="num ${sign(Number(t.net_inr))}">${sinr(Number(t.net_inr))}</td></tr>`).join("")
      : '<tr><td colspan="7" class="muted">No paper trades yet.</td></tr>';
    const ex = o.paper.expected || {}, tot = o.paper.totals || {};
    $("vs-backtest").textContent = ["G1", "G2"].map((k) => `${k}: paper ${tot[k] ? `${tot[k].trades} trades, ${sinr(tot[k].net_per_trade)}/trade` : "no trades yet"}`
      + ` vs backtest ${ex[k] ? sinr(ex[k].net_per_trade_inr) + "/trade" : "—"}`).join("  ·  ");
  }

  async function refresh() {
    let o;
    try { o = await api("/api/overview"); } catch (e) { console.error(e); return; }
    renderTop(o); renderMarket(o); renderAccount(o);
    for (const k of ["G1", "G2"]) renderSetup(k, (o.setups || {})[k], (o.paper.expected || {})[k], (o.paper.totals || {})[k]);
    renderDays(o);
  }

  // ---- system log (SSE) --------------------------------------------------------------------
  function addFeed(evt) {
    if (evt.type === "CANDLE") return;
    const li = document.createElement("li");
    const p = evt.payload || {};
    let text = JSON.stringify(p);
    if (evt.type === "STATE_TRANSITION") text = `${p.from} → ${p.to} (${p.reason})`;
    if (evt.type === "HALT" || evt.type === "RESUME") text = `${p.reason} (via ${p.source})`;
    if (evt.type === "AUTH") text = p.connected ? "Groww connected" : `Groww connect failed: ${p.error}`;
    if (evt.type === "UI_ACTION") text = p.action;
    li.innerHTML = `<span class="mono muted"></span> <span class="tag"></span> <span></span>`;
    li.children[0].textContent = new Date(evt.ts).toLocaleTimeString("en-IN", {hour12: false});
    li.children[1].textContent = evt.type;
    li.children[2].textContent = text;
    $("feed").prepend(li);
    while ($("feed").children.length > 200) $("feed").lastChild.remove();
  }
  const es = new EventSource("/api/stream");
  ["DECISION", "STATE_TRANSITION", "HALT", "RESUME", "AUTH", "UI_ACTION", "ALERT"].forEach((t) =>
    es.addEventListener(t, (e) => { addFeed(JSON.parse(e.data)); refresh(); }));
  api("/api/events").then((evs) => evs.forEach(addFeed)).catch(() => {});

  // ---- actions -----------------------------------------------------------------------------
  $("btn-connect").onclick = async () => {
    const b = $("btn-connect"); b.disabled = true; b.textContent = "Connecting…";
    try { await api("/api/auth/groww", {}); } catch (e) { alert(e.message); }
    b.disabled = false; b.textContent = "Connect Groww"; refresh();
  };
  $("btn-kill").onclick = () => { $("kill-confirm").value = ""; $("dlg-kill").showModal(); };
  $("kill-go").onclick = async (e) => {
    e.preventDefault();
    try { await api("/api/kill", {confirm: $("kill-confirm").value, reason: $("kill-reason").value}); $("dlg-kill").close(); refresh(); }
    catch (err) { alert(err.message); }
  };
  $("btn-resume").onclick = () => $("dlg-resume").showModal();
  $("resume-go").onclick = async (e) => {
    e.preventDefault();
    try { await api("/api/resume", {reason: $("resume-reason").value}); $("dlg-resume").close(); refresh(); }
    catch (err) { alert(err.message); }
  };
  if ($("btn-logout")) $("btn-logout").onclick = async () => { await api("/logout", {}); location.href = "/login"; };

  setInterval(() => { $("clock").textContent = istNow().toLocaleTimeString("en-IN", {hour12: false}) + " IST"; }, 500);
  refresh();
  setInterval(refresh, 3000);
})();
