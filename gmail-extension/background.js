
// ============================================================================
// Simple helpers around chrome.storage so we can use async/await
// ============================================================================

function readFromStorage(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, (result) => {
      resolve(result || {});
    });
  });
}

function writeToStorage(obj) {
  return new Promise((resolve) => {
    chrome.storage.local.set(obj, () => resolve());
  });
}

// ============================================================================
// Google auth helpers
// ============================================================================

async function getInteractiveAuthToken() {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive: true }, (token) => {
      if (chrome.runtime.lastError || !token) {
        return reject(chrome.runtime.lastError);
      }
      resolve(token);
    });
  });
}

async function googleApiFetch(url, token) {
  const res = await fetch(url, {
    headers: { Authorization: "Bearer " + token },
  });

  if (!res.ok) {
    throw new Error(`GAPI ${res.status}: ${await res.text()}`);
  }

  return res.json();
}

// ============================================================================
// MIME + body helpers
// ============================================================================

function collectImageParts(payload, acc = []) {
  if (!payload) return acc;

  const mime = payload.mimeType || "";
  const hasAttachment = payload.body?.attachmentId;

  if (mime.startsWith("image/") && hasAttachment) {
    acc.push(payload);
  }

  (payload.parts || []).forEach((part) => collectImageParts(part, acc));
  return acc;
}

function base64UrlToBase64(b64url) {
  return (b64url || "").replace(/-/g, "+").replace(/_/g, "/");
}

function decodeBodyData(b64url) {
  if (!b64url) return "";

  const b64 = base64UrlToBase64(b64url);

  try {
    // Try proper UTF-8 decoding
    const binary = atob(b64);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder("utf-8").decode(bytes);
  } catch {
    // Fallback to plain atob if UTF-8 fails
    try {
      return atob(b64);
    } catch {
      return "";
    }
  }
}

// ============================================================================
// HTML → plain text cleanup
// ============================================================================

function htmlToText(html) {
  if (!html) return "";

  return html
    .replace(/<head[\s\S]*?<\/head>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<\/div>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/li>/gi, "\n")
    .replace(/<li>/gi, "• ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function pickBodyText(payload) {
  let plain = null;
  let html = null;

  (function walk(part) {
    if (!part) return;

    const mt = (part.mimeType || "").toLowerCase();

    if (mt === "text/plain" && part.body?.data) {
      plain = decodeBodyData(part.body.data);
    }

    if (mt === "text/html" && part.body?.data) {
      html = decodeBodyData(part.body.data);
    }

    (part.parts || []).forEach(walk);
  })(payload);

  if (plain && plain.trim()) return htmlToText(plain.trim());
  if (html) return htmlToText(html);
  if (payload?.body?.data) return htmlToText(decodeBodyData(payload.body.data));

  return "";
}

// ============================================================================
// Google Vision OCR
// ============================================================================

async function runVisionOCR(base64Content, apiKey) {
  const url = `https://vision.googleapis.com/v1/images:annotate?key=${encodeURIComponent(
    apiKey
  )}`;

  const body = {
    requests: [
      {
        image: { content: base64Content },
        features: [{ type: "DOCUMENT_TEXT_DETECTION" }],
      },
    ],
  };

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const json = await res.json();

  if (json.error) {
    throw new Error(json.error.message);
  }

  const r0 = json.responses?.[0] || {};
  const text =
    r0.fullTextAnnotation?.text || r0.textAnnotations?.[0]?.description || "";

  return (text || "").trim();
}

// ============================================================================
// MailGuard backend (ML only)
// ============================================================================

async function sendToMailGuardServer(emailData) {
  const apiUrl = "http://127.0.0.1:8000/analyze_email/";

  try {
    console.log("Sending email to backend:", emailData);

    const res = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emailData),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Server ${res.status}: ${text}`);
    }

    return await res.json();
  } catch (err) {
    console.error("MailGuard API error:", err);
    return {
      verdict: "error",
      score: 0,
      reasons: [err.message || String(err)],
    };
  }
}

// ============================================================================
// Core: fetch emails, run OCR, call ML backend
// ============================================================================

async function fetchEmailsWithOCR() {
  // 1) Get Google auth token
  let token;
  try {
    token = await getInteractiveAuthToken();
  } catch (e) {
    console.error("Auth token error:", e);
    return { emails: [], ocrMap: {} };
  }

  // 2) List recent messages
  let list;
  try {
    list = await googleApiFetch(
      "https://www.googleapis.com/gmail/v1/users/me/messages?maxResults=10",
      token
    );
  } catch (e) {
    console.error("Failed to list messages:", e);
    return { emails: [], ocrMap: {} };
  }

  if (!list.messages) return { emails: [], ocrMap: {} };

  // 3) Check if OCR is enabled
  const storage = await readFromStorage(["visionApiKey"]);
  const visionApiKey = storage.visionApiKey || "";
  const hasVision = !!visionApiKey;

  const emails = [];
  const ocrMap = {};

  // 4) Process each message
  for (const msg of list.messages) {
    let detail;

    try {
      detail = await googleApiFetch(
        `https://www.googleapis.com/gmail/v1/users/me/messages/${msg.id}?format=full`,
        token
      );
    } catch (e) {
      console.warn("Failed to fetch message detail", msg.id, e);
      continue;
    }

    const headers = detail.payload?.headers || [];
    const subject =
      headers.find((h) => h.name === "Subject")?.value || "(No Subject)";
    const from =
      headers.find((h) => h.name === "From")?.value || "(Unknown)";
    const snippet = detail.snippet || "";
    const bodyText = pickBodyText(detail.payload);

    ocrMap[msg.id] = ocrMap[msg.id] || [];

    // 5) If available, run OCR on image attachments
    if (hasVision) {
      const imageParts = collectImageParts(detail.payload);

      for (const part of imageParts) {
        try {
          const attachment = await googleApiFetch(
            `https://www.googleapis.com/gmail/v1/users/me/messages/${msg.id}/attachments/${part.body.attachmentId}`,
            token
          );

          const b64 = base64UrlToBase64(attachment.data || "");
          let text = "";

          try {
            text = await runVisionOCR(b64, visionApiKey);
          } catch (e) {
            text = `(OCR error) ${e.message}`;
          }

          ocrMap[msg.id].push({
            filename: part.filename || `(image ${part.partId || ""})`,
            text,
          });
        } catch (e) {
          ocrMap[msg.id].push({
            filename: part.filename || `(image ${part.partId || ""})`,
            text: `(attachment fetch error) ${e.message}`,
          });
        }
      }
    }

    const ocrItems = ocrMap[msg.id] || [];
    const ocrTexts = ocrItems
      .map((x) => x.text?.trim())
      .filter(Boolean);

    let effectiveBody = bodyText || snippet;

    if (ocrTexts.length) {
      effectiveBody +=
        "\n\n[OCR extraction from attachments]\n" +
        ocrTexts.join("\n\n---\n\n");
    }

    const emailData = {
      message_id: msg.id,
      sender: from,
      subject,
      body: effectiveBody,
      attachments_text: ocrTexts,
      fetched_at: new Date().toISOString(),
      client_meta: { extension: "gmail-fetcher", version: "1.0" },
    };

    // 6) Call ML backend
    try {
      const analysis = await sendToMailGuardServer(emailData);

      const mlScore =
        typeof analysis.score === "number" ? analysis.score : null;
      const mlVerdict = analysis.verdict ?? "unknown";

      // Keep ML result alongside OCR info (useful in popup)
      ocrMap[msg.id].push({
        filename: "(MailGuard ML verdict)",
        text: [
          `Verdict: ${mlVerdict}`,
          mlScore !== null ? `ML score: ${mlScore.toFixed(3)}` : "ML score: —",
        ].join("\n"),
      });

      // Final record we store and send to popup/content script
      emails.push({
        id: msg.id,
        subject,
        from,
        snippet,
        bodyText: effectiveBody,
        fetched_at: new Date().toISOString(),
        mailguard: {
          verdict: String(mlVerdict).toLowerCase(),
          score: mlScore,
          reasons: analysis.reasons ?? [],
          ml_verdict: mlVerdict,
          ml_score: mlScore,
          cached: !!analysis.cached,
        },
      });

      console.log("MailGuard ML verdict for", subject, {
        mlVerdict,
        mlScore,
        reasons: analysis?.reasons ?? [],
      });
    } catch (e) {
      console.warn("MailGuard call failed for", msg.id, e);
      emails.push({
        id: msg.id,
        subject,
        from,
        snippet,
        bodyText: effectiveBody,
      });
    }
  }

  // 7) Notifications for new emails + persist to storage
  try {
    const { lastSeenId } = await readFromStorage(["lastSeenId"]);
    const newEmails = [];

    for (const email of emails) {
      if (email.id === lastSeenId) break;
      newEmails.push(email);
    }

    if (newEmails.length > 0) {
      newEmails.reverse().forEach((email) => {
        const preview =
          email.bodyText && email.bodyText.length > 200
            ? email.bodyText.slice(0, 200) + "..."
            : email.bodyText || "";

        chrome.notifications.create({
          type: "basic",
          iconUrl: "icon.png",
          title: email.subject,
          message: `From: ${email.from}\n\n${preview}`,
          priority: 2,
        });
      });

      await writeToStorage({ lastSeenId: emails[0].id });
    }

    await writeToStorage({ emails, ocrMap });
  } catch (e) {
    console.warn("Storage/notification error:", e);
  }

  return { emails, ocrMap };
}

// ============================================================================
// Scheduling & popup bridge
// ============================================================================

// Run every minute in background
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("fetchEmailsAlarm", { periodInMinutes: 1 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "fetchEmailsAlarm") {
    fetchEmailsWithOCR().catch(() => {});
  }
});

// Also run once when the service worker starts
fetchEmailsWithOCR().catch(() => {});

// Handle messages from popup.js
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "fetchEmails") {
    fetchEmailsWithOCR()
      .then(({ emails, ocrMap }) => sendResponse({ emails, ocrMap }))
      .catch((err) =>
        sendResponse({ error: err?.message || String(err) })
      );
    return true; // keep the message channel open for async response
  }
});

// ============================================================================
// Content-script bridge (classify a single Gmail row on demand)
// ============================================================================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== "mailguardClassify") return;

  (async () => {
    try {
      const cacheKey = `mg_cache_${msg.key}`;

      // 1) Check cache first to avoid repeated calls for same email
      const cached = await new Promise((resolve) => {
        chrome.storage.local.get(cacheKey, (result) =>
          resolve(result[cacheKey])
        );
      });

      if (cached) {
        sendResponse({ ok: true, source: "cache", ...cached });
        return;
      }

      // 2) Build minimal payload using data extracted by content script
      const payload = {
        message_id: msg.key,
        sender: msg.from || "",
        subject: msg.subject || "",
        body: msg.text || msg.subject || "",
        attachments_text: [],
        fetched_at: new Date().toISOString(),
        client_meta: { extension: "gmail-badge", version: "1.0" },
      };

      // 3) Call backend
      const analysis = await sendToMailGuardServer(payload);
      const mlScore =
        typeof analysis.score === "number" ? analysis.score : null;
      const mlVerdict = analysis.verdict ?? "unknown";

      const result = {
        verdict: mlVerdict,
        score: mlScore,
        reasons: analysis.reasons ?? [],
        ml_verdict: mlVerdict,
        ml_score: mlScore,
      };

      // 4) Cache result for this message id
      await new Promise((resolve) =>
        chrome.storage.local.set({ [cacheKey]: result }, resolve)
      );

      sendResponse({ ok: true, source: "live", ...result });
    } catch (e) {
      sendResponse({ ok: false, error: e?.message || String(e) });
    }
  })();

  return true; // async response
});
