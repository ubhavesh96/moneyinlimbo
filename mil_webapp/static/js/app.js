/* Shared behaviour for every page: API calls with CSRF, appearance, account menu, dialogs, snackbars. */
(function () {
  "use strict";

  function cookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  /** localStorage that never throws (private windows, blocked storage). */
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }

  /** Call the agent API through Django. Throws Error(detail) on failure. */
  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", headers: { "X-CSRFToken": cookie("csrftoken") } };
    if (opts.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.form) {
      init.body = opts.form;
    }
    const r = await fetch("/api/" + path, init);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map(function (d) { return d.msg; }).join("; ");
      throw new Error(msg || ("Request failed (" + r.status + ")"));
    }
    return data;
  }

  // Snackbar (MUI) with an optional action button
  let toastTimer = null;
  function toast(msg, bad, action) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = "";
    const span = document.createElement("span");
    span.textContent = msg;
    el.appendChild(span);
    if (action) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = action.label;
      b.addEventListener("click", function () { el.hidden = true; action.run(); });
      el.appendChild(b);
    }
    el.className = "toast" + (bad ? " bad" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, action ? 9000 : 4200);
  }

  /** Run an async action from a button, disabling it meanwhile and reporting errors. */
  async function act(button, fn) {
    if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); }
    try { return await fn(); }
    catch (e) { toast(e.message, true); return null; }
    finally { if (button) { button.disabled = false; button.removeAttribute("aria-busy"); } }
  }

  // Appearance: light / dark / auto (follows the system)
  const root = document.documentElement;
  function applyTheme(mode) {
    if (mode === "light" || mode === "dark") root.dataset.theme = mode; else delete root.dataset.theme;
    store("mil-theme", mode === "auto" ? null : mode);
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.themeSet === (mode || "auto")));
    });
  }
  applyTheme(store("mil-theme") || "auto");
  document.querySelectorAll("[data-theme-set]").forEach(function (b) {
    b.addEventListener("click", function () { applyTheme(b.dataset.themeSet); });
  });

  // Account menu
  const menu = document.getElementById("account");
  const menuBtn = document.querySelector("[data-menu-open]");
  function setMenu(open) {
    if (!menu || !menuBtn) return;
    menu.hidden = !open;
    menuBtn.setAttribute("aria-expanded", String(open));
  }
  if (menuBtn) menuBtn.addEventListener("click", function (e) { e.stopPropagation(); setMenu(menu.hidden); });
  document.addEventListener("click", function (e) { if (menu && !menu.hidden && !menu.contains(e.target)) setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setMenu(false); });

  // Mobile navigation drawer
  document.querySelectorAll("[data-navtoggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      const nav = document.getElementById("nav");
      const open = nav.classList.toggle("open");
      b.setAttribute("aria-expanded", String(open));
    });
  });

  // <dialog> helpers: [data-open="id"] opens, [data-close] closes; clicking the backdrop closes
  document.addEventListener("click", function (e) {
    const opener = e.target.closest("[data-open]");
    if (opener) {
      const d = document.getElementById(opener.dataset.open);
      if (d && d.showModal) d.showModal();
    }
    const closer = e.target.closest("[data-close]");
    if (closer) {
      const d = closer.closest("dialog");
      if (d) d.close();
    }
    if (e.target.tagName === "DIALOG") e.target.close();
  });

  // Clickable table rows (the row's link stays the accessible target)
  document.addEventListener("click", function (e) {
    const row = e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a, button, input, select, label")) location.href = row.dataset.href;
  });

  // Drag-and-drop file zones: show chosen file names, highlight while dragging
  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    const input = zone.querySelector("input[type=file]");
    const names = zone.querySelector("[data-dropzone-names]");
    function show() { if (names && input.files.length) names.textContent = Array.from(input.files).map(function (f) { return f.name; }).join(", "); }
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.remove("over"); }); });
    zone.addEventListener("drop", function (e) { e.preventDefault(); if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); } });
  });

  // Demo reset (officer only)
  document.querySelectorAll("[data-reset-demo]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!window.confirm("Reset the demo? This deletes every case and seeds a fresh queue.")) return;
      act(b, async function () { await api("demo/reset", { method: "POST" }); location.reload(); });
    });
  });

  window.MIL = { api: api, toast: toast, act: act, store: store };
})();
