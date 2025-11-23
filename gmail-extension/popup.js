
// popup.js — simple UI for showing fetched emails + ML verdicts
console.log("[popup.js] Loaded");

// Run once popup UI is ready
document.addEventListener("DOMContentLoaded", () => {
  console.log("[popup] DOM ready");

  const fetchBtn     = document.getElementById("fetchBtn");
  const list         = document.getElementById("emailList");
  const apiKeyWrap   = document.getElementById("apiKeySection");
  const apiKeyInput  = document.getElementById("apiKey");
  const saveKeyBtn   = document.getElementById("saveKey");
  const saveStatus   = document.getElementById("saveStatus");
  const toggleKeyBtn = document.getElementById("toggleKey");

  // Basic HTML escaping for safety
  const esc = (str = "") =>
    str.replace(/[&<>"']/g, (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[m]));

  // ---------------------------------------------------------------
  // Load stored Vision API key (if present)
  // ---------------------------------------------------------------
  let currentKey = "";

  chrome.storage.local.get("visionApiKey", ({ visionApiKey }) => {
    currentKey = visionApiKey || "";

    if (!currentKey) {
      // No key saved → show input box
      apiKeyWrap && (apiKeyWrap.style.display = "block");
      saveKeyBtn && (saveKeyBtn.disabled = true);
    } else {
      // Hide section if key already exists
      apiKeyWrap && (apiKeyWrap.style.display = "none");
    }

    apiKeyInput && (apiKeyInput.value = currentKey);
  });

  // Enable “Save” button when key changes
  apiKeyInput?.addEventListener("input", () => {
    const changed = apiKeyInput.value.trim() !== currentKey.trim();
    saveKeyBtn && (saveKeyBtn.disabled = !changed);
    saveStatus && (saveStatus.textContent = "");
  });

  // Show/hide key
  toggleKeyBtn?.addEventListener("click", () => {
    if (apiKeyInput) {
      apiKeyInput.type =
        apiKeyInput.type === "password" ? "text" : "password";
    }
  });

  // Save key
  saveKeyBtn?.addEventListener("click", () => {
    const newKey = apiKeyInput?.value.trim() || "";
    chrome.storage.local.set({ visionApiKey: newKey }, () => {
      currentKey = newKey;
      apiKeyWrap && (apiKeyWrap.style.display = "none");
    });
  });

  // ---------------------------------------------------------------
  // Render emails + OCR + ML verdict section
  // ---------------------------------------------------------------
  function render(emails, ocrMap) {
    if (!list) return;

    list.innerHTML = "";

    if (!emails || emails.length === 0) {
      list.innerHTML = "<li>No emails found</li>";
      return;
    }

    emails.forEach((email) => {
      const li = document.createElement("li");
      li.className = "email-item";

      const mg = email.mailguard || {};
      const verdict = (mg.verdict || "unknown").toLowerCase();
      const score   = typeof mg.score === "number" ? mg.score : null;
      const reasons = Array.isArray(mg.reasons) ? mg.reasons : [];

      li.classList.add(verdict);

      const reasonsText = reasons.length ? esc(reasons.join(", ")) : "";

      // OCR results
      const ocrList = (ocrMap && ocrMap[email.id]) || [];
      const ocrHtml = ocrList
        .map(x => `
          <div class="ocr" style="white-space:pre-wrap;">
            <b>${esc(x.filename || "attachment")}</b> ${esc((x.text || "").trim())}
          </div>
        `).join("");

      // Body block
      const bodyBlock = email.bodyText
        ? `<div class="ocr" style="white-space:pre-wrap;"><b>Body text</b>\n${esc(email.bodyText.trim())}</div>`
        : "";

      // Friendly verdict text
      const verdictLabel =
        verdict === "spam"        ? "⚠️ Spam" :
        verdict === "benign"      ? "✅ Benign" :
        verdict === "suspicious"  ? "⚠️ Suspicious" :
        esc(verdict);

      const scoreLabel =
        score !== null ? `Risk score: ${Math.round(score * 100)}%`
                       : `Risk score: —`;

      const reasonsHtml = reasonsText
        ? `<div class="verdict-reason" title="${reasonsText}">Reasons: ${reasonsText}</div>`
        : "";

      li.innerHTML = `
        <div class="email-subject">${esc(email.subject || "(No Subject)")}</div>
        <div class="verdict-row">
          <span class="verdict-badge ${verdict}" title="Verdict: ${esc(verdict)}">
            ${verdictLabel}
          </span>
          <span class="verdict-score" style="margin-left:8px">${scoreLabel}</span>
          ${reasonsHtml}
        </div>
        <div class="email-from">From: ${esc(email.from || "(Unknown)")}</div>
        <div class="email-snippet">${esc(email.snippet || "")}</div>
        ${bodyBlock}
        ${ocrHtml}
      `;

      list.appendChild(li);
    });
  }

  // Expose for debugging from DevTools
  window.render = render;

  // ---------------------------------------------------------------
  // Manual "Fetch" button → call background.js for fresh data
  // ---------------------------------------------------------------
  fetchBtn?.addEventListener("click", () => {
    list.innerHTML = "<li>Fetching…</li>";

    chrome.runtime.sendMessage({ action: "fetchEmails" }, (response) => {
      if (chrome.runtime.lastError) {
        list.innerHTML =
          `<li class="error">${esc(chrome.runtime.lastError.message)}</li>`;
        return;
      }

      if (!response || response.error) {
        list.innerHTML =
          `<li class="error">${esc(response?.error || "Unknown error")}</li>`;
        return;
      }

      render(response.emails, response.ocrMap);
    });
  });

  // ---------------------------------------------------------------
  // Auto-render most recent data when popup opens
  // ---------------------------------------------------------------
  chrome.storage.local.get(["emails", "ocrMap"], ({ emails, ocrMap }) => {
    if (emails && emails.length) {
      render(emails, ocrMap);
    } else {
      list.innerHTML = "<li>No emails found</li>";
    }
  });
});

