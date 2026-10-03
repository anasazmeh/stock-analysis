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
    const poll = function () {
      fetch("/refresh/status").then(r => r.json()).then(function (s) {
        if (s.running) { status.textContent = "Running since " + s.started.slice(11, 16) + "…"; setTimeout(poll, 5000); return; }
        btn.disabled = false; btn.textContent = "Refresh data";
        if (s.finished) {
          status.textContent = s.exit_code === 0 ? "Done — reloading" : (s.exit_code === 2 ? "Done (degraded data) — reloading" : "Run failed (see logs/dashboard_run.log)");
          if (s.exit_code === 0 || s.exit_code === 2) setTimeout(() => location.reload(), 1200);
        }
      }).catch(() => { status.textContent = "Lost contact with the dashboard"; btn.disabled = false; });
    };
    btn.addEventListener("click", function () {
      btn.disabled = true; btn.textContent = "Running…";
      fetch("/refresh", { method: "POST" }).then(function (r) {
        if (r.status === 409) status.textContent = "A run is already in progress";
        poll();
      }).catch(() => { btn.disabled = false; status.textContent = "Could not start the run"; });
    });
    fetch("/refresh/status").then(r => r.json()).then(s => { if (s.running) { btn.disabled = true; btn.textContent = "Running…"; poll(); } });
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
