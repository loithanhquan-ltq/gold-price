let chart = null;
let toastTimer = null;

const fmtVND = v =>
  v == null ? "—" : new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(v) + " ₫";

const fmtUSD = v =>
  v == null ? "—" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function showToast(msg, ms = 3500) {
  clearTimeout(toastTimer);
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  toastTimer = setTimeout(() => t.classList.add("hidden"), ms);
}

function setBtn(id, label, disabled) {
  const b = document.getElementById(id);
  b.textContent = label;
  b.disabled = disabled;
}

async function loadCurrentPrices() {
  setBtn("btn-refresh", "⏳ Đang tải...", true);
  try {
    const res = await fetch("/api/prices/current");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const sjc = data.sjc || {};
    const intl = data.international || {};

    document.getElementById("sjc-buy").textContent  = fmtVND(sjc.buy_price);
    document.getElementById("sjc-sell").textContent = fmtVND(sjc.sell_price);
    document.getElementById("intl-price").textContent = fmtUSD(intl.buy_price);
    document.getElementById("intl-hl").textContent =
      fmtUSD(intl.high) + " / " + fmtUSD(intl.low);

    document.getElementById("last-updated").textContent =
      "Cập nhật: " + new Date(data.fetched_at).toLocaleString("vi-VN");

    await loadChart();
    await loadStatus();
  } catch (e) {
    showToast("Lỗi tải giá: " + e.message, 5000);
  } finally {
    setBtn("btn-refresh", "Cập Nhật Giá", false);
  }
}

async function loadChart() {
  const res = await fetch("/api/prices/history?days=7");
  if (!res.ok) return;
  const rows = await res.json();

  const sjcRows  = rows.filter(r => r.source === "SJC");
  const intlRows = rows.filter(r => r.source === "INTERNATIONAL");
  const dates    = [...new Set(rows.map(r => r.price_date))].sort();

  function byDate(arr, field) {
    const map = {};
    arr.forEach(r => { map[r.price_date] = r[field]; });
    return dates.map(d => map[d] ?? null);
  }

  const ctx = document.getElementById("priceChart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: dates.map(d => {
        const [y, m, day] = d.split("-");
        return `${day}/${m}`;
      }),
      datasets: [
        {
          label: "SJC Bán (triệu VND)",
          data: byDate(sjcRows, "sell_price").map(v => v != null ? v / 1_000_000 : null),
          borderColor: "#e6a817",
          backgroundColor: "rgba(230,168,23,0.08)",
          yAxisID: "y",
          tension: 0.35,
          spanGaps: true,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: "XAU/USD",
          data: byDate(intlRows, "buy_price"),
          borderColor: "#2196F3",
          backgroundColor: "rgba(33,150,243,0.08)",
          yAxisID: "y2",
          tension: 0.35,
          spanGaps: true,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      scales: {
        y: {
          position: "left",
          ticks: { color: "#e6a817", font: { size: 11 } },
          grid: { color: "#1f1f1f" },
        },
        y2: {
          position: "right",
          ticks: { color: "#2196F3", font: { size: 11 } },
          grid: { drawOnChartArea: false },
        },
        x: {
          ticks: { color: "#666", font: { size: 11 } },
          grid: { color: "#1a1a1a" },
        },
      },
      plugins: {
        legend: { labels: { color: "#aaa", font: { size: 12 }, boxWidth: 14 } },
        tooltip: {
          backgroundColor: "#1e1e1e",
          titleColor: "#ccc",
          bodyColor: "#eee",
          borderColor: "#333",
          borderWidth: 1,
        },
      },
    },
  });
}

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    const dot = document.getElementById("status-dot");
    if (data.scheduler_running) {
      dot.className = "dot dot-ok";
      dot.title = "Scheduler running. Next run: " + (data.next_run
        ? new Date(data.next_run).toLocaleString("vi-VN") : "N/A");
    } else {
      dot.className = "dot dot-error";
      dot.title = "Scheduler not running";
    }
  } catch {}
}

async function triggerEmail() {
  setBtn("btn-send", "⏳ Đang gửi...", true);
  try {
    const res = await fetch("/api/email/test", {
      method: "POST",
      headers: { "X-API-Token": APP_TOKEN },
    });
    if (res.ok) {
      showToast("Email đã được gửi thành công!");
    } else {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
  } catch (e) {
    showToast("Lỗi gửi email: " + e.message, 6000);
  } finally {
    setBtn("btn-send", "Gửi Email Test", false);
  }
}

// Initial load + auto-refresh every 5 minutes
loadCurrentPrices();
setInterval(loadCurrentPrices, 5 * 60 * 1000);
