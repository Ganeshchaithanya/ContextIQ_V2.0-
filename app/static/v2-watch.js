"use strict";

function priceMoney(minor, currency) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(
    minor / 100,
  );
}

async function applyStoreHandoff(route, hash, renderId) {
  const [page, section] = route;
  const intent = page === "watch" ? "track" :
    page === "budget" && section === "goals" ? "plan" :
    page === "purchases" && section === "during" ? "checkout" : null;
  const token = new URLSearchParams(hash.split("?")[1]).get("cart");
  if (!intent || !token) return false;
  const result = await api(`/store-cart/${intent}`, { token });
  if (renderId !== S.renderId || hash !== location.hash) return true;
  const destination = intent === "track" ? "purchases/before" :
    intent === "plan" ? "budget/goals" : `invoice/${result.id}`;
  if (intent === "track") toast(t("Items added to your watchlist"));
  if (intent === "plan") toast(t("Cart items linked to your savings plans"));
  // Replace the signed handoff URL so refreshing or using Back does not repeat it.
  history.replaceState(null, "", `#/${destination}`);
  await render();
  return true;
}

async function watchPage() {
  const registrations = await api("/watch");
  const selected = S.route[0] === "watch" ? S.route[1] : null;
  const rows = registrations.filter((row) => !selected || row.id === selected);
  return `${back(selected ? "purchases/before" : "purchases")}${head("Cart Intelligence", "Before payment · track items you are interested in", '<a class="btn white" href="/store">Open BrightMart ↗</a>')}<section class="panel"><h2>${esc(t("Watch a product"))}</h2><p class="field-hint">Enter a clean public product URL. Supported pages publish one in-stock price. Active demo workspaces check roughly every four hours while the server is awake; blocked pages show an error, not an invented price.</p><form id="watch-product-form" style="margin-top:16px">${field("Product page URL", "product_url", "", "url", 'required maxlength="2000" placeholder="https://store.example/product"')}<button type="submit" class="btn green">${esc(t("Track price"))}</button></form><details style="margin-top:18px"><summary>See how a price drop changes a savings plan</summary><p class="field-hint">Labelled simulation: a shop printer falls from ₹12,000 to ₹9,900. Its one-year savings target updates, a priority notice appears and Tara can explain the evidence. This does not change store prices or recorded cash.</p>${button("Run price-drop demo", "watch-demo", "", "small white")}</details></section>${rows.length ? `<div class="grid two">${rows.map(watchCard).join("")}</div>` : `<section class="panel"><p class="muted">${esc(t(selected ? "This tracked item is no longer available." : "No tracked items yet. Share your BrightMart cart or add a public product link."))}</p></section>`}`;
}

function watchCard(row) {
  const effect = row.price_effect || {};
  const prices = [...row.history].reverse().map(x => x.amount_minor);
  const min = Math.min(...prices), max = Math.max(...prices);
  const points = prices.map((v, i) => `${12 + i * 276 / Math.max(1, prices.length - 1)},${74 - (v - min) * 58 / Math.max(1, max - min)}`).join(" ");
  const monthly = effect.monthly_request;
  const pace = monthly ? `<p class="field-hint">Planned monthly saving: <s>${esc(priceMoney(monthly.before_minor, row.currency))}</s> → <strong>${esc(priceMoney(monthly.after_minor, row.currency))}</strong>. Actual allocation remains capped by available funds and your overrides.</p>` : "";
  const impact = effect.drop_minor > 0 ? `<div class="price-impact"><strong>↓ ${esc(priceMoney(effect.drop_minor, row.currency))} · ${effect.drop_percent}% below first observed price</strong><p>${esc(priceMoney(effect.quantity_saving_minor, row.currency))} less needed for ${row.quantity} item${row.quantity === 1 ? "" : "s"}.${effect.plan_updated ? " Your linked savings target has updated automatically." : " Plan a purchase to connect this price to savings."}</p><small>Planning only. Your cash has not moved; buying still needs your approval.</small></div>` : `<p class="field-hint">${effect.drop_minor < 0 ? "Price is above the first observed quote. Your active linked plan uses the latest price." : "Tracking started. A new observed low will create a priority notice."}</p>`;
  const purchase = row.purchase_plan_id
    ? link("View savings plan", `budget/goals/${row.purchase_plan_id}`, "small green")
    : row.currency === "INR" ? button("Plan to buy", "purchase-plan-dialog", row.id, "small green") : "";
  return `<section class="panel">${effect.simulated ? '<span class="status">Simulated price scenario</span>' : ''}<h2>${esc(row.title)}</h2><p class="field-hint">${esc(row.merchant)} · ${esc(t("Quantity"))} ${row.quantity}</p>${kv("Last observed price", priceMoney(row.current_minor, row.currency))}${kv("Lowest since tracking began", priceMoney(row.low_minor, row.currency))}${impact}${pace}<svg viewBox="0 0 300 90" class="price-sparkline" role="img" aria-label="Observed price history; exact prices available below"><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="3"/>${prices.map((v,i) => `<circle cx="${12+i*276/Math.max(1,prices.length-1)}" cy="${74-(v-min)*58/Math.max(1,max-min)}" r="4" fill="currentColor"/>`).join('')}</svg><p class="field-hint">${esc(effect.scope || "Lowest since tracking began, not an all-time market low.")}<br>${esc(t("Last checked"))} ${esc(new Date(row.checked_at).toLocaleString())}</p>${row.error ? `<div class="notice warn">${esc(row.error)}</div>` : ""}<details style="margin:14px 0"><summary>${esc(t("Price history"))}</summary>${row.history.map((sample) => kv(new Date(sample.at).toLocaleString(), priceMoney(sample.amount_minor, row.currency))).join("")}</details><div class="actions">${purchase}${effect.simulated ? '' : `<a class="btn white small" href="${esc(row.source_url)}" rel="noopener noreferrer" target="_blank">${esc(t("Open product page"))} ↗</a>${button("Check price", "watch-refresh", row.id, "small white")}`}${link("Ask Tara", "ask", "small white")}${button("Stop tracking", "watch-stop", row.id, "small ghost")}</div></section>`;
}

const paymentPresentation = {
  upi: ['<img src="/static/upi.svg" alt="" width="48" height="17">', "UPI app or QR"],
  card: ["💳", "Credit and debit cards"],
  netbanking: ["🏦", "Pay through your bank"],
  mock: ["₹", "Simulated payment"],
};

function usesDemoPayment(row, method) {
  return method === "mock" || Boolean(row.checkout.simulated_method) || !row.checkout.gateway_available;
}

function checkoutButtonText(row, method) {
  return `${t(usesDemoPayment(row, method) ? "Confirm demo payment" : "Continue to payment")} · ${money(row.total_minor)}`;
}

function setCheckoutMethod(row, method) {
  const demo = usesDemoPayment(row, method);
  $("#mock-payment-options").hidden = !demo;
  $("#checkout-mode").textContent = t(demo
    ? "Demo checkout · no money will move."
    : "Secure Razorpay test checkout");
  $("#continue-payment").textContent = checkoutButtonText(row, method);
  $("#payment-method-details").innerHTML = paymentMethodDetails(row, method);
}

function paymentMethodDetails(row, method) {
  if (!usesDemoPayment(row, method))
    return '<div class="payment-detail"><strong>Complete payment with the test gateway</strong><p>Razorpay opens after you approve this invoice. Enter payment details in its checkout window.</p></div>';
  const instruments = row.checkout.demo_instruments?.[method] || {};
  const selected = row.checkout.simulated_instrument || Object.keys(instruments)[0];
  const choices = Object.entries(instruments).map(([value, label]) =>
    `<label class="demo-instrument"><input type="radio" name="simulated_instrument" value="${esc(value)}" ${value === selected ? "checked" : ""} ${row.checkout.simulated_instrument && value !== selected ? "disabled" : ""}><span>${esc(label)}</span></label>`).join("");
  const description = {
    upi: ["Choose a demo UPI flow", "Select an app or QR flow for this walkthrough. Your selection is saved with the demo payment."],
    card: ["Demo card", "Use the sample card ending 4242 for this walkthrough."],
    netbanking: ["Demo bank transfer", "Use Demo Business Bank for this walkthrough."],
    mock: ["Simulated payment", "Review the exact total and recipient, then approve the demo payment."],
  }[method];
  return `<section class="payment-detail"><strong>${description[0]}</strong><p>${description[1]}</p><div class="demo-instruments">${choices}</div></section>`;
}

function checkoutForm(row) {
  const { methods, existing_method, simulated_method, gateway_available } = row.checkout;
  const locked = existing_method || simulated_method;
  const choices = { ...methods };
  if (gateway_available || locked === "mock") choices.mock = "Mock payment";
  const selected = locked || (gateway_available ? "mock" : "upi");
  const demo = usesDemoPayment(row, selected);
  const methodsHtml = Object.entries(choices).filter(([key]) => !locked || locked === key).map(([key, label]) => {
    const [icon, hint] = paymentPresentation[key];
    return `<label class="payment-method"><input type="radio" name="method" value="${key}" ${key === selected ? "checked" : ""}><span class="payment-icon" aria-hidden="true">${icon}</span><span><strong>${esc(t(label))}</strong><small>${esc(t(hint))}</small></span></label>`;
  }).join("");
  return `<form id="authorize-form"><div class="checkout-summary"><span class="checkout-merchant-mark" aria-hidden="true">B</span><div><p>Paying BrightMart Electronics</p><strong>${money(row.total_minor)}</strong></div><span class="status">${esc(t(demo ? "Demo checkout" : "Test gateway"))}</span></div><fieldset class="payment-methods"><legend>${esc(t("Payment method"))}</legend>${methodsHtml}</fieldset><div id="payment-method-details">${paymentMethodDetails(row, selected)}</div><p id="checkout-mode" class="field-hint">${esc(t(demo ? "Demo checkout · no money will move." : "Secure Razorpay test checkout"))}</p>${check("I authorize this exact amount, recipient and invoice.", "authorized")}<details id="mock-payment-options" ${demo ? "" : "hidden"}><summary class="field-hint">${esc(t("Demo settings"))}</summary>${check("Demo response interruption", "simulate_interruption")}</details><div class="actions"><button id="continue-payment" class="btn green" type="submit">${esc(checkoutButtonText(row, selected))}</button>${row.can_decline ? button("Decline purchase", "cancel-invoice", row.id, "white") : ""}${existing_method ? button("Check provider status", "provider-check", row.id, "white") : row.case_id ? button("Check original payment", "reconcile", row.id, "white") : ""}</div><p class="checkout-footnote">Your approval is tied to this invoice, recipient and amount. <a href="#/knowledge/receiving-upi">UPI safety guide ↗</a></p></form>`;
}

let razorpaySource;
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  if (!razorpaySource) {
    razorpaySource = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = resolve;
      script.onerror = () => {
        script.remove();
        razorpaySource = null;
        reject(new Error("Razorpay checkout could not load."));
      };
      document.head.append(script);
    });
  }
  return razorpaySource;
}

async function openProviderCheckout(invoice, payload, method) {
  if (!payload.authorized)
    throw new Error(t("Review and authorize the exact invoice first"));
  await loadRazorpay();
  const order = await api(`/invoices/${invoice.id}/provider-order`, {
    ...payload,
    method,
  });
  const checkout = new window.Razorpay({
    key: order.key,
    amount: order.amount,
    currency: order.currency,
    order_id: order.order_id,
    name: "BrightMart Electronics",
    description: "ContextIQ · Razorpay test checkout",
    config: {
      display: {
        blocks: {
          chosen: {
            name: order.method,
            instruments: [{ method: order.method }],
          },
        },
        sequence: ["block.chosen"],
        preferences: { show_default_blocks: false },
      },
    },
    handler: async (proof) => {
      try {
        const result = await api(`/invoices/${invoice.id}/provider-confirm`, {
          payment_id: proof.razorpay_payment_id,
          signature: proof.razorpay_signature,
        });
        toast(
          t(
            result.ok
              ? "Payment confirmed"
              : "Awaiting verified provider capture",
          ),
        );
      } catch (error) {
        toast(error.message);
      }
      if (S.route[0] === "invoice" && S.route[1] === invoice.id) await render();
    },
    modal: {
      ondismiss: () => {
        if (S.route[0] === "invoice" && S.route[1] === invoice.id) render();
      },
    },
  });
  checkout.open();
}
