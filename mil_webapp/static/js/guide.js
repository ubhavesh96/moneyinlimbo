/* Guide: a help sheet that explains everything, plus a spotlight tour of the current page.
   Opened from the Guide button in the top bar, or by pressing "?". */
(function () {
  "use strict";
  const { store, toast } = window.MIL;
  const page = document.body.dataset.page || "";
  const role = document.body.dataset.role || "officer";
  const sheet = document.getElementById("guide");
  if (!sheet) return;

  // ------------------------------------------------------------------ page tours
  const TOURS = {
    "officer-queue": [
      ["nav", "Your desk", "Everything you need as a grievance officer: the queue, drafts waiting for you, new complaints and insights. Badges show live counts."],
      ["kpis", "Today at a glance", "Open complaints, drafts waiting for your approval, turnaround breaches and the compensation already owed. Breaches are what reach the RBI Ombudsman."],
      ["toolbar", "Find a complaint fast", "Search by case, customer or UTR, filter by rail or status, or show only Internal Ombudsman referrals and outage clusters. Press J and K to move, Enter to open."],
      ["table", "Sorted by urgency", "Overdue complaints come first, then drafts that need your review. Each row shows the AI's failure point, the statutory deadline and what is owed."],
      ["new", "Open a new complaint", "Upload what the customer handed in. The agents pull the bank's own records and investigate in seconds."],
      ["guide", "Help is always here", "Open the Guide any time (or press ?) for the full manual, the case flow, a demo script and a glossary."],
    ],
    "officer-drafts": [
      ["table", "Waiting for you", "Every draft here is complete but unsent. Open one, check it and approve, or reject it with a reason."],
    ],
    "officer-case": [
      ["casehead", "The case at a glance", "Customer, reference, disputed amount and rail. This header stays pinned while you scroll."],
      ["clock", "The statutory clock", "Red means the RBI reversal deadline has passed and compensation is accruing. Amber means it is still running. Green means nothing is owed."],
      ["stepper", "Where the case is", "Every case moves through nine states. Only the Case Tracker agent can move it, and every move is audited."],
      ["agentlog", "What the agent did", "Every tool call, state change and decision, in order, with a single trace ID. Nothing the agents do is hidden."],
      ["run", "Start the investigation", "The orchestrator runs five specialists: timeline, diagnosis, rules, referral check and drafting."],
      ["evidence", "Evidence, with sources", "One timeline merged from the customer's documents and the bank's own switch and ledger logs. Every event shows the exact line it came from."],
      ["diagnosis", "Where it failed", "The agent's proposed failure point, its confidence and the reasons, each citing a timeline event. Disagree? Override it with a reason and the reply is redrafted."],
      ["rights", "What is owed", "The deadline, days overdue and compensation are calculated by the rules engine in code, never by AI. Unverified rules are flagged."],
      ["referral", "Ombudsman check", "Rejections must go to the Internal Ombudsman first. You also see when the customer may approach the RBI Ombudsman."],
      ["ask", "Ask the case", "Ask anything in plain words. Answers come only from the case facts."],
      ["draft", "The reply", "A cited draft to the customer. Edit it freely; use Diff to compare with the AI version, or Restore to undo."],
      ["gate", "You decide", "Confirm the timeline, the amounts and the text. Only then can you approve, and only then does anything leave the bank."],
      ["tracking", "After sending", "Follow-ups and practice controls: post the credit, simulate an RBI complaint, or skip days to watch the clock."],
    ],
    "officer-new": [
      ["upload", "Upload documents", "Drop in the complaint letter, the statement and the SMS. The agent pulls the bank's own logs for the reference automatically."],
      ["samples", "Or use a sample", "Synthetic hero cases from the project file. Open one directly, or download its documents to try the upload."],
    ],
    "officer-insights": [
      ["kpis", "How the desk is doing", "Replies sent, how many beat the deadline, time to reply and how often you edit the AI's drafts."],
      ["cluster", "Outage clusters", "When many payments fail the same way in the same window, the agent finds the root cause, including customers who have not complained yet."],
    ],
    "auditor-explorer": [
      ["nav", "Oversight", "Read-only views for audit and compliance. You can inspect and export everything but change nothing."],
      ["table", "Every complaint", "Outcome, compensation and approval status for every case. Open Replay to see exactly what happened."],
    ],
    "auditor-replay": [
      ["states", "State history", "Every state change, when and why. Only the Case Tracker moves state."],
      ["decisions", "Human decisions", "Every approval, rejection and override, with the officer and the reason."],
      ["diff", "AI draft against what was sent", "Green words were added by the officer, red words removed."],
      ["trace", "Tool-by-tool trace", "Open any step to see the tool's exact inputs and outputs, and its typed-contract check."],
      ["export", "Export the evidence", "A zip with the PDF, documents, audit trail and a SHA-256 manifest."],
    ],
    "auditor-decisions": [["table", "Decision log", "Every human decision across all cases, newest first."]],
    "auditor-rules": [["table", "Rule library", "The rules the engine applies. Rows marked Verify must be checked against the current RBI text."]],
    "auditor-models": [
      ["targets", "Live evaluation", "Computed now from the code and cases against the project file's targets."],
      ["layers", "Evaluation layers", "What has been measured and what is still planned."],
    ],
    "auditor-exports": [["table", "Evidence packs", "Download a regulator-ready pack for any case. Each export is itself audited."]],
  };

  function steps() {
    return (TOURS[page] || [])
      .map(function (s) { return { el: document.querySelector('[data-tour="' + s[0] + '"]'), title: s[1], text: s[2] }; })
      .filter(function (s) { return s.el && s.el.offsetParent !== null; });
  }

  // ------------------------------------------------------------------ spotlight tour
  let tour = null;
  function endTour() {
    if (!tour) return;
    tour.mask.remove(); tour.spot.remove(); tour.card.remove();
    document.removeEventListener("keydown", tour.keys);
    window.removeEventListener("resize", tour.place);
    window.removeEventListener("scroll", tour.place);
    tour = null;
  }
  function startTour() {
    const list = steps();
    if (!list.length) { toast("There is no tour for this page yet."); return; }
    if (sheet.open) sheet.close();
    endTour();
    const mask = document.createElement("div"); mask.className = "tour-mask";
    const spot = document.createElement("div"); spot.className = "tour-spot";
    const card = document.createElement("div"); card.className = "tour-card"; card.setAttribute("role", "dialog");
    card.setAttribute("aria-live", "polite");
    document.body.append(mask, spot, card);
    let i = 0;
    function place() {
      const s = list[i];
      const r = s.el.getBoundingClientRect();
      const pad = 6;
      spot.style.top = (r.top - pad) + "px"; spot.style.left = (r.left - pad) + "px";
      spot.style.width = (r.width + pad * 2) + "px"; spot.style.height = Math.min(r.height + pad * 2, window.innerHeight - 24) + "px";
      const cw = card.offsetWidth, ch = card.offsetHeight;
      let top = r.bottom + 14, left = Math.min(Math.max(12, r.left), window.innerWidth - cw - 12);
      if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 14);
      if (top < 12 || (r.height > window.innerHeight * .6)) { top = Math.min(window.innerHeight - ch - 12, Math.max(12, r.top + 12)); left = Math.min(window.innerWidth - cw - 12, r.right - cw - 12); }
      card.style.top = top + "px"; card.style.left = Math.max(12, left) + "px";
    }
    function show() {
      const s = list[i];
      s.el.scrollIntoView({ block: "center", behavior: "smooth" });
      card.innerHTML = "";
      const dots = list.map(function (_, k) { return '<i class="' + (k === i ? "on" : "") + '"></i>'; }).join("");
      card.insertAdjacentHTML("beforeend",
        '<div class="row between"><span class="caption faint">' + (i + 1) + " of " + list.length + '</span>' +
        '<button class="iconbtn" data-x aria-label="End tour"><svg class="icon sm"><use href="#i-x"/></svg></button></div>');
      const h = document.createElement("h3"); h.textContent = s.title;
      const p = document.createElement("p"); p.textContent = s.text;
      card.append(h, p);
      card.insertAdjacentHTML("beforeend",
        '<div class="row between mt"><div class="dots">' + dots + '</div><div class="row">' +
        (i > 0 ? '<button class="btn sm" data-prev>Back</button>' : "") +
        '<button class="btn sm primary" data-next>' + (i === list.length - 1 ? "Done" : "Next") + "</button></div></div>");
      card.querySelector("[data-x]").onclick = endTour;
      card.querySelector("[data-next]").onclick = function () { if (i < list.length - 1) { i++; show(); } else endTour(); };
      const pb = card.querySelector("[data-prev]"); if (pb) pb.onclick = function () { i--; show(); };
      card.querySelector("[data-next]").focus({ preventScroll: true });
      setTimeout(place, 260); place();
    }
    function keys(e) {
      if (e.key === "Escape") endTour();
      else if (e.key === "ArrowRight") card.querySelector("[data-next]").click();
      else if (e.key === "ArrowLeft" && i > 0) { i--; show(); }
    }
    mask.addEventListener("click", endTour);
    document.addEventListener("keydown", keys);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { passive: true });
    tour = { mask: mask, spot: spot, card: card, keys: keys, place: place };
    show();
    store("mil-tour-" + page, "seen");
  }

  // ------------------------------------------------------------------ guide content
  const C = { blue: "#0A84FF", indigo: "#5E5CE6", green: "#30D158", orange: "#FF9F0A", red: "#FF453A", teal: "#30B0C7", pink: "#FF375F", gray: "#8E8E93" };
  const officer = role === "officer";
  const SECTIONS = [
    { icon: "spark", color: C.blue, title: "What Money in Limbo does", body:
      "<p>An AI investigation agent for a bank's grievance team. For each failed-payment complaint it <b>rebuilds the payment trail</b>, " +
      "<b>finds where it failed</b>, <b>applies the RBI turnaround and compensation rules</b>, checks whether an <b>ombudsman referral</b> is needed, " +
      "and <b>drafts a cited reply</b>. A grievance officer reviews everything; nothing leaves the bank without their approval.</p>" +
      "<p>All data in this demo is synthetic. The bank, the payment gateway and the regulator are simulated.</p>" },
    { icon: "layers", color: C.indigo, title: "How a case flows", body:
      "<ol><li><b>Reconstruct</b>: customer documents plus the bank's switch and ledger logs become one cited timeline.</li>" +
      "<li><b>Diagnose</b>: the likely failure point, with confidence and reasons. If unsure, the agent asks for a document.</li>" +
      "<li><b>Check</b>: deadline (T+1 or T+5 calendar days), days overdue and Rs 100 per day compensation, calculated in code.</li>" +
      "<li><b>Draft</b>: a footnoted reply and a regulator-ready evidence PDF.</li>" +
      "<li><b>Approve and track</b>: you confirm three checks and approve; the Case Tracker sends, then watches the clock.</li></ol>" +
      "<p>States: intake, reconstructed, diagnosed, rights computed, complaint ready, awaiting party, escalated, resolved, closed.</p>" },
    officer ? { icon: "inbox", color: C.blue, title: "Your screens", body:
      "<ul><li><b>My queue</b>: every complaint, most urgent first. Click a row to open its workbench.</li>" +
      "<li><b>Drafts awaiting approval</b>: finished investigations waiting for your decision.</li>" +
      "<li><b>New complaint</b>: upload the customer's documents, or open a synthetic sample.</li>" +
      "<li><b>Case workbench</b>: evidence on the left, the investigation in the middle, the draft and approval on the right.</li>" +
      "<li><b>Insights</b>: desk metrics and outage clusters across cases.</li></ul>" }
      : { icon: "shield", color: C.teal, title: "Your screens (read-only)", body:
      "<ul><li><b>Audit explorer</b>: every case with outcome and approval status.</li>" +
      "<li><b>Case replay</b>: state history, human decisions, AI draft against the text sent, and every tool's inputs and outputs.</li>" +
      "<li><b>Decision log</b>: all approvals, rejections and overrides.</li><li><b>Rule library</b>: the rules the engine applies.</li>" +
      "<li><b>Model status</b>: live evaluation against the project file's targets.</li><li><b>Evidence exports</b>: zip packs with a SHA-256 manifest.</li></ul>" },
    { icon: "users", color: C.green, title: "The seven agents", body:
      "<ul><li><b>Orchestrator</b>: picks the next specialist and never skips your approval.</li>" +
      "<li><b>Timeline Reconstructor</b>: reads documents and pulls bank records for the UTR.</li>" +
      "<li><b>Failure Diagnoser</b>: proposes the failure point, checks incidents and outage clusters.</li>" +
      "<li><b>Policy and Rights</b>: finds the RBI rule and computes deadline and compensation.</li>" +
      "<li><b>Escalation</b>: Internal Ombudsman referral before any rejection; responses to the RBI Ombudsman.</li>" +
      "<li><b>Evidence and Complaint</b>: drafts the cited reply and builds the evidence PDF.</li>" +
      "<li><b>Case Tracker</b>: sends what you approved, moves the case and watches deadlines.</li></ul>" +
      "<p>See every step on a case under <b>What the agent did</b>.</p>" },
    { icon: "flash", color: C.orange, title: "Statuses and what to do", body:
      "<ul><li><span class='chip overdue'>Overdue</span> deadline passed, compensation accruing: review first.</li>" +
      "<li><span class='chip review'>Needs your review</span> draft ready inside the deadline.</li>" +
      "<li><span class='chip new'>New</span> documents on file: run the investigation.</li>" +
      "<li><span class='chip working'>Agent working</span> the page refreshes when done.</li>" +
      "<li><span class='chip waiting'>Awaiting customer</span> sent, or waiting for a document from the customer.</li>" +
      "<li><span class='chip escalated'>Escalated</span> a follow-up was missed, or an ombudsman step is in progress.</li>" +
      "<li><span class='chip resolved'>Resolved</span> money credited; close it to archive.</li></ul>" },
    { icon: "lock", color: C.red, title: "Approval rules", body:
      "<ul><li>Tick all three checks: <b>timeline</b>, <b>amounts</b>, <b>text</b>. Editing the text unticks the text check.</li>" +
      "<li>Rejecting a draft needs a reason of at least 10 characters; it is logged.</li>" +
      "<li>Overriding the failure point needs a reason; the reply is redrafted.</li>" +
      "<li>A complaint the bank proposes to reject goes to the <b>Internal Ombudsman</b> first; the reply stays locked until they concur.</li>" +
      "<li>Compensation keeps growing until the credit actually posts.</li>" +
      "<li>Auditors can never change a case.</li></ul>" },
    officer ? { icon: "play", color: C.pink, title: "Practice controls", body:
      "<p>After a reply is sent, the workbench's Tracking card simulates the outside world:</p>" +
      "<ul><li><b>Payments ops posts the credit</b>: the case resolves.</li><li><b>Customer files with RBI Ombudsman</b>: the agent drafts your response.</li>" +
      "<li><b>Internal Ombudsman concurs</b>: unlocks a rejection reply.</li><li><b>Skip days</b>: watch breaches and escalation.</li></ul>" +
      "<p>For thin-evidence cases, <b>Customer sent it (practice)</b> delivers the requested document.</p>" } : null,
    { icon: "clock", color: C.teal, title: "Three-minute demo", body:
      "<ol><li><b>Intake</b>: New complaint, upload Case A's documents (or open MIL-24001 and run the investigation).</li>" +
      "<li><b>Investigation</b>: timeline with sources, diagnosis, rights card: T+1 breached by 6 days = Rs 600.</li>" +
      "<li><b>Approval gate</b>: edit the reply, tick the checks, approve; then post the credit.</li>" +
      "<li><b>Outage cluster</b>: Insights, Coastal Co-operative Bank.</li>" +
      "<li><b>Audit and evals</b>: switch to the auditor (top right), open a replay and Model status.</li></ol>" +
      "<p>Before a demo: My queue, Reset demo queue.</p>" },
    { icon: "cpu", color: C.gray, title: "Keyboard shortcuts", body:
      "<ul><li><kbd>?</kbd> open this guide</li><li><kbd>J</kbd> / <kbd>K</kbd> move through the queue, <kbd>Enter</kbd> open</li>" +
      "<li><kbd>Esc</kbd> close a dialog or the tour</li><li><kbd>←</kbd> <kbd>→</kbd> move through the tour</li></ul>" },
    { icon: "book", color: C.indigo, title: "Glossary", body:
      "<ul><li><b>UTR / RRN</b>: the unique reference of a UPI/IMPS or card transaction.</li>" +
      "<li><b>TAT</b>: turnaround time set by RBI. <b>T</b> is the transaction day; T+1 means the next calendar day.</li>" +
      "<li><b>CBS</b>: core banking system. <b>NPCI switch</b>: the network that routes UPI and IMPS.</li>" +
      "<li><b>Internal Ombudsman</b>: a senior officer inside the bank who reviews complaints before rejection.</li>" +
      "<li><b>RBI Ombudsman</b>: the regulator's complaint service (cms.rbi.org.in), open 30 days after the complaint.</li>" +
      "<li><b>Outage cluster</b>: many transactions failing the same way in the same window.</li></ul>" },
  ].filter(Boolean);

  function build() {
    const n = steps().length;
    const name = role === "officer" ? "Priya" : "Ravi";
    sheet.innerHTML =
      '<div class="dh"><h2 id="guide-title">Guide</h2><button type="button" class="iconbtn" data-close aria-label="Close guide"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
      '<div class="db" style="padding-bottom:28px">' +
      '<div class="guide-hero"><h3>Hi ' + name + ', welcome to Money in Limbo</h3>' +
      "<p>" + (n ? "Take a " + n + "-step tour of this page, or browse the topics below." : "Browse the topics below.") + "</p>" +
      (n ? '<button type="button" class="btn sm" data-tour-start><svg class="icon sm"><use href="#i-play"/></svg>Tour this page</button>' : "") + "</div>" +
      '<label class="sr-only" for="guide-q">Search the guide</label>' +
      '<div class="toolbar" style="padding:0;border:0"><div class="search" style="max-width:none"><svg class="icon"><use href="#i-search"/></svg>' +
      '<input id="guide-q" class="input" type="search" placeholder="Search the guide"></div></div>' +
      '<div class="stack sm" id="guide-list"></div></div>';
    const list = sheet.querySelector("#guide-list");
    SECTIONS.forEach(function (s, k) {
      const d = document.createElement("details");
      d.className = "guide-section";
      if (k === 0) d.open = true;
      d.innerHTML = '<summary><span class="gi" style="background:' + s.color + '"><svg class="icon sm" style="stroke:#fff"><use href="#i-' + s.icon + '"/></svg></span>' +
        s.title + '</summary><div class="gb">' + s.body + "</div>";
      list.appendChild(d);
    });
    sheet.querySelector("#guide-q").addEventListener("input", function (e) {
      const q = e.target.value.toLowerCase().trim();
      list.querySelectorAll(".guide-section").forEach(function (d) {
        const hit = !q || d.textContent.toLowerCase().indexOf(q) >= 0;
        d.hidden = !hit;
        if (q && hit) d.open = true;
      });
    });
    const ts = sheet.querySelector("[data-tour-start]");
    if (ts) ts.addEventListener("click", startTour);
  }

  function openGuide() { build(); sheet.showModal(); }
  document.querySelectorAll("[data-guide-open]").forEach(function (b) { b.addEventListener("click", openGuide); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "?" && !e.target.closest("input, textarea, select") && !sheet.open) { e.preventDefault(); openGuide(); }
  });

  // Deep links: #guide opens the guide, #tour starts this page's tour (shareable help links).
  if (location.hash === "#guide") { openGuide(); return; }
  if (location.hash === "#tour") { setTimeout(startTour, 300); return; }

  // First visit to a page: offer its tour once (skipped while the agent is working).
  if (steps().length && !store("mil-tour-" + page) && !document.querySelector("[data-running]")) {
    setTimeout(function () {
      store("mil-tour-" + page, "offered");
      toast("New here? Take a quick tour of this page.", false, { label: "Start tour", run: startTour });
    }, 900);
  }
  window.MIL.startTour = startTour;
})();
