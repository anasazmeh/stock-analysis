// Sortable tables, filters, refresh button. Charts are set up per page from inline JSON.
(function () {
  function cellValue(td) {
    const v = td.dataset.value !== undefined ? td.dataset.value : td.textContent.trim();
    const n = parseFloat(String(v).replace(/[€$,%+]/g, "").replace("−", "-"));
    return isNaN(n) || v === "" || v === "–" ? String(v).toLowerCase() : n;
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th[data-sort]").forEach(function (th, idx) {
      th.addEventListener("click", function () {
        const col = Array.from(th.parentNode.children).indexOf(th);
        const asc = !th.classList.contains("sorted-asc");
        table.querySelectorAll("th").forEach(h => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(asc ? "sorted-asc" : "sorted-desc");
        const body = table.tBodies[0];
        const rows = Array.from(body.rows);
        rows.sort(function (a, b) {
          const x = cellValue(a.cells[col]), y = cellValue(b.cells[col]);
          const xs = typeof x === "string", ys = typeof y === "string";
          if (xs !== ys) return xs ? 1 : -1;          // blanks / text after numbers
          if (x < y) return asc ? -1 : 1;
          if (x > y) return asc ? 1 : -1;
          return 0;
        });
        rows.forEach(r => body.appendChild(r));
      });
    });
  });

  const filterForm = document.getElementById("filters");
  if (filterForm) {
    const apply = function () {
      const q = (filterForm.q.value || "").toLowerCase();
      const region = filterForm.region.value, shariah = filterForm.shariah.value;
      const top = filterForm.top.checked, hideGaps = filterForm.gaps.checked;
      let shown = 0;
      document.querySelectorAll("#opp-table tbody tr").forEach(function (tr) {
        const ok = (!q || tr.dataset.search.includes(q)) &&
          (!region || tr.dataset.region === region) &&
          (!shariah || tr.dataset.shariah === shariah) &&
          (!top || tr.dataset.top === "1") &&
          (!hideGaps || tr.dataset.ok === "1");
        tr.hidden = !ok;
        if (ok) shown++;
      });
      const c = document.getElementById("shown-count");
      if (c) c.textContent = shown;
    };
    filterForm.addEventListener("input", apply);
    filterForm.addEventListener("submit", e => e.preventDefault());
    apply();
  }

  const btn = document.getElementById("refresh-btn");
  if (btn) {
    const status = document.getElementById("refresh-status");
    const cancel = document.getElementById("refresh-cancel");
    const mmss = s => Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    const show = (text, withLog) => {
      status.textContent = text + (withLog ? " · " : "");
      if (withLog) { const a = document.createElement("a"); a.href = "/refresh/log"; a.textContent = "log"; status.appendChild(a); }
    };
    const idle = () => { btn.disabled = false; btn.textContent = "Refresh data"; if (cancel) cancel.hidden = true; };
    const busy = () => { btn.disabled = true; btn.textContent = "Running…"; if (cancel) cancel.hidden = false; };
    const handle = function (r) {
      if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return null; }
      if (r.status === 403) { idle(); show("Blocked: open the dashboard from its own address and try again"); return null; }
      return r.json();
    };
    let watching = false;   // true once this page has seen a run in progress
    const poll = function () {
      fetch("/refresh/status", { cache: "no-store" }).then(handle).then(function (s) {
        if (!s) return;
        if (s.running) {
          watching = true;
          busy();
          const step = (s.stage || "starting").replace(/^[^A-Za-z]*/, "");
          show(mmss(s.elapsed_s || 0) + " · " + step, true);
          setTimeout(poll, 4000);
          return;
        }
        idle();
        if (!s.finished || !watching) return;
        watching = false;
        const msg = { 0: "Done — reloading", 2: "Done (some data missing) — reloading", timeout: "Stopped: the run took longer than " + s.timeout_min + " min",
                      cancelled: "Cancelled" }[s.exit_code] || ("Run failed (exit code " + s.exit_code + ")");
        show(msg, !(s.exit_code === 0 || s.exit_code === 2));
        if (s.exit_code === 0 || s.exit_code === 2) setTimeout(() => location.reload(), 1200);
      }).catch(() => { show("Lost contact with the dashboard — retrying"); setTimeout(poll, 10000); });
    };
    btn.addEventListener("click", function () {
      busy(); show("Starting…"); watching = true;
      fetch("/refresh", { method: "POST" }).then(function (r) {
        if (r.status === 409) show("A run is already in progress");
        return handle(r);
      }).then(s => { if (s) poll(); }).catch(() => { idle(); show("Could not start the run"); });
    });
    if (cancel) cancel.addEventListener("click", function () {
      cancel.disabled = true;
      fetch("/refresh/cancel", { method: "POST" }).then(handle).finally(() => { cancel.disabled = false; poll(); });
    });
    // Phones pause timers in the background: check again when the page comes back.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
    poll();
  }
})();

// Chart colours follow the CSS tokens so both themes stay readable.
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function chartDefaults() {
  if (!window.Chart) return false;
  Chart.defaults.color = cssVar("--muted");
  Chart.defaults.borderColor = cssVar("--border");
  Chart.defaults.font.family = cssVar("--font");
  return true;
}
const SERIES = ["--accent", "--info", "--warn", "--good", "--bad", "--muted"];
