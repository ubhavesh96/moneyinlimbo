/* Queue and explorer tables: client-side filters, J/K keyboard navigation, refresh while agents work. */
(function () {
  "use strict";
  const rows = Array.from(document.querySelectorAll("[data-row]"));
  const ctl = {};
  document.querySelectorAll("[data-filter]").forEach(function (el) { ctl[el.dataset.filter] = el; });
  const count = document.getElementById("count");
  let sel = -1;

  function visible() { return rows.filter(function (r) { return !r.hidden; }); }

  function apply() {
    const q = (ctl.q && ctl.q.value || "").toLowerCase().trim();
    rows.forEach(function (r) {
      let ok = true;
      if (q && r.dataset.text.toLowerCase().indexOf(q) < 0) ok = false;
      if (ctl.rail && ctl.rail.value && r.dataset.rail.indexOf(ctl.rail.value) !== 0) ok = false;
      if (ctl.status && ctl.status.value && r.dataset.status !== ctl.status.value) ok = false;
      if (ctl.referral && ctl.referral.checked && !r.dataset.referral) ok = false;
      if (ctl.cluster && ctl.cluster.checked && !r.dataset.cluster) ok = false;
      r.hidden = !ok;
    });
    if (count) count.textContent = "Showing " + visible().length + " of " + rows.length + " complaints.";
    MIL.store("mil-queue-filters", JSON.stringify(state()));
  }

  function state() {
    return { q: ctl.q && ctl.q.value, rail: ctl.rail && ctl.rail.value, status: ctl.status && ctl.status.value,
      referral: ctl.referral && ctl.referral.checked, cluster: ctl.cluster && ctl.cluster.checked };
  }

  try {
    const saved = JSON.parse(MIL.store("mil-queue-filters") || "null");
    if (saved) Object.keys(saved).forEach(function (k) {
      if (!ctl[k]) return;
      if (ctl[k].type === "checkbox") ctl[k].checked = !!saved[k]; else ctl[k].value = saved[k] || "";
    });
  } catch (e) { /* ignore bad saved state */ }

  Object.values(ctl).forEach(function (el) { el.addEventListener("input", apply); el.addEventListener("change", apply); });
  document.querySelectorAll("[data-filter-reset]").forEach(function (b) {
    b.addEventListener("click", function () {
      Object.values(ctl).forEach(function (el) { if (el.type === "checkbox") el.checked = false; else el.value = ""; });
      apply();
    });
  });

  function mark(i) {
    const v = visible();
    if (!v.length) return;
    sel = Math.max(0, Math.min(i, v.length - 1));
    rows.forEach(function (r) { r.classList.remove("sel"); });
    v[sel].classList.add("sel");
    v[sel].scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, select, textarea")) return;
    if (e.key === "j") mark(sel + 1);
    else if (e.key === "k") mark(sel - 1);
    else if (e.key === "Enter" && sel >= 0) { const v = visible()[sel]; if (v) location.href = v.dataset.href; }
  });

  apply();
  if (rows.some(function (r) { return r.hasAttribute("data-working"); })) setTimeout(function () { location.reload(); }, 2500);
})();
