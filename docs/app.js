'use strict';

const DATA_URL = './data/prices.json';
let chart = null;

// ── formatters ──────────────────────────────────────────────────────────────

function fmtVND(v) {
  if (v == null) return 'N/A';
  return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND',
    maximumFractionDigits: 0 }).format(v);
}

function fmtUSD(v) {
  if (v == null) return 'N/A';
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2,
    maximumFractionDigits: 2 });
}

function changeLabel(current, previous, fmtFn) {
  if (current == null || previous == null || previous === 0) return null;
  const diff = current - previous;
  const pct  = (diff / previous) * 100;
  const sign = diff >= 0 ? '+' : '';
  const cls  = diff > 0 ? 'up' : diff < 0 ? 'down' : '';
  return { text: `${sign}${fmtFn(diff)} (${sign}${pct.toFixed(2)}%)`, cls };
}

// ── render ───────────────────────────────────────────────────────────────────

function renderSJC(sjc, history) {
  document.getElementById('sjc-buy').textContent  = fmtVND(sjc?.buy_price);
  document.getElementById('sjc-sell').textContent = fmtVND(sjc?.sell_price);

  const prev = history.length >= 2 ? history[history.length - 2] : null;
  const info = changeLabel(sjc?.sell_price, prev?.sjc_sell, fmtVND);
  const el   = document.getElementById('sjc-change');
  if (info) { el.textContent = info.text; el.className = 'change ' + info.cls; }
}

function renderIntl(intl, history) {
  document.getElementById('intl-price').textContent = fmtUSD(intl?.buy_price);
  document.getElementById('intl-high').textContent  = fmtUSD(intl?.high);
  document.getElementById('intl-low').textContent   = fmtUSD(intl?.low);

  const prev = history.length >= 2 ? history[history.length - 2] : null;
  const info = changeLabel(intl?.buy_price, prev?.intl_price, fmtUSD);
  const el   = document.getElementById('intl-change');
  if (info) { el.textContent = info.text; el.className = 'change ' + info.cls; }
}

function renderChart(history) {
  const recent = history.slice(-7);
  const labels = recent.map(h => {
    const [y, m, d] = h.date.split('-');
    return `${d}/${m}`;
  });
  const sjcVals  = recent.map(h => h.sjc_sell  != null ? h.sjc_sell  / 1_000_000 : null);
  const intlVals = recent.map(h => h.intl_price != null ? h.intl_price            : null);

  const ctx = document.getElementById('priceChart').getContext('2d');

  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    data: {
      labels,
      datasets: [
        {
          type: 'line', label: 'SJC (triệu VND/lượng)',
          data: sjcVals, yAxisID: 'yLeft',
          borderColor: '#e6a817', backgroundColor: 'rgba(230,168,23,.15)',
          borderWidth: 2, pointRadius: 4, fill: true, tension: .3,
        },
        {
          type: 'line', label: 'XAU/USD ($/troy oz)',
          data: intlVals, yAxisID: 'yRight',
          borderColor: '#2196F3', backgroundColor: 'rgba(33,150,243,.12)',
          borderWidth: 2, pointRadius: 4, fill: true, tension: .3,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#aaa', font: { size: 12 } },
        },
        tooltip: {
          callbacks: {
            label: ctx => ctx.dataset.yAxisID === 'yLeft'
              ? `SJC: ${ctx.parsed.y?.toFixed(2)} triệu VND`
              : `XAU/USD: $${ctx.parsed.y?.toFixed(2)}`,
          },
        },
      },
      scales: {
        x:      { ticks: { color: '#888' }, grid: { color: '#2a2a2a' } },
        yLeft:  { position: 'left',  ticks: { color: '#e6a817' }, grid: { color: '#2a2a2a' } },
        yRight: { position: 'right', ticks: { color: '#2196F3' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

// ── main ─────────────────────────────────────────────────────────────────────

async function load() {
  try {
    const resp = await fetch(DATA_URL + '?t=' + Date.now());
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const history = data.history || [];

    renderSJC(data.sjc, history);
    renderIntl(data.international, history);
    if (history.length) renderChart(history);

    const updatedAt = data.updated_at
      ? new Date(data.updated_at).toLocaleString('vi-VN', {
          timeZone: 'Asia/Ho_Chi_Minh',
          day: '2-digit', month: '2-digit', year: 'numeric',
          hour: '2-digit', minute: '2-digit',
        })
      : null;
    document.getElementById('updated-at').textContent =
      updatedAt ? `Cập nhật lúc ${updatedAt}` : 'Chưa có dữ liệu';

  } catch (err) {
    console.error('Failed to load price data:', err);
    document.getElementById('updated-at').textContent = 'Lỗi khi tải dữ liệu';
  }
}

load();
