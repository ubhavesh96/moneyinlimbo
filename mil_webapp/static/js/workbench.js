/* Case workbench: approval gate, edits, overrides, document requests, practice events, chat.
   The page is server-rendered; actions call the agent API and then reload (or poll while the agent works). */
(function () {
  "use strict";
  const wb = document.getElementById("wb");
  if (!wb) return;
  const id = wb.dataset.case;
  const { api, act, toast, store } = window.MIL;
  const $ = function (sel) { return wb.querySelector(sel) || document.querySelector(sel); };

  // While the agent works, poll until it is done, then re-render the page.
  if (wb.hasAttribute("data-running")) {
    const poll = async function () {
      try {
        const c = await api("cases/" + id);
        if (!c.running) { location.reload(); return; }
      } catch (e) { /* keep polling through brief hiccups */ }
      setTimeout(poll, 1200);
    };
    setTimeout(poll, 1000);
  }

  // Tabs (timeline / documents)
  wb.querySelectorAll("[role=tab]").forEach(function (tab) {
    tab.addEventListener("click", function () {
      wb.querySelectorAll("[role=tab]").forEach(function (t) {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
    });
  });

  // Pane layout (keyboard-accessible alternative to dragging), remembered per browser
  const panes = document.getElementById("panes");
  function layout(name) {
    if (!panes) return;
    panes.className = "panes" + (name ? " " + name : "");
    store("mil-layout", name || "");
    document.querySelectorAll("[data-layout]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.layout === (name || ""))); });
  }
  layout(store("mil-layout") || "");
  document.querySelectorAll("[data-layout]").forEach(function (b) {
    b.addEventListener("click", function () { layout(b.dataset.layout); });
  });

  const reload = function () { location.reload(); };

  // Run investigation (intake)
  document.querySelectorAll("[data-investigate]").forEach(function (b) {
    b.addEventListener("click", function () { act(b, async function () { await api("cases/" + id + "/investigate", { method: "POST" }); reload(); }); });
  });

  // ---- draft and approval gate ----
  const draft = document.getElementById("draft");
  const originalEl = document.getElementById("original-text");
  const original = originalEl ? JSON.parse(originalEl.textContent) : "";
  const saved = draft ? draft.value : "";
  const checks = Array.from(document.querySelectorAll("[data-check]"));
  const approveOpen = document.querySelector("[data-approve-open]");
  const hint = document.getElementById("gatehint");
  const dirtyNote = document.getElementById("dirty");
  const labels = { timeline: "verify the timeline", amounts: "confirm the amounts", text: "approve the text" };

  function dirty() { return draft && draft.value !== saved; }
  function gate() {
    const done = checks.filter(function (c) { return c.checked; });
    const count = document.getElementById("checkcount");
    if (count) count.textContent = done.length + " of " + checks.length + " confirmed";
    const bar = document.getElementById("gateprogress");
    if (bar && checks.length) bar.style.width = (100 * done.length / checks.length) + "%";
    const missing = checks.filter(function (c) { return !c.checked; }).map(function (c) { return labels[c.dataset.check]; });
    if (dirtyNote) dirtyNote.hidden = !dirty();
    if (hint) {
      hint.hidden = !missing.length && !dirty();
      hint.textContent = dirty() ? "Save your edits first: the text check resets when the draft changes."
        : "Approval is disabled until you " + missing.join(", ") + ".";
    }
    if (approveOpen && !approveOpen.hasAttribute("data-locked")) approveOpen.disabled = missing.length > 0 || dirty();
  }
  if (approveOpen && approveOpen.disabled) approveOpen.setAttribute("data-locked", "");
  checks.forEach(function (c) {
    c.addEventListener("change", function () {
      act(null, async function () {
        await api("cases/" + id + "/checklist", { method: "PUT", json: { item: c.dataset.check, checked: c.checked } });
      }).then(gate);
      gate();
    });
  });
  if (draft) draft.addEventListener("input", gate);
  gate();

  const save = document.querySelector("[data-save]");
  if (save) save.addEventListener("click", function () {
    act(save, async function () {
      await api("cases/" + id + "/draft", { method: "PUT", json: { kind: draft.dataset.kind, text: draft.value } });
      toast("Draft saved. Re-confirm the text before approving.");
      setTimeout(reload, 600);
    });
  });

  document.querySelectorAll("[data-restore]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!window.confirm("Replace your edits with the AI draft?")) return;
      act(b, async function () { await api("cases/" + id + "/draft/restore", { method: "POST", json: { kind: b.dataset.restore } }); reload(); });
    });
  });

  // Word diff of the AI draft against the current text
  function esc(s) { return s.replace(/[&<>"]/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]; }); }
  function diff(a, b) {
    const x = a.split(/(\s+)/), y = b.split(/(\s+)/);
    if (x.length * y.length > 4e6) return "<p>Too long to compare here.</p>";
    const n = x.length, m = y.length, L = [];
    for (let i = 0; i <= n; i++) L.push(new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
      L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0, out = "";
    while (i < n && j < m) {
      if (x[i] === y[j]) { out += esc(x[i]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) { out += "<del>" + esc(x[i++]) + "</del>"; }
      else { out += "<ins>" + esc(y[j++]) + "</ins>"; }
    }
    while (i < n) out += "<del>" + esc(x[i++]) + "</del>";
    while (j < m) out += "<ins>" + esc(y[j++]) + "</ins>";
    return out.replace(/\n/g, "<br>");
  }
  const diffBtn = document.querySelector("[data-diff]"), diffView = document.getElementById("diffview");
  if (diffBtn && diffView) diffBtn.addEventListener("click", function () {
    const on = diffBtn.getAttribute("aria-pressed") !== "true";
    diffBtn.setAttribute("aria-pressed", String(on));
    diffView.hidden = !on; draft.hidden = on;
    if (on) diffView.innerHTML = original === draft.value
      ? "<p class='muted'>No changes from the AI draft.</p>" : diff(original, draft.value);
  });

  if (approveOpen) approveOpen.addEventListener("click", function () {
    const dlg = document.getElementById("dlg-approve");
    if (dlg) dlg.showModal();
  });
  document.querySelectorAll("[data-approve]").forEach(function (b) {
    b.addEventListener("click", function () {
      act(b, async function () {
        await api("cases/" + id + "/approve", { method: "POST", json: { kind: b.dataset.approve } });
        reload();
      });
    });
  });

  function formHandler(sel, fn) {
    const f = document.querySelector(sel);
    if (!f) return;
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(f).entries());
      act(f.querySelector("[type=submit]"), async function () { await fn(data); reload(); });
    });
  }
  formHandler("[data-reject]", function (d) {
    return api("cases/" + id + "/reject", { method: "POST", json: { kind: draft.dataset.kind, reason: d.reason } });
  });
  formHandler("[data-request]", function (d) {
    return api("cases/" + id + "/request-documents", { method: "POST", json: { document: d.document, note: d.note || "" } });
  });
  formHandler("[data-override]", function (d) {
    return api("cases/" + id + "/override", { method: "POST", json: { failure_point: d.failure_point, reason: d.reason } });
  });

  // Documents: practice delivery and real upload
  document.querySelectorAll("[data-practice-doc]").forEach(function (b) {
    b.addEventListener("click", function () {
      act(b, async function () { await api("cases/" + id + "/documents/practice", { method: "POST" }); reload(); });
    });
  });
  document.querySelectorAll("[data-upload]").forEach(function (input) {
    input.addEventListener("change", function () {
      if (!input.files.length) return;
      const fd = new FormData();
      Array.from(input.files).forEach(function (f) { fd.append("files", f); });
      act(null, async function () { await api("cases/" + id + "/documents", { method: "POST", form: fd }); reload(); });
    });
  });

  // Practice controls
  document.querySelectorAll("[data-sim]").forEach(function (b) {
    b.addEventListener("click", function () {
      act(b, async function () {
        await api("cases/" + id + "/simulate", { method: "POST", json: { event: b.dataset.sim, days: Number(b.dataset.days || 0) } });
        reload();
      });
    });
  });
  document.querySelectorAll("[data-close-case]").forEach(function (b) {
    b.addEventListener("click", function () {
      act(b, async function () { await api("cases/" + id + "/close", { method: "POST" }); reload(); });
    });
  });

  // Ask about this case
  const chat = document.querySelector("[data-chat]");
  if (chat) chat.addEventListener("submit", function (e) {
    e.preventDefault();
    const q = chat.q.value.trim();
    if (!q) return;
    act(chat.querySelector("button"), async function () {
      await api("cases/" + id + "/chat", { method: "POST", json: { message: q } });
      reload();
    });
  });
})();
