"use strict";
// Interface somente leitura: desenha os eventos gravados pelo motor. Nada aqui recalcula decisões.
const LW = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const S = {
  session: null, candles: [], candleIndex: new Map(), decisions: [], decisionById: new Map(),
  opens: [], trades: [], tradeById: new Map(), reviews: new Map(), outcomes: [], outcomeByDecision: new Map(),
  alerts: [], equity: [], lastEquity: null, lastDecision: null, lastCandle: null, lastId: 0, stats: null,
};
const dirty = { candles: 0, equity: 0, markers: false, forecast: false, attribution: false, segments: false,
                panels: false, trades: false };

// ---------- formatação ----------
const nf = (digits) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const N2 = nf(2), N3 = nf(3);
const signed = (text, value) => (value > 0 ? "+" : "") + text;
const price = (v) => (v == null ? "—" : N2.format(v));
const pct = (v, digits = 2) => (v == null ? "—" : signed(nf(digits).format(100 * v), v) + "%");
const logPct = (v, digits = 2) => (v == null ? "—" : pct(Math.expm1(v), digits));
function money(v) {
  if (v == null) return "—";
  const text = N2.format(Math.abs(v));
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return S.session && S.session.currency === "BRL" ? `${sign}R$ ${text}` : `${sign}${text} USDT`;
}
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const date = (t) => new Date(t * 1000);
const utc = (t) => date(t).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const local = (t) => date(t).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const both = (t) => `${utc(t)} (${local(t)} local)`;
const hhmm = (t) => date(t).toISOString().slice(11, 16);
const sideIcon = (side) => (side === "comprada" ? "▲" : "▼");

// ---------- gráficos ----------
function chartOptions(height) {
  return {
    autoSize: true, height,
    layout: { background: { color: css("--panel") }, textColor: css("--muted"), attributionLogo: false,
              fontFamily: getComputedStyle(document.body).fontFamily },
    grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--border") },
    rightPriceScale: { borderColor: css("--border") },
    crosshair: { mode: LW.CrosshairMode.Normal },
    localization: { locale: "pt-BR", priceFormatter: (p) => N2.format(p) },
  };
}
const lineOptions = (color, style = LW.LineStyle.Solid, width = 2) => ({
  color, lineStyle: style, lineWidth: width, priceLineVisible: false, lastValueVisible: false,
  crosshairMarkerVisible: false,
});

const main = LW.createChart($("chart"), chartOptions(460));
const candleSeries = main.addCandlestickSeries({
  upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false,
});
// Linhas do Lightweight Charts 4 não se interrompem em pontos vazios: cada segmento usa a sua série.
const POOL = 40;
function pool(options) {
  const series = [];
  return (segments) => {
    const recent = segments.slice(-POOL);
    while (series.length < recent.length) series.push(main.addLineSeries(options()));
    series.forEach((s, i) => {
      const segment = recent[i];
      s.applyOptions(segment ? { color: segment.color } : {});
      s.setData(segment ? segment.points : []);
    });
  };
}
const drawForecasts = pool(() => lineOptions(css("--forecast"), LW.LineStyle.Dashed));
const drawSegments = pool(() => lineOptions(css("--even"), LW.LineStyle.Solid, 4));
const attributionSeries = main.addHistogramSeries({ priceScaleId: "attr", priceLineVisible: false, lastValueVisible: false,
  priceFormat: { type: "custom", formatter: (v) => pct(v, 4) } });
main.priceScale("attr").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.18 } });

const equityChart = LW.createChart($("equity"), chartOptions(170));
const equitySeries = equityChart.addLineSeries({ ...lineOptions(css("--accent")), lastValueVisible: true, title: "estratégia" });
const holdSeries = equityChart.addLineSeries({ ...lineOptions(css("--even"), LW.LineStyle.Dotted), title: "comprar e segurar" });
equityChart.priceScale("right").applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });
let priceLines = [], priceLinesKey = null;

const candlePoint = (c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });

function forecastData(decision) {
  const end = decision.time + decision.horizon_minutes * 60;
  return [{ time: decision.time, value: decision.close },
          { time: end, value: decision.close * Math.exp(decision.predicted_log_return) }];
}

function renderForecast() {
  drawForecasts(S.decisions.filter((d) => d.predicted_log_return != null && d.horizon_minutes)
    .map((d) => ({ color: css("--forecast"), points: forecastData(d) })));
}

function renderAttribution() {
  const byTime = new Map();
  const up = css("--up"), down = css("--down");
  for (const d of S.decisions) {
    if (!d.attributions) continue;
    const peak = Math.max(...d.attributions.map(Math.abs)) || 1;
    d.attributions.forEach((value, i) => {
      const time = d.time - (d.attributions.length - 1 - i) * 60;
      const alpha = Math.round(60 + 195 * Math.abs(value) / peak).toString(16).padStart(2, "0");
      byTime.set(time, { time, value, color: (value >= 0 ? up : down) + alpha });
    });
  }
  attributionSeries.setData([...byTime.values()].sort((a, b) => a.time - b.time));
}

// Faixa da posição: segmento no preço de entrada, verde se o resultado líquido é positivo.
function renderSegments() {
  const segment = (from, to, value, net) => ({ color: net > 0 ? css("--up") : css("--down"),
    points: from < to ? [{ time: from, value }, { time: to, value }] : [{ time: from, value }] });
  const segments = S.trades.map((t) => segment(t.entry_time, t.exit_bar, t.entry_raw, t.net_display));
  const open = S.lastEquity && S.lastEquity.position;
  if (open && S.lastCandle) segments.push(segment(open.entry_time, S.lastCandle.time, open.entry_raw, open.net_display));
  drawSegments(segments);
}

function markersFor(opens, trades) {
  const markers = [];
  for (const o of opens) {
    const long = o.side === "comprada";
    markers.push({ time: o.time, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown",
                   color: long ? css("--up") : css("--down"), text: long ? "C" : "V" });
  }
  for (const t of trades) {
    markers.push({ time: t.exit_bar, position: t.side === "comprada" ? "aboveBar" : "belowBar", shape: "circle",
                   color: t.net_display > 0 ? css("--up") : css("--down"), text: `${t.exit_reason} ${signed(N2.format(t.net_display), t.net_display)}` });
  }
  return markers.sort((a, b) => a.time - b.time);
}

function renderPriceLines() {
  const p = S.lastEquity && S.lastEquity.position;
  const key = p ? `${p.id}` : null;
  if (key === priceLinesKey) return;
  priceLines.forEach((line) => candleSeries.removePriceLine(line));
  priceLines = [];
  priceLinesKey = key;
  if (!p) return;
  const add = (value, color, style, title) => value != null && priceLines.push(candleSeries.createPriceLine({
    price: value, color, lineStyle: style, lineWidth: 1, axisLabelVisible: true, title }));
  add(p.entry_raw, css("--text"), LW.LineStyle.Solid, "entrada");
  add(p.breakeven, css("--even"), LW.LineStyle.Dotted, "empate");
  add(p.target, css("--up"), LW.LineStyle.Dashed, "alvo");
  add(p.stop, css("--down"), LW.LineStyle.Dashed, "stop");
}

// Acompanha o candle mais recente só se o usuário estiver olhando o fim do gráfico.
function atEnd(chart, count) {
  const range = chart.timeScale().getVisibleLogicalRange();
  return !range || range.to >= count - 3;
}

function renderCharts() {
  const followMain = atEnd(main, candleSeries.data().length);
  const followEquity = atEnd(equityChart, equitySeries.data().length);
  if (dirty.candles) {
    const fresh = S.candles.slice(-dirty.candles);
    if (dirty.candles > 300 || fresh.length === S.candles.length) candleSeries.setData(S.candles.map(candlePoint));
    else fresh.forEach((c) => candleSeries.update(candlePoint(c)));
    dirty.candles = 0;
    if (followMain) main.timeScale().scrollToPosition(4, false);
  }
  if (dirty.equity) {
    const fresh = S.equity.slice(-dirty.equity);
    const point = (e) => ({ time: e.time, value: e.marked_display });
    const hold = (e) => (e.buy_hold_display == null ? { time: e.time } : { time: e.time, value: e.buy_hold_display });
    if (dirty.equity > 300 || fresh.length === S.equity.length) {
      equitySeries.setData(S.equity.map(point));
      holdSeries.setData(S.equity.map(hold));
    } else fresh.forEach((e) => { equitySeries.update(point(e)); holdSeries.update(hold(e)); });
    dirty.equity = 0;
    if (followEquity) equityChart.timeScale().scrollToPosition(2, false);
  }
  if (dirty.markers) { candleSeries.setMarkers(markersFor(S.opens, S.trades)); dirty.markers = false; }
  if (dirty.forecast) { renderForecast(); dirty.forecast = false; }
  if (dirty.attribution) { renderAttribution(); dirty.attribution = false; }
  if (dirty.segments) { renderSegments(); dirty.segments = false; }
  renderPriceLines();
}

// ---------- painéis ----------
function text(id, value, className) {
  const el = $(id);
  el.textContent = value;
  if (className !== undefined) el.className = className;
}

function renderDecision() {
  const d = S.lastDecision;
  $("decision-empty").hidden = !!d;
  $("decision").hidden = !d;
  if (!d) return;
  text("d-time", both(d.available_at));
  if (d.predicted_log_return != null) {
    text("d-pred", `${logPct(d.predicted_log_return, 3)} → ${price(d.close * Math.exp(d.predicted_log_return))}`,
         cls(d.predicted_log_return));
  } else text("d-pred", "não se aplica: regra sem previsão de retorno", "muted");
  text("d-hurdle", `compra ${logPct(d.hurdle_long, 3)} · venda ${logPct(d.hurdle_short, 3)}`);
  text("d-conf", S.session.model === "numerico_v1"
    ? "desconhecida: o modelo v1 não emite probabilidades" : "não se aplica: regra fixa", "muted");
  text("d-vol", `${logPct(d.volatility, 2)} em 30 min`);
  const color = /COMPRAR/.test(d.action) ? "pos" : /VENDER|ZERAR/.test(d.action) ? "neg" : "";
  text("d-action", d.action, `action ${color}`);
  text("d-reason", d.reason);
  const q = S.stats && S.stats.prediction;
  text("d-quality", q && q.resolved
    ? `Em ${q.resolved} decisões resolvidas: erro médio ${pct(q.mae, 3)} contra ${pct(q.mae_zero_forecast, 3)} prevendo zero; direção certa em ${pct(q.direction_accuracy, 1).replace("+", "")}.`
    : "Desfecho das previsões aparece 30 minutos após cada decisão.");
}

const LEVEL_SOURCE = {
  provisorio_volatilidade: "Stop e alvo provisórios: múltiplos da volatilidade recente. O modelo v1 ainda não os prevê.",
  modelo: "Stop e alvo previstos pelo modelo.",
  desligado: "Stop e alvo desligados nesta sessão.",
};

function renderPosition() {
  const p = S.lastEquity && S.lastEquity.position;
  $("position-empty").hidden = !!p;
  $("position").hidden = !p;
  text("p-source", p ? LEVEL_SOURCE[p.levels_source] || "" : "");
  if (!p) return;
  const close = S.lastCandle.close;
  text("p-side", `${sideIcon(p.side)} ${p.side} · ${money(S.session.settings.stake).replace("+", "")}`, p.side === "comprada" ? "pos" : "neg");
  text("p-entry", `${price(p.entry_raw)} às ${hhmm(p.entry_time)} UTC`);
  text("p-gross", money(p.gross_display), cls(p.gross_display));
  text("p-net", `${money(p.net_display)} (${pct(p.net_pct)})`, cls(p.net_display));
  const horizon = S.session.settings.horizon_minutes;
  text("p-age", horizon ? `${p.age} de ${horizon} min` : `${p.age} min`);
  text("p-target", p.target ? `${price(p.target)} (${pct(p.target / close - 1)})` : "—");
  text("p-stop", p.stop ? `${price(p.stop)} (${pct(p.stop / close - 1)})` : "—");
  text("p-extremes", `${logPct(p.best_pct)} / ${logPct(p.worst_pct)}`);
}

function renderData() {
  const c = S.lastCandle;
  if (c) {
    const latency = c.latency_seconds != null ? ` · atraso ${N2.format(c.latency_seconds)} s` : "";
    text("data-status", `Último candle: ${hhmm(c.time)} UTC, fechado às ${hhmm(c.time + 60)}${latency}`);
    text("clock", `${utc(c.time + 60)} · ${local(c.time + 60)} local`);
  }
  const list = $("alerts");
  list.replaceChildren(...S.alerts.slice(-30).reverse().map((a) => {
    const li = document.createElement("li");
    li.className = a.level;
    li.textContent = `${hhmm(a.time)} ${a.message}`;
    return li;
  }));
}

function renderStrip() {
  const n = S.trades.length;
  const balance = S.lastEquity ? S.lastEquity.balance_display : 0;
  const wins = S.trades.filter((t) => t.net_display > 0).length;
  const el = $("balance");
  el.textContent = `Saldo acumulado: ${money(balance)} em ${n} operação(ões)` + (n ? ` · ${Math.round(100 * wins / n)}% positivas` : "");
  el.className = cls(balance);
  $("recent").textContent = S.trades.slice(-5).reverse()
    .map((t) => `${hhmm(t.entry_time)} ${sideIcon(t.side)}${t.side} ${t.exit_reason} ${money(t.net_display)}`).join("  |  ");
}

// ---------- diário ----------
function cell(row, value, className) {
  const td = row.insertCell();
  td.textContent = value;
  if (className) td.className = className;
  return td;
}

function renderTrades() {
  const body = $("trades").tBodies[0];
  body.replaceChildren();
  for (const t of [...S.trades].reverse()) {
    const row = body.insertRow();
    row.onclick = () => openDetail(t.id);
    row.tabIndex = 0;
    row.onkeydown = (event) => { if (event.key === "Enter") openDetail(t.id); };
    const rate = t.rate_entry;
    const outcome = S.outcomeByDecision.get(t.decision_id);
    const review = S.reviews.get(t.id);
    cell(row, t.id);
    cell(row, `${sideIcon(t.side)} ${t.side}`, t.side === "comprada" ? "pos" : "neg");
    cell(row, `${utc(t.entry_time)} (${local(t.entry_time)})`);
    cell(row, `${hhmm(t.exit_time)} UTC`);
    cell(row, `${N2.format(t.minutes)} min`);
    cell(row, `${price(t.entry_raw)} → ${price(t.exit_raw)}`);
    cell(row, `${price(t.stop)} / ${price(t.target)}`);
    cell(row, t.exit_reason + (t.ambiguous ? " (stop e alvo no mesmo candle)" : ""));
    cell(row, money(t.gross_quote * rate), cls(t.gross_quote));
    cell(row, money(-(t.fees_quote + t.slippage_quote + t.borrow_quote) * rate), "neg");
    cell(row, `${money(t.net_display)} (${pct(t.net_pct)})`, cls(t.net_display));
    cell(row, t.predicted_log_return == null ? "—"
      : `${logPct(t.predicted_log_return, 3)} / real ${outcome ? logPct(outcome.realized, 3) : "…"}`);
    cell(row, `${logPct(t.best_pct)} / ${logPct(t.worst_pct)}`);
    cell(row, review ? (review.exit_efficiency == null ? "sem ganho a capturar" : pct(review.exit_efficiency, 0).replace("+", ""))
      : "aguardando 30 min", "retro");
    cell(row, review ? ["-15", "-5", "5", "15", "30"].map((k) => logPct(review.what_if_log_return[k])).join(" / ")
      : "aguardando 30 min", "retro");
  }
}

// ---------- detalhe ----------
let detailChart = null, detailSeries = null, detailLines = [], detailForecast = null;

function openDetail(id) {
  const t = S.tradeById.get(id);
  const decision = S.decisionById.get(t.decision_id);
  $("detail").hidden = false;
  $("close-detail").focus();
  $("detail-title").textContent = `Operação #${t.id}: ${t.side}, saída por ${t.exit_reason}, ${money(t.net_display)} (${pct(t.net_pct)})`;
  if (!detailChart) {
    detailChart = LW.createChart($("detail-chart"), chartOptions(360));
    detailSeries = detailChart.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"),
      wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false });
    detailForecast = detailChart.addLineSeries(lineOptions(css("--forecast"), LW.LineStyle.Dashed));
  }
  const from = t.entry_time - 3600, to = t.exit_bar + 3600;
  detailSeries.setData(S.candles.filter((c) => c.time >= from && c.time <= to).map(candlePoint));
  detailSeries.setMarkers(markersFor(S.opens.filter((o) => o.trade_id === t.id), [t]));
  detailLines.forEach((line) => detailSeries.removePriceLine(line));
  detailLines = [["entrada", t.entry_raw, css("--text"), LW.LineStyle.Solid], ["alvo", t.target, css("--up"), LW.LineStyle.Dashed],
                 ["stop", t.stop, css("--down"), LW.LineStyle.Dashed]]
    .filter(([, value]) => value != null)
    .map(([title, value, color, style]) => detailSeries.createPriceLine({ price: value, color, lineStyle: style, lineWidth: 1, title }));
  detailForecast.setData(decision && decision.predicted_log_return != null ? forecastData(decision) : []);
  detailChart.timeScale().fitContent();

  const state = $("detail-state");
  state.replaceChildren();
  const add = (label, value) => {
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    state.append(dt, dd);
  };
  if (decision) {
    add("Decidido em", both(decision.available_at));
    add("Decisão", decision.action);
    add("Motivo", decision.reason);
    add("Previsão 30 min", logPct(decision.predicted_log_return, 3));
    const outcome = S.outcomeByDecision.get(decision.id);
    add("Realizado 30 min", outcome ? logPct(outcome.realized, 3) : "ainda não disponível");
    add("Volatilidade recente", logPct(decision.volatility));
  }
  add("Stop e alvo", LEVEL_SOURCE[t.levels_source] || "");
  add("Custos", `taxa ${money(-t.fees_quote * t.rate_entry)} · slippage ${money(-t.slippage_quote * t.rate_entry)} · empréstimo ${money(-t.borrow_quote * t.rate_entry)}`);
  if (S.session.currency === "BRL") add("Efeito do câmbio", money(t.fx_effect_display));
  $("detail-attr").replaceChildren(decision && decision.attributions ? attributionBars(decision.attributions) : "");

  const timeline = $("detail-timeline");
  const start = decision ? decision.time : t.entry_time;
  timeline.replaceChildren(...S.decisions.filter((d) => d.time >= start && d.time <= t.exit_bar).slice(0, 200).map((d) => {
    const li = document.createElement("li");
    li.textContent = `${hhmm(d.available_at)} UTC: ${d.action}. ${d.reason}`;
    return li;
  }));
  if (!timeline.children.length) timeline.textContent = "Nenhuma decisão nova entre a entrada e a saída.";
  $("detail-command").textContent = replayCommand(t);
}

function replayCommand(t) {
  const s = S.session, set = s.settings;
  const day = (seconds) => new Date(seconds * 1000).toISOString().slice(0, 10);
  const parts = ["python App/trading_server.py replay", `--model ${s.model === "numerico_v1" ? "cnn" : "medias"}`,
                 `--start ${day(t.entry_time - 3600)}`, `--end ${day(t.exit_bar + 86400)}`, "--speed 10",
                 `--stake ${set.stake}`, `--horizon ${set.horizon_minutes || 0}`];
  if (!set.allow_short) parts.push("--no-short");
  if (!set.levels) parts.push("--no-stops");
  if (s.test_unlocked) parts.push("--allow-test");
  return parts.join(" ");
}

function svg(width, height) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("viewBox", `0 0 ${width} ${height}`);
  el.setAttribute("width", "100%");
  return el;
}
function node(parent, tag, attributes, content) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  if (content != null) el.textContent = content;
  parent.append(el);
  return el;
}

function attributionBars(values) {
  const el = svg(320, 80);
  const peak = Math.max(...values.map(Math.abs)) || 1;
  values.forEach((v, i) => {
    const h = 34 * Math.abs(v) / peak;
    node(el, "rect", { x: 10 + i * 10, y: v >= 0 ? 40 - h : 40, width: 8, height: Math.max(h, .5),
                       fill: v >= 0 ? css("--up") : css("--down") });
  });
  node(el, "text", { x: 10, y: 78 }, "minuto 1 → 30 da janela; altura = influência na previsão");
  return el;
}

// ---------- desempenho ----------
function metric(label, value, className = "") {
  const div = document.createElement("div");
  div.className = "metric";
  const b = document.createElement("b");
  b.textContent = value;
  b.className = className;
  const span = document.createElement("span");
  span.textContent = label;
  div.append(b, span);
  return div;
}

function scatterPlot(points, { diagonal = false, lines = null, empty = "Ainda sem dados." } = {}) {
  const el = svg(420, 260), pad = 36, w = 420 - 2 * pad, h = 260 - 2 * pad;
  const xs = lines ? lines.flatMap((l) => l.values.map((_, i) => i)) : points.map((p) => p[0]);
  const ys = lines ? lines.flatMap((l) => l.values) : points.map((p) => p[1]);
  if (!ys.length) { node(el, "text", { x: pad, y: 130 }, empty); return el; }
  const sorted = (a) => [...a].sort((p, q) => p - q);
  const clip = (a) => { const s = sorted(a); return [s[Math.floor(.01 * (s.length - 1))], s[Math.ceil(.99 * (s.length - 1))]]; };
  let [x0, x1] = lines ? [0, Math.max(...xs) || 1] : clip(xs);
  let [y0, y1] = clip(ys);
  if (diagonal) { x0 = y0 = Math.min(x0, y0); x1 = y1 = Math.max(x1, y1); }
  if (x0 === x1) { x0 -= 1e-4; x1 += 1e-4; }
  if (y0 === y1) { y0 -= 1e-4; y1 += 1e-4; }
  const X = (v) => pad + w * (Math.min(Math.max(v, x0), x1) - x0) / (x1 - x0);
  const Y = (v) => pad + h - h * (Math.min(Math.max(v, y0), y1) - y0) / (y1 - y0);
  node(el, "rect", { x: pad, y: pad, width: w, height: h, fill: "none", stroke: css("--border") });
  if (y0 < 0 && y1 > 0) node(el, "line", { x1: pad, x2: pad + w, y1: Y(0), y2: Y(0), stroke: css("--border") });
  if (diagonal) node(el, "line", { x1: X(x0), y1: Y(y0), x2: X(x1), y2: Y(y1), stroke: css("--even"), "stroke-dasharray": "4 3" });
  if (lines) {
    for (const line of lines) {
      node(el, "polyline", { fill: "none", stroke: line.color, "stroke-width": 2,
                             points: line.values.map((v, i) => `${X(i)},${Y(v)}`).join(" ") });
    }
  } else {
    for (const [x, y] of points) node(el, "circle", { cx: X(x), cy: Y(y), r: 2.5, fill: css("--accent"), "fill-opacity": .5 });
  }
  const fmt = (v) => (lines ? pct(v, 2) : pct(v, 2));
  node(el, "text", { x: 2, y: pad + 4 }, fmt(y1));
  node(el, "text", { x: 2, y: pad + h }, fmt(y0));
  if (!lines) { node(el, "text", { x: pad, y: 256 }, fmt(x0)); node(el, "text", { x: pad + w - 50, y: 256 }, fmt(x1)); }
  return el;
}

function histogram(values) {
  const el = svg(420, 200);
  if (!values.length) { node(el, "text", { x: 20, y: 100 }, "Ainda sem operações."); return el; }
  const lo = Math.min(...values, 0), hi = Math.max(...values, 0), bins = 20, size = (hi - lo) / bins || 1;
  const counts = Array(bins).fill(0);
  values.forEach((v) => { counts[Math.min(bins - 1, Math.floor((v - lo) / size))] += 1; });
  const peak = Math.max(...counts);
  counts.forEach((c, i) => {
    const center = lo + (i + .5) * size, h = 150 * c / peak;
    node(el, "rect", { x: 20 + i * 19, y: 170 - h, width: 17, height: h, fill: center >= 0 ? css("--up") : css("--down") });
  });
  node(el, "text", { x: 20, y: 192 }, money(lo));
  node(el, "text", { x: 330, y: 192 }, money(hi));
  return el;
}

function rolling(values, window = 50) {
  const out = [];
  let sum = 0;
  values.forEach((v, i) => { sum += v; if (i >= window) sum -= values[i - window]; if (i >= window - 1) out.push(sum / window); });
  return out;
}

function renderPerformance() {
  const stats = S.stats;
  if (!stats) return;
  const t = stats.trading;
  const cards = $("metrics");
  cards.replaceChildren();
  const warning = $("warning");
  if (!t.trades) {
    cards.append(metric("Operações", "0"));
    warning.hidden = false;
    warning.textContent = "Ainda sem operações fechadas.";
  } else {
    cards.append(
      metric("Resultado líquido", money(t.net_display), cls(t.net_display)),
      metric("Operações", String(t.trades)),
      metric("Positivas", pct(t.win_rate, 0).replace("+", "")),
      metric("Ganho médio / perda média", `${money(t.average_win)} / ${money(t.average_loss)}`),
      metric("Fator de lucro", t.profit_factor == null ? "—" : N2.format(t.profit_factor)),
      metric("Maior queda do saldo", money(-t.max_drawdown_display), "neg"),
      metric("Custos totais (câmbio de entrada)", money(-t.costs_display), "neg"),
      metric("Média por operação, IC 90%", `${money(t.mean_net_display)} [${money(t.mean_net_ci90[0])}; ${money(t.mean_net_ci90[1])}]`),
      metric("Stop e alvo no mesmo candle", String(t.ambiguous_bars)),
    );
    const notes = [];
    if (t.trades < 30) notes.push(`Com ${t.trades} operação(ões), o resultado ainda é compatível com sorte.`);
    if (t.mean_net_ci90[0] <= 0 && t.mean_net_ci90[1] >= 0) notes.push("O intervalo de 90% do resultado médio inclui zero.");
    warning.hidden = !notes.length;
    warning.textContent = notes.join(" ");
  }
  $("hist").replaceChildren(histogram(S.trades.map((x) => x.net_display)));
  const empty = S.session.model === "numerico_v1" ? "Ainda sem decisões resolvidas." : "Este modelo não prevê retorno.";
  $("scatter").replaceChildren(scatterPlot(S.outcomes.map((o) => [Math.expm1(o.predicted), Math.expm1(o.realized)]), { diagonal: true, empty }));
  $("rolling").replaceChildren(scatterPlot([], { empty, lines: [
    { values: rolling(S.outcomes.map((o) => Math.abs(o.error))), color: css("--accent") },
    { values: rolling(S.outcomes.map((o) => Math.abs(o.realized))), color: css("--even") }] }));
  const groups = $("groups");
  groups.replaceChildren();
  const header = groups.createTHead().insertRow();
  ["Grupo", "Operações", "Líquido"].forEach((label) => { const th = document.createElement("th"); th.textContent = label; header.append(th); });
  const body = groups.createTBody();
  for (const [name, g] of Object.entries(t.groups || {})) {
    const row = body.insertRow();
    cell(row, name.replace("side:", "lado ").replace("exit_reason:", "saída por "));
    cell(row, g.trades);
    cell(row, money(g.net_display), cls(g.net_display));
  }
  $("calibration").textContent = S.session.model === "numerico_v1"
    ? "Indisponível: o modelo v1 prevê só o retorno, sem probabilidades. O diagrama aparece quando existir a cabeça de desfecho (alvo, stop, tempo) do plano."
    : "Não se aplica: médias móveis não emitem confiança.";
}

async function refreshStats() {
  try {
    S.stats = await (await fetch("/api/stats")).json();
    renderDecision();
    if (activeTab === "desempenho") renderPerformance();
  } catch (error) { /* servidor indisponível: o status de conexão já informa */ }
}

// ---------- eventos ----------
function ingest(events) {
  for (const e of events) {
    S.lastId = e.seq;
    switch (e.kind) {
      case "candle":
        S.candleIndex.set(e.time, S.candles.length);
        S.candles.push(e); S.lastCandle = e; dirty.candles += 1; break;
      case "decision":
        S.decisions.push(e); S.decisionById.set(e.id, e); S.lastDecision = e;
        if (e.predicted_log_return != null) dirty.forecast = true;
        if (e.attributions) dirty.attribution = true;
        break;
      case "order":
        if (e.action === "abrir") { S.opens.push(e); dirty.markers = true; }
        break;
      case "trade":
        S.trades.push(e); S.tradeById.set(e.id, e); dirty.markers = true; dirty.trades = true; dirty.segments = true; break;
      case "review": S.reviews.set(e.trade_id, e); dirty.trades = true; break;
      case "outcome": S.outcomes.push(e); S.outcomeByDecision.set(e.decision_id, e); dirty.trades = true; break;
      case "equity":
        S.equity.push(e); S.lastEquity = e; dirty.equity += 1;
        if (e.position || dirty.hadPosition) dirty.segments = true;
        dirty.hadPosition = !!e.position;
        break;
      case "alert": S.alerts.push(e); break;
      default: break;
    }
  }
  dirty.panels = true;
  schedule();
}

let frame = null;
function schedule() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = null;
    renderCharts();
    if (dirty.panels) { renderDecision(); renderPosition(); renderData(); renderStrip(); dirty.panels = false; }
    if (dirty.trades && activeTab === "diario") { renderTrades(); dirty.trades = false; }
  });
}

function connect() {
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?after=${S.lastId}`);
  socket.onmessage = (message) => ingest(JSON.parse(message.data));
  socket.onopen = () => { if (!S.lastCandle) text("data-status", "Conectado; aguardando candles."); };
  socket.onclose = () => {
    text("data-status", "Conexão com o servidor perdida; tentando de novo…");
    setTimeout(connect, 2000);
  };
}

// ---------- controles e abas ----------
let activeTab = "painel";
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  activeTab = button.dataset.tab;
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b === button);
    b.setAttribute("aria-selected", String(b === button));
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === activeTab));
  if (activeTab === "diario") { renderTrades(); dirty.trades = false; }
  if (activeTab === "desempenho") refreshStats().then(renderPerformance);
}));
$("close-detail").onclick = () => { $("detail").hidden = true; };
$("detail").onclick = (event) => { if (event.target.id === "detail") $("detail").hidden = true; };
document.addEventListener("keydown", (event) => { if (event.key === "Escape") $("detail").hidden = true; });

async function control(action, value) {
  const response = await fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ action, value }) });
  const state = await response.json();
  $("play").textContent = state.paused ? "▶ Continuar" : "⏸ Pausar";
  return state;
}
$("play").onclick = () => control($("play").textContent.includes("Pausar") ? "pause" : "resume");
$("step").onclick = () => control("step", 1);
$("speed").onchange = (event) => control("speed", Number(event.target.value));

async function start() {
  S.session = await (await fetch("/api/session")).json();
  const s = S.session;
  text("mode", s.mode === "replay" ? `Replay ${s.start_utc.slice(0, 10)} → ${s.end_utc.slice(0, 10)}` : "Ao vivo (paper trading)");
  text("model", `Modelo ${s.model} · ${s.model_version}`);
  $("model").title = s.model_description;
  const set = s.settings;
  text("currency", `${money(set.stake).replace("+", "")} por operação · ${s.fx_source} · ` +
       `${set.allow_short ? "compra e venda a descoberto" : "só compra"}`);
  if (s.mode === "replay") {
    const splits = (s.splits || []).join(", ");
    text("period", `Divisão: ${splits}${s.test_unlocked ? " · TESTE DESBLOQUEADO" : ""}`, s.test_unlocked ? "chip danger" : "chip");
    $("speed").value = String(s.speed);
    $("play").textContent = s.paused ? "▶ Iniciar" : "⏸ Pausar";
  } else {
    $("controls").hidden = true;
    $("period").hidden = true;
  }
  connect();
  setInterval(refreshStats, 5000);
}
start();
