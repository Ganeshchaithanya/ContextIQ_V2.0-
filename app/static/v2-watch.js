"use strict";

function priceMoney(minor, currency) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(
    minor / 100,
  );
}

async function sharedCartReview(intent) {
  const search = location.hash.split("?")[1] || "";
  const token = new URLSearchParams(search).get("cart");
  S.sharedCartToken = null;
  if (!token) return "";
  try {
    const cart = await api("/store-cart/review", { token });
    S.sharedCartToken = token;
    const next =
      intent === "checkout"
        ? button("Create checkout invoice", "checkout-shared-cart", "", "green")
        : button("Track these items", "watch-shared-cart", "", "green");
    return `<section class="panel"><h2>${esc(t("Shared by BrightMart"))}</h2><p class="field-hint">${esc(t("This is a snapshot. Your cart stays at BrightMart."))}</p>${cart.items.map((item) => `<div class="list-row"><div><h3>${esc(item.name)}</h3><p>${item.quantity} × ${money(item.unit_minor)}</p></div><strong>${money(item.quantity * item.unit_minor)}</strong></div>`).join("")}${kv("Total", money(cart.total_minor))}<div class="actions" style="margin-top:16px">${next}</div></section>`;
  } catch (error) {
    return `<div class="notice warn">${esc(error.message)}</div>`;
  }
}

async function watchPage() {
  const registrations = await api("/watch");
  const selected = S.route[0] === "watch" ? S.route[1] : null;
  const handoff = await sharedCartReview("track");
  const rows = registrations.filter((row) => !selected || row.id === selected);
  return `${back(selected ? "purchases/before" : "purchases")}${head("Cart Intelligence", "Before payment · track items you are interested in", '<a class="btn white" href="/store">Open BrightMart ↗</a>')}${handoff}<section class="panel"><h2>${esc(t("Watch a product"))}</h2><p class="field-hint">${esc(t("Enter a public product page. ContextIQ watches its published price and alerts you when it sets a new low since tracking began."))}</p><form id="watch-product-form" style="margin-top:16px">${field("Product page URL", "product_url", "", "url", 'required maxlength="2000" placeholder="https://store.example/product"')}<button type="submit" class="btn green">${esc(t("Track price"))}</button></form></section>${rows.length ? `<div class="grid two">${rows.map(watchCard).join("")}</div>` : `<section class="panel"><p class="muted">${esc(t(selected ? "This tracked item is no longer available." : "No tracked items yet. Share your BrightMart cart or add a public product link."))}</p></section>`}`;
}

function watchCard(row) {
  return `<section class="panel"><h2>${esc(row.title)}</h2><p class="field-hint">${esc(row.merchant)} · ${esc(t("Quantity"))} ${row.quantity}</p>${kv("Last observed price", priceMoney(row.current_minor, row.currency))}${kv("Lowest since tracking began", priceMoney(row.low_minor, row.currency))}<p class="field-hint">${esc(t("Last checked"))} ${esc(new Date(row.checked_at).toLocaleString())}</p>${row.error ? `<div class="notice warn">${esc(row.error)}</div>` : ""}<details style="margin:14px 0"><summary>${esc(t("Price history"))}</summary>${row.history.map((sample) => kv(new Date(sample.at).toLocaleString(), priceMoney(sample.amount_minor, row.currency))).join("")}</details><div class="actions"><a class="btn white small" href="${esc(row.source_url)}" rel="noopener noreferrer" target="_blank">${esc(t("Open product page"))} ↗</a>${button("Check price", "watch-refresh", row.id, "small white")}${button("Stop tracking", "watch-stop", row.id, "small ghost")}</div></section>`;
}

function checkoutForm(row) {
  const existing = row.checkout.existing_method;
  const choices = Object.entries(row.checkout.methods);
  const select = `<div class="form-field"><label for="pay-method">${esc(t("Payment method"))}</label><select id="pay-method" name="method">${!existing ? `<option value="mock">${esc(t("Mock payment"))}</option>` : ""}${choices.map(([key, label]) => `<option value="${key}" ${!row.checkout.gateway_available || (existing && key !== existing) ? "disabled" : ""} ${existing === key ? "selected" : ""}>${esc(t(label))} · ${esc(t(row.checkout.gateway_available ? "Razorpay test checkout" : "Not configured"))}</option>`).join("")}</select></div>`;
  return `<form id="authorize-form">${select}${check("I authorize this exact amount, recipient and invoice.", "authorized")}<div id="mock-payment-options" ${existing ? "hidden" : ""}>${check("Demo response interruption", "simulate_interruption")}</div><div class="actions"><button id="continue-payment" class="btn green" type="submit">${esc(t(existing ? "Continue to payment" : "Pay with mock provider"))} · ${money(row.total_minor)}</button>${existing ? button("Check provider status", "provider-check", row.id, "white") : row.case_id ? button("Check original payment", "reconcile", row.id, "white") : ""}</div></form>`;
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
