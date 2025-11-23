
// MailGuard content script (ML-only)
// Injects small badges into Gmail rows based on the ML verdict.

console.log("MailGuard content script (ML-only) loaded");

// ---------------------------------------------------------------------------
//  Inject CSS once for the badges
// ---------------------------------------------------------------------------
(function injectMailGuardStyles() {
  if (document.getElementById("mailguard-inline-style")) return;

  const css = `
    .mailguard-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 11px;
      color: #fff;
      margin-left: 8px;
      line-height: 1.8;
      box-shadow: 0 1px 0 rgba(0, 0, 0, .06);
      cursor: default;
    }
    .mailguard-safe       { background: #137333; }
    .mailguard-risk       { background: #d93025; }
    .mailguard-suspicious { background: #f0a500; color: #111; }
    .mailguard-unknown    { background: #9aa0a6; }

    .mailguard-badge .mg-score {
      font-weight: 600;
      opacity: .9;
      background: rgba(255, 255, 255, .15);
      padding: 0 6px;
      border-radius: 999px;
    }
  `;

  const style = document.createElement("style");
  style.id = "mailguard-inline-style";
  style.textContent = css;
  document.documentElement.appendChild(style);
})();

// ---------------------------------------------------------------------------
//  Small utilities
// ---------------------------------------------------------------------------

// Simple string hash used for cache keys (subject/snippet etc.)
function hashString(str) {
  str = (str || "").slice(0, 800);
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0;
  }
  return h.toString(16);
}

// Map verdict to CSS class
function verdictToClass(verdict) {
  const v = String(verdict || "unknown").toLowerCase();
  if (v === "spam" || v === "risk") return "mailguard-risk";
  if (v === "benign") return "mailguard-safe";
  if (v === "suspicious") return "mailguard-suspicious";
  return "mailguard-unknown";
}

// Ensure there is a container span next to the Gmail subject
function ensureBadgeContainer(row) {
  const subjectHost = row.querySelector(".y6");
  if (!subjectHost) return null;

  let holder = subjectHost.querySelector(".mailguard-holder");
  if (!holder) {
    holder = document.createElement("span");
    holder.className = "mailguard-holder";
    holder.style.marginLeft = "6px";
    subjectHost.appendChild(holder);
  }
  return holder;
}

// ---------------------------------------------------------------------------
//  Tooltip and badge rendering (ML-only)
// ---------------------------------------------------------------------------

function formatTooltip(verdict, score, reasons) {
  const v = (verdict || "unknown").toUpperCase();
  const pct = typeof score === "number" ? ` ${Math.round(score * 100)}%` : "";
  let text = `MailGuard: ${v}${pct}`;

  const list = Array.isArray(reasons)
    ? reasons.filter(Boolean).slice(0, 4)
    : [];

  if (list.length) {
    text += "\n• " + list.join("\n• ");
  }

  return text;
}

function renderBadge(holder, verdict, score, reasons) {
  holder.innerHTML = "";

  const badge = document.createElement("span");
  badge.className = `mailguard-badge ${verdictToClass(verdict)}`;
  badge.textContent = (verdict || "unknown").toUpperCase();

  if (typeof score === "number") {
    const pct = Math.round(score * 100);
    const scoreSpan = document.createElement("span");
    scoreSpan.className = "mg-score";
    scoreSpan.textContent = `${pct}%`;
    badge.appendChild(scoreSpan);
  }

  const tooltip = formatTooltip(verdict, score, reasons);
  badge.title = tooltip;
  badge.setAttribute("aria-label", tooltip);

  holder.appendChild(badge);
}

// ---------------------------------------------------------------------------
//  In-memory cache for ML verdicts (ML-only)
// ---------------------------------------------------------------------------

let mailguardCache = Object.create(null);

function putCache(key, verdict, score, reasons) {
  if (!key) return;
  mailguardCache[key] = {
    verdict,
    score,
    reasons: Array.isArray(reasons) ? reasons : [],
  };
}

// Build cache from the emails stored by the background script
function buildCacheFromEmails(emails) {
  mailguardCache = Object.create(null);
  if (!Array.isArray(emails)) return;

  for (const email of emails) {
    const verdict = email?.mailguard?.verdict || "unknown";
    const score =
      typeof email?.mailguard?.score === "number" ? email.mailguard.score : null;
    const reasons = email?.mailguard?.reasons || [];

    if (email?.id) {
      putCache(`id:${email.id}`, verdict, score, reasons);
    }

    const subj = (email?.subject || "").trim().toLowerCase();
    const snip = (email?.snippet || "").trim().toLowerCase();

    if (subj || snip) {
      putCache(
        `ss:${hashString(subj + "|" + snip)}`,
        verdict,
        score,
        reasons
      );
    }

    if (subj) {
      putCache(`s:${hashString(subj)}`, verdict, score, reasons);
    }

    const from = (email?.from || "").trim().toLowerCase();
    if (from && subj) {
      putCache(
        `fs:${hashString(from + "|" + subj)}`,
        verdict,
        score,
        reasons
      );
    }
  }
}

function refreshCacheAndRescan() {
  chrome.storage.local.get(["emails"], ({ emails }) => {
    buildCacheFromEmails(emails || []);
    debouncedScan(0);
  });
}

// ---------------------------------------------------------------------------
//  Reading data from a Gmail row
// ---------------------------------------------------------------------------

function extractRowText(row) {
  const subject =
    row.querySelector(".bog")?.textContent?.trim() || "";
  const snippet =
    row
      .querySelector(".y2")
      ?.textContent?.replace(/^\s*-\s*/, "")
      .trim() || "";
  const from =
    row.querySelector(".yX.xY .yW span")?.getAttribute("email") || "";

  return { subject, snippet, from };
}

// Try to find a cached verdict for this row using IDs or hashes
function findVerdictForRow(row) {
  const lastMsgId = row.getAttribute("data-legacy-last-message-id");
  const msgId = row.getAttribute("data-legacy-message-id");
  const threadId = row.getAttribute("data-legacy-thread-id");

  if (lastMsgId && mailguardCache[`id:${lastMsgId}`]) {
    return mailguardCache[`id:${lastMsgId}`];
  }
  if (msgId && mailguardCache[`id:${msgId}`]) {
    return mailguardCache[`id:${msgId}`];
  }
  if (threadId && mailguardCache[`id:${threadId}`]) {
    return mailguardCache[`id:${threadId}`];
  }

  const { subject, snippet, from } = extractRowText(row);
  const subj = subject.trim().toLowerCase();
  const snip = snippet.trim().toLowerCase();
  const frm = from.trim().toLowerCase();

  if (frm && subj) {
    const key = `fs:${hashString(frm + "|" + subj)}`;
    if (mailguardCache[key]) return mailguardCache[key];
  }

  if (subj || snip) {
    const key = `ss:${hashString(subj + "|" + snip)}`;
    if (mailguardCache[key]) return mailguardCache[key];
  }

  if (subj) {
    const key = `s:${hashString(subj)}`;
    if (mailguardCache[key]) return mailguardCache[key];
  }

  return null;
}

// ---------------------------------------------------------------------------
//  Remember badge state on the DOM row itself
// ---------------------------------------------------------------------------

function rememberVerdict(row, verdict, score, reasons) {
  row.dataset.mgVerdict = verdict || "unknown";
  row.dataset.mgScore =
    typeof score === "number" ? String(score) : "";
  row.dataset.mgReasons = JSON.stringify(
    Array.isArray(reasons) ? reasons : []
  );
}

function ensureBadgeStillThere(row) {
  if (!row.dataset.mgVerdict) return;

  const holder = row.querySelector(".mailguard-holder");
  if (!holder) {
    const newHolder = ensureBadgeContainer(row);
    if (!newHolder) return;

    const verdict = row.dataset.mgVerdict;
    const score = row.dataset.mgScore ? Number(row.dataset.mgScore) : null;
    const reasons = JSON.parse(row.dataset.mgReasons || "[]");

    renderBadge(newHolder, verdict, score, reasons);
  }
}

// ---------------------------------------------------------------------------
//  Main per-row processing
// ---------------------------------------------------------------------------

function processRow(row) {
  if (row.dataset.mailguardProcessed === "1") {
    // Row already processed, just make sure the badge still exists
    ensureBadgeStillThere(row);
    return;
  }

  const hit = findVerdictForRow(row);
  if (!hit) return;

  const holder = ensureBadgeContainer(row);
  if (!holder) return;

  renderBadge(holder, hit.verdict, hit.score, hit.reasons);
  rememberVerdict(row, hit.verdict, hit.score, hit.reasons);

  row.dataset.mailguardProcessed = "1";

  // If Gmail re-renders the row, re-attach the badge
  if (!row._mgObserver) {
    row._mgObserver = new MutationObserver(() => ensureBadgeStillThere(row));
    row._mgObserver.observe(row, { childList: true, subtree: true });
  }
}

// ---------------------------------------------------------------------------
//  Scanning logic
// ---------------------------------------------------------------------------

function scanVisibleRows() {
  const rows = document.querySelectorAll('div[role="main"] tr.zA');
  rows.forEach(processRow);
}

let scanTimer;
function debouncedScan(delay = 120) {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(scanVisibleRows, delay);
}

// Watch the DOM for changes (e.g. folder change, new mail, etc.)
const listObserver = new MutationObserver(() => debouncedScan());
listObserver.observe(document.body, { childList: true, subtree: true });

// Re-scan when the user scrolls the message list
function hookScroll() {
  const scroller =
    document.querySelector('div[role="main"] .aeF') ||
    document.querySelector('div[role="main"]');

  if (scroller && !scroller._mgScrollHooked) {
    scroller._mgScrollHooked = true;
    scroller.addEventListener(
      "scroll",
      () => debouncedScan(100),
      { passive: true }
    );
  }
}
hookScroll();

// Update cache whenever the background script updates stored emails
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.emails) {
    buildCacheFromEmails(changes.emails.newValue || []);
    debouncedScan(0);
  }
});

// Initial cache warm-up + a few retries in case Gmail loads slowly
refreshCacheAndRescan();
setTimeout(refreshCacheAndRescan, 400);
setTimeout(refreshCacheAndRescan, 1200);
setTimeout(refreshCacheAndRescan, 2500);

// Periodic scan as a fallback
setInterval(() => debouncedScan(200), 4000);




