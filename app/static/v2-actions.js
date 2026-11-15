const toMinor = (value) => Math.round(Number(value) * 100);
const purposeField = (purpose = "personal") =>
  selectField(
    "Purpose",
    "purpose",
    [
      ["personal", "Personal"],
      ["business", "Business"],
    ],
    purpose,
  );
const amountField = (label = "Amount", name = "amount", value = "") =>
  field(label, name, value, "number", "min=0.01 step=0.01 required");

function billDialog() {
  const purpose = S.dashboard?.workspace ?? S.profile.override ?? S.profile.configuration;
  const due = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Kolkata" });
  modal(
    `<h2>${esc(t("Add bill"))}</h2><form id="bill-form"><div class="bill-import"><label for="bill-source">${esc(t("Paste invoice text or a UPI QR payload"))}</label><textarea id="bill-source" rows="3" maxlength="4000" placeholder="Supplier: Bharat Wholesale&#10;Amount due: ₹2,450.00&#10;Due date: 20/11/2026"></textarea><p id="bill-import-status" class="field-hint" role="status">${esc(t("Tara fills in the details it finds. Review them before saving."))}</p></div>${field("Title", "title", "", "text", "required maxlength=100")}${amountField()}${field("Due date", "due", due, "date", "required")}${purposeField(purpose === "business" ? "business" : "personal")}${check("Repeat every 30 days", "recurring")}${formFooter("Save bill")}</form>`,
  );
  $("#bill-form").elements.due.dataset.autofill = due;
}

function readBillText(text) {
  const value = text.trim();
  if (/^upi:\/\/pay\?/i.test(value)) {
    const params = new URLSearchParams(value.slice(value.indexOf("?") + 1));
    if (params.get("cu") && params.get("cu") !== "INR") return {};
    const amount = params.get("am");
    return {
      title: params.get("pn") || params.get("pa"),
      amount: amount && /^\d{1,9}(?:\.\d{1,2})?$/.test(amount) ? Number(amount) : null,
    };
  }
  const title = value.match(/^(?:biller|supplier|merchant|vendor|payee|title)\s*:\s*([^\r\n]+)/im)?.[1];
  const amount = value.match(/^(?:amount due|total due|balance due|grand total|total|amount)\s*[:=]?\s*(?:₹|INR\s*|Rs\.?\s*)?\s*([\d,]+(?:\.\d{1,2})?)(?:\s|$)/im)?.[1];
  const rawDue = value.match(/^(?:due date|payment due|due on)\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[\/-]\d{1,2}[\/-]\d{4})\b/im)?.[1];
  let due = rawDue;
  if (rawDue && !/^\d{4}-/.test(rawDue)) {
    const [day, month, year] = rawDue.split(/[\/-]/);
    due = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  }
  const date = due && new Date(`${due}T00:00:00Z`);
  return {
    title,
    amount: amount ? Number(amount.replaceAll(",", "")) : null,
    due: date && !isNaN(date) && date.toISOString().slice(0, 10) === due ? due : null,
  };
}

function autofillBill(source) {
  const parsed = readBillText(source.value);
  let found = false;
  for (const [name, value] of Object.entries(parsed)) {
    if (!value) continue;
    found = true;
    const input = source.form.elements[name];
    if (input.value && input.value !== input.dataset.autofill) continue;
    input.value = String(value).trim().slice(0, 100);
    input.dataset.autofill = input.value;
  }
  $("#bill-import-status").textContent = t(found
    ? "Review the detected details before saving."
    : "Tara fills in the details it finds. Review them before saving.");
}

document.addEventListener("input", ({ target }) => {
  if (target.id === "bill-source") autofillBill(target);
});

function collectPreferences(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const name of ["context_consent", "voice_enabled", "learning_enabled"])
    data[name] = form.elements[name]?.checked || false;
  data.features = ["budget", "purchases", "goals", "emi", "business"].filter(
    (key) => form.elements[`feature-${key}`]?.checked,
  );
  for (const name of ["work_start", "work_end"])
    if (data[name] !== undefined) data[name] = Number(data[name]);
  for (const key of Object.keys(data))
    if (key.startsWith("feature-")) delete data[key];
  return { ...S.profile, ...data };
}

function planDialog(kind) {
  S.planKind = kind;
  const fields =
    kind === "goal"
      ? `${amountField("Target", "target")}${field("Saved", "saved", 0, "number", "min=0 step=0.01 required")}${field("Monthly contribution", "contribution", 0, "number", "min=0 step=0.01")}${selectField(
          "Horizon",
          "horizon",
          [
            ["short", "Short term"],
            ["medium", "Medium term"],
            ["long", "Long term"],
          ],
          "medium",
        )}${field("Target date", "target_date", "", "date")}`
      : kind === "emi"
        ? `${amountField("Financed principal", "principal")}${field("Annual interest rate (%)", "annual_rate", 0, "number", "min=0 max=60 step=0.01 required")}${field("Months", "months", 12, "number", "min=1 max=120 required")}<div id="emi-estimate"></div>${button("Compare total cost", "emi-compare", "", "white")}`
        : amountField("Allocated");
  modal(
    `<h2>${esc(t(kind === "allocation" ? "Add reserve" : "Add plan"))}</h2><form id="plan-form">${field("Title", "title", "", "text", "required maxlength=100")}${purposeField(S.dashboard?.workspace === "business" ? "business" : "personal")}<div class="form-grid">${fields}</div><div class="spacer"></div>${formFooter("Save plan")}</form>`,
  );
}
function planPayload(form) {
  const data = Object.fromEntries(new FormData(form));
  const payload = {
    kind: S.planKind,
    title: data.title || t("EMI Commitments"),
    purpose: data.purpose,
  };
  if (S.planKind === "goal")
    Object.assign(payload, {
      target_minor: toMinor(data.target),
      saved_minor: toMinor(data.saved),
      contribution_minor: toMinor(data.contribution),
      horizon: data.horizon,
      target_date: data.target_date,
    });
  if (S.planKind === "emi")
    Object.assign(payload, {
      principal_minor: toMinor(data.principal),
      annual_rate: data.annual_rate,
      months: Number(data.months),
    });
  if (S.planKind === "allocation") payload.amount_minor = toMinor(data.amount);
  return payload;
}

async function submitAuthorization(payload) {
  const result = await api(`/invoices/${S.invoice.id}/authorize`, payload);
  if (result.gateway === "step_up") {
    S.authorization = payload;
    modal(
      `<h2>${esc(t("Confirm this payment"))}</h2><p>${esc(t("Extra confirmation is required for this demo payment."))}</p><div class="notice">${esc(t("Demo confirmation code"))}: <strong>${esc(result.step_up_code_demo)}</strong></div><form id="stepup-form">${field("Confirmation code", "code", "", "text", "required autocomplete=off inputmode=numeric")}${formFooter("Confirm payment")}</form>`,
    );
    return;
  }
  if (!result.ok) {
    closeModal();
    toast(
      t(
        result.pending
          ? "Verification pending. Check the original payment before retrying."
          : result.reason || result.gateway || "Payment was not completed",
      ),
    );
    await render();
    return;
  }
  closeModal();
  toast(t("Payment confirmed"));
  await render();
}

async function submitRefund(payload) {
  const result = await api(`/purchases/${S.item.id}/refund`, payload);
  if (result.gateway === "step_up") {
    S.refund = payload;
    modal(
      `<h2>${esc(t("Confirm refund"))}</h2><div class="notice">${esc(t("Demo confirmation code"))}: <strong>${esc(result.step_up_code_demo)}</strong></div><form id="refund-stepup-form">${field("Confirmation code", "code", "", "text", "required autocomplete=off")}${formFooter("Confirm refund")}</form>`,
    );
    return;
  }
  if (!result.ok) throw new Error(result.gateway || "Refund was not completed");
  closeModal();
  toast(t("Refund confirmed"));
  await render();
}

async function askQuestion(message) {
  const input = $("#ask-form input");
  if (input) input.value = "";
  const placeholder = document.createElement("div");
  placeholder.className = "message user";
  placeholder.textContent = message;
  $("#messages").append(placeholder);
  const waiting = document.createElement("div");
  waiting.className = "message assistant";
  waiting.textContent = t("Checking your records…");
  $("#messages").append(waiting);
  waiting.scrollIntoView({ block: "nearest" });
  try {
    const result = await api("/ask", { message });
    placeholder.remove();
    waiting.remove();
    $("#messages").insertAdjacentHTML(
      "beforeend",
      messageHtml({ ...result, question: message }),
    );
    $("#messages").lastElementChild.scrollIntoView({ block: "nearest" });
  } catch (error) {
    waiting.textContent = error.message;
    throw error;
  }
}

async function useCamera() {
  if (!("BarcodeDetector" in window)) {
    toast(
      t(
        "Camera QR detection is unavailable in this browser. Paste the QR text instead.",
      ),
    );
    return;
  }
  S.stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment" },
  });
  const video = $("#scan-video");
  video.classList.remove("hide");
  video.srcObject = S.stream;
  await video.play();
  const detector = new BarcodeDetector({ formats: ["qr_code"] });
  async function scanFrame() {
    if (!S.stream) return;
    try {
      const codes = await detector.detect(video);
      if (codes.length) {
        $("#token").value = codes[0].rawValue;
        stopCamera();
        video.classList.add("hide");
        $("#scan-form").requestSubmit();
        return;
      }
    } catch {
      stopCamera();
      toast(t("Unable to read the camera. Paste the QR text instead."));
      return;
    }
    setTimeout(scanFrame, 400);
  }
  scanFrame();
}

async function action(name, id) {
  if (name === "watch-shared-cart" || name === "checkout-shared-cart") {
    if (!S.sharedCartToken)
      throw new Error(t("Share a fresh cart from BrightMart"));
    if (name === "watch-shared-cart") {
      await api("/store-cart/track", { token: S.sharedCartToken });
      toast(t("Items added to your watchlist"));
      return navigate("purchases/before");
    }
    const row = await api("/store-cart/checkout", { token: S.sharedCartToken });
    return navigate(`invoice/${row.id}`);
  }
  if (name === "watch-refresh") {
    const row = await api(`/watch/${id}/refresh`, {});
    toast(row.error || t("Showing the latest recorded price"));
    return render();
  }
  if (name === "watch-stop") {
    await api(`/watch/${id}`, undefined, "DELETE");
    return navigate("purchases/before");
  }
  if (name === "provider-check") {
    const result = await api(`/invoices/${id}/provider-status`, {});
    toast(
      t(result.ok ? "Payment confirmed" : "Awaiting verified provider capture"),
    );
    return render();
  }
  if (name === "business-dialog") {
    return modal(
      `<h2>${esc(t("Add business record"))}</h2><form id="business-form">${selectField("Type", "kind", businessKinds, "customer")}${field("Title", "title", "", "text", "required maxlength=100")}${field("Contact", "contact")}${field("Amount", "amount", "", "number", "min=0 step=0.01")}${field("Expected amount", "expected", "", "number", "min=0 step=0.01")}${field("Due date", "due", "", "date")}${field("Notes", "notes")}${formFooter("Save record")}</form>`,
    );
  }
  if (name === "business-pay") {
    return modal(
      `<h2>${esc(t("Record payment"))}</h2><p>${esc(t("This records a payment you made elsewhere. It does not initiate a bank transfer."))}</p><div class="actions">${button("Confirm payment record", "business-pay-confirm", id, "green")}${button("Cancel", "close", "", "white")}</div>`,
    );
  }
  if (name === "business-pay-confirm") {
    await api(`/business/${id}/settle`, { confirmed: true });
    closeModal();
    return render();
  }
  if (name === "close") return closeModal();
  if (name === "reload") return render();
  if (name === "persona") {
    S.persona = id;
    return welcome();
  }
  if (name === "language") {
    S.profile.language = id;
    return onboarding();
  }
  if (name === "configuration") {
    S.profile.configuration = id;
    return onboarding();
  }
  if (name === "onboard-back") {
    S.step--;
    return onboarding();
  }
  if (name === "start") {
    const session = await api("/session", { persona: S.persona });
    S.csrf = session.csrf;
    S.profile = await api("/profile");
    return render();
  }
  if (name === "copy-qr") {
    await navigator.clipboard.writeText(S.invoice.qr_token);
    return toast(t("Copied"));
  }
  if (name === "cancel-invoice") {
    await api(`/invoices/${id}/cancel`, {});
    return render();
  }
  if (name === "regenerate") {
    const row = S.invoice;
    const data = await api("/invoices", {
      previous_id: row.id,
      kind: row.kind,
      items:
        row.kind === "payment"
          ? []
          : row.items.map((i) => ({
              product_id: i.product_id,
              quantity: i.quantity,
            })),
      amount_minor: row.total_minor,
      description: row.items[0].name,
      purpose: row.purpose,
    });
    return navigate(`invoice/${data.id}`);
  }
  if (name === "alternative") {
    const row = await api("/invoices", {
      items: [{ product_id: "headphones", quantity: 1 }],
      previous_id: S.invoice.id,
      purpose: S.invoice.purpose,
    });
    return navigate(`invoice/${row.id}`);
  }
  if (name === "reconcile") {
    const result = await api(`/invoices/${id}/reconcile`, {});
    toast(
      t(
        result.ok
          ? "Payment confirmed"
          : "Verification pending. Check the original payment before retrying.",
      ),
    );
    return render();
  }
  if (name === "camera") return useCamera();
  if (name === "delivery-dialog")
    return modal(
      `<h2>${esc(t("Simulate delivery"))}</h2>${noticeDemo()}<form id="delivery-form">${field("Delivered quantity", "quantity", S.item.quantity, "number", `min=1 max=${S.item.quantity} required`)}${field("Days since delivery", "days_ago", 2, "number", "min=0 max=30 required")}${formFooter("Confirm delivery")}</form>`,
    );
  if (name === "item-action") {
    if (["replacement", "return", "warranty"].includes(id)) {
      S.itemAction = id;
      return modal(
        `<h2>${esc(t("Review request"))}</h2><form id="item-request-form"><label for="issue">${esc(t("Describe the issue"))}</label><textarea id="issue" name="issue" required maxlength="1000"></textarea><div class="spacer"></div>${formFooter("Send request")}</form>`,
      );
    }
    await api(`/purchases/${S.item.id}/action`, { action: id });
    toast(t("Updated"));
    return render();
  }
  if (name === "refund-dialog")
    return modal(
      `<h2>${esc(t("Refund items"))}</h2>${noticeDemo()}<p>${esc(t("Approve a refund as the demo seller."))}</p><form id="refund-form">${field("Quantity", "quantity", 1, "number", `min=1 max=${S.item.quantity - S.item.refunded_quantity} required`)}${check("I approve this demo refund.", "confirmed")}${formFooter("Confirm refund")}</form>`,
    );
  if (name === "investigate") {
    const result = await api(`/briefcases/${id}/investigate`, {});
    return modal(
      `<h2>${esc(t("Payment verification"))}</h2><p>${esc(result.summary || result.explanation || result.finding || "")}</p>${Object.entries(
        result,
      )
        .filter(
          ([key, value]) =>
            typeof value === "string" &&
            !["summary", "explanation", "finding"].includes(key),
        )
        .map(([key, value]) => kv(key.replaceAll("_", " "), esc(value)))
        .join("")}${formFooter("Close")}`.replace(
        '<button type="submit" class="btn green">' +
          esc(t("Close")) +
          "</button>",
        button("Close", "close", "", "green"),
      ),
    );
  }
  if (name === "connect") {
    const result = await api(`/briefcases/${id}/connect`, {});
    modal(
      `<h2>${esc(t("Connected with demo seller"))}</h2><p>${esc(t("The agents exchanged a permission-scoped case summary. Review the shared timeline and evidence in your briefcase."))}</p><div class="notice">${esc(result.status || result.state || "completed")}</div><div class="actions">${link("Complete briefcase", `activity/briefcase/${id}`, "green")}${button("Close", "close", "", "white")}</div>`,
    );
    return;
  }
  if (name === "bill-dialog") return billDialog();
  if (name === "bill-pay")
    return modal(
      `<h2>${esc(t("Record payment"))}</h2><p>${esc(t("This records a payment you made elsewhere. It does not initiate a bank transfer."))}</p><div class="actions">${button("Confirm payment record", "bill-pay-confirm", id, "green")}${button("Cancel", "close", "", "white")}</div>`,
    );
  if (name === "bill-pay-confirm") {
    await api(`/bills/${id}/record-payment`, { confirmed: true });
    closeModal();
    return render();
  }
  if (name === "plan-dialog") return planDialog(id);
  if (name === "emi-compare") {
    const result = await api("/emi/compare", planPayload($("#plan-form")));
    $("#emi-estimate").innerHTML =
      `<div class="notice">${kv("Monthly installment", money(result.installment_minor))}${kv("Total repayment", money(result.total_minor))}${kv("Total interest", money(result.interest_minor))}</div>`;
    return;
  }
  if (name === "savings-dialog") {
    const plan = S.plans.find((p) => p.id === id);
    S.planId = id;
    return modal(
      `<h2>${esc(plan.title)}</h2><form id="savings-form">${field("Saved", "saved", plan.data.saved_minor / 100, "number", `min=0 max=${plan.data.target_minor / 100} step=0.01 required`)}${formFooter("Save")}</form>`,
    );
  }
  if (name === "ledger-dialog")
    return modal(
      `<h2>${esc(t("Add record"))}</h2><form id="ledger-form">${field("Title", "title", "", "text", "required maxlength=100")}${selectField(
        "Type",
        "direction",
        [
          ["income", "Income"],
          ["expense", "Expense"],
        ],
        "expense",
      )}${amountField()}${purposeField()}${field("Category", "category", "general", "text", "required maxlength=40")}${formFooter("Save record")}</form>`,
    );
  if (name === "notice-dialog")
    return modal(
      `<h2>${esc(t("Draft notice"))}</h2><form id="notice-form">${selectField(
        "From",
        "direction",
        [
          ["buyer", "Buyer"],
          ["seller", "Demo seller"],
        ],
        id === "seller" ? "seller" : "buyer",
      )}${field("Subject", "subject", "", "text", "required maxlength=150")}<label for="notice-message">${esc(t("Message"))}</label><textarea id="notice-message" name="message" required maxlength="3000"></textarea><div class="spacer"></div>${formFooter("Save draft")}</form>`,
    );
  if (name === "notice-review") {
    const row = S.notices.find((n) => n.id === id);
    return modal(
      `<h2>${esc(row.subject)}</h2><p style="white-space:pre-wrap">${esc(row.message)}</p><div class="notice">${esc(t("In-app only. No email, SMS or WhatsApp will be sent."))}</div><div class="actions">${button("Approve and send", "notice-send", id, "green")}${button("Cancel", "close", "", "white")}</div>`,
    );
  }
  if (name === "notice-send") {
    await api(`/notices/${id}/send`, { confirmed: true });
    closeModal();
    navigate("notices/sent");
    return;
  }
  if (name === "prompt") return askQuestion(id);
  if (name === "speak") {
    if (!window.speechSynthesis)
      return toast(t("Speech is unavailable in this browser."));
    const utterance = new SpeechSynthesisUtterance(id);
    utterance.lang = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" }[
      S.profile.language
    ];
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
    return;
  }
  if (name === "voice") {
    const Recognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition)
      return toast(
        t(
          "Voice input is unavailable in this browser. Please type your question.",
        ),
      );
    const recognition = new Recognition();
    recognition.lang = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" }[
      S.profile.language
    ];
    recognition.onresult = (event) => {
      $("#ask-form input").value = event.results[0][0].transcript;
    };
    recognition.onerror = () =>
      toast(t("Voice input could not start. Please type your question."));
    recognition.start();
    return toast(t("Listening… Review the text before sending."));
  }
  if (name === "reset-review")
    return modal(
      `<h2>${esc(t("Reset my demo"))}</h2><p>${esc(t("Start a fresh private workspace. Other visitors are unaffected."))}</p><div class="actions">${button("Reset my demo", "reset-confirm", "", "green")}${button("Cancel", "close", "", "white")}</div>`,
    );
  if (name === "reset-confirm") {
    await api("/reset", { confirmed: true });
    closeModal();
    S.csrf = "";
    S.profile = { language: "en" };
    S.step = 0;
    location.hash = "";
    return welcome();
  }
}

async function submit(form) {
  const data = Object.fromEntries(new FormData(form));
  if (form.id === "watch-product-form") {
    const row = await api("/watch", { url: data.product_url });
    toast(t("Price tracking started"));
    return navigate(`watch/${row.id}`);
  }
  if (form.id === "business-form") {
    await api("/business", {
      kind: data.kind,
      title: data.title,
      contact: data.contact,
      amount_minor: toMinor(data.amount),
      expected_minor: toMinor(data.expected),
      due: data.due,
      notes: data.notes,
    });
  }
  if (form.id === "onboarding-form") {
    if (S.step === 1) Object.assign(S.profile, data);
    if (S.step === 2 && data.business_type !== undefined)
      S.profile.business_type = data.business_type;
    if (S.step < 3) {
      S.step++;
      return onboarding();
    }
    S.profile = await api("/profile", collectPreferences(form), "PUT");
    return render();
  }
  if (form.id === "preferences-form") {
    S.profile = await api("/profile", collectPreferences(form), "PUT");
    toast(t("Preferences saved"));
    return render();
  }
  if (form.id === "authorize-form") {
    const payload = {
      authorized: !!data.authorized,
      simulate_interruption: !!data.simulate_interruption,
      fingerprint: S.invoice.fingerprint,
      version: S.invoice.version,
    };
    if (data.method && !usesDemoPayment(S.invoice, data.method))
      return openProviderCheckout(S.invoice, payload, data.method);
    return submitAuthorization({ ...payload, simulated_method: data.method || "mock" });
  }
  if (form.id === "stepup-form")
    return submitAuthorization({ ...S.authorization, step_up_code: data.code });
  if (form.id === "refund-stepup-form")
    return submitRefund({ ...S.refund, step_up_code: data.code });
  if (form.id === "qr-form") {
    if (data.kind === "itemized") return window.location.assign("/store");
    const row = await api("/invoices", {
      kind: "payment",
      amount_minor: toMinor(data.amount),
      description: data.description,
      purpose: data.purpose,
    });
    return navigate(`invoice/${row.id}`);
  }
  if (form.id === "scan-form") {
    const result = await api("/scan", { token: data.token.trim() });
    if (result.invoice) return navigate(`invoice/${result.invoice.id}`);
    $("#scan-result").innerHTML =
      `<div class="notice warn"><h3>${esc(t(result.upi_uri ? "Review external UPI request" : "External QR — review only"))}</h3><p>${esc(result.details?.summary || result.message || result.reason || "")}</p>${Object.entries(
        result.details || {},
      )
        .filter(
          ([key, value]) =>
            (typeof value === "string" || typeof value === "number") &&
            !["summary", "url"].includes(key),
        )
        .map(([key, value]) => kv(key.replaceAll("_", " "), esc(value)))
        .join(
          "",
        )}${result.upi_uri ? `<p>${esc(t("Verify the recipient and amount in your UPI app. ContextIQ cannot independently confirm this external payment."))}</p><a class="btn green" href="${esc(result.upi_uri)}">${esc(t("Open UPI app"))}</a>` : ""}</div>`;
    return;
  }
  if (form.id === "delivery-form")
    await api(`/purchases/${S.item.id}/action`, {
      action: "deliver",
      quantity: Number(data.quantity),
      days_ago: Number(data.days_ago),
    });
  if (form.id === "item-request-form")
    await api(`/purchases/${S.item.id}/action`, {
      action: S.itemAction,
      issue: data.issue,
    });
  if (form.id === "refund-form")
    return submitRefund({
      quantity: Number(data.quantity),
      confirmed: !!data.confirmed,
      request_id: crypto.randomUUID(),
    });
  if (form.id === "bill-form")
    await api("/bills", {
      title: data.title,
      amount_minor: toMinor(data.amount),
      due: data.due,
      purpose: data.purpose,
      recurring: !!data.recurring,
    });
  if (form.id === "plan-form") await api("/plans", planPayload(form));
  if (form.id === "savings-form")
    await api(
      `/plans/${S.planId}/savings`,
      { saved_minor: toMinor(data.saved) },
      "PUT",
    );
  if (form.id === "ledger-form")
    await api("/history", {
      title: data.title,
      amount_minor: toMinor(data.amount),
      direction: data.direction,
      purpose: data.purpose,
      category: data.category,
      request_id: crypto.randomUUID(),
    });
  if (form.id === "notice-form") {
    await api("/notices", data);
    closeModal();
    return navigate("notices/drafts");
  }
  if (form.id === "ask-form") return askQuestion(data.message);
  closeModal();
  toast(t("Saved"));
  return render();
}

async function guarded(task, control) {
  if (S.busy) return;
  S.busy = true;
  if (control) control.disabled = true;
  try {
    await task();
  } catch (error) {
    toast(error.message);
  } finally {
    S.busy = false;
    if (control) control.disabled = false;
  }
}
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-checklist-toggle]"))
    return toggleDailyChecklist();
  const control = event.target.closest("[data-action]");
  if (control) {
    event.preventDefault();
    guarded(() => action(control.dataset.action, control.dataset.id), control);
  }
  const read = event.target.closest("[data-read]");
  if (read)
    api(
      `/notifications/${encodeURIComponent(read.dataset.read)}/read`,
      {},
    ).catch(() => {});
  if (event.target.closest("dialog a[href]")) closeModal();
});
document.addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(() => submit(event.target), event.submitter);
});
document.addEventListener("input", (event) => {
  if (event.target.id === "history-search")
    for (const row of document.querySelectorAll("[data-search]"))
      row.hidden = !row.dataset.search.includes(
        event.target.value.toLowerCase(),
      );
});
document.addEventListener("change", (event) => {
  const task = event.target.closest("[data-daily-task]");
  if (task) {
    const completed = task.checked;
    if (S.busy) {
      task.checked = !completed;
      return;
    }
    return guarded(async () => {
      try {
        await api(
          "/daily-tasks",
          { id: task.dataset.dailyTask, completed },
          "PUT",
        );
      } catch (error) {
        task.checked = !completed;
        throw error;
      }
      await guide.refreshHomeFocus(true);
    });
  }
  if (event.target.name === "method" && event.target.form?.id === "authorize-form") {
    setCheckoutMethod(S.invoice, event.target.value);
  }
  if (event.target.id === "workspace-select")
    guarded(async () => {
      S.profile = await api(
        "/profile",
        { ...S.profile, override: event.target.value },
        "PUT",
      );
      await render();
    });
});
window.addEventListener("hashchange", render);
window.addEventListener("online", () => {
  offlineBanner();
  if (S.csrf) render();
});
window.addEventListener("offline", offlineBanner);
window.addEventListener("pagehide", stopCamera);
window.addEventListener("resize", () => {
  if ($("#balance-chart"))
    drawChart("balance-chart", S.dashboard.finance.chart);
  if ($("#forecast-chart")) drawChart("forecast-chart", S.forecast.points);
});
async function boot() {
  try {
    const session = await api("/session");
    S.csrf = session.csrf;
    S.profile = await api("/profile");
  } catch (error) {
    if (error.status !== 401) toast(error.message);
  }
  await render();
}
boot();
