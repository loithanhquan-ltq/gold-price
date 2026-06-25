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

    await loadStatus();
  } catch (e) {
    showToast("Lỗi tải giá: " + e.message, 5000);
  } finally {
    setBtn("btn-refresh", "Cập Nhật Giá", false);
  }
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
