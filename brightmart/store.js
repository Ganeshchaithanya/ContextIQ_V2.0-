"use strict";

const select = (selector) => document.querySelector(selector);
const safe = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const moneyInr = (minor) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(minor / 100);
const storageKey = "brightmart.cart.v1";
let cart = {};
let catalog = [];

try {
  const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
  if (saved && !Array.isArray(saved) && typeof saved === "object") cart = saved;
} catch {
  /* This visitor can still build a cart for the current tab. */
}

function lines() {
  return catalog
    .filter((p) => Number.isInteger(cart[p.id]) && cart[p.id] > 0)
    .map((p) => ({ ...p, quantity: Math.min(cart[p.id], 100) }));
}

function updateCount() {
  select("#cart-count").textContent = lines().reduce(
    (sum, item) => sum + item.quantity,
    0,
  );
}

function setQuantity(sku, quantity) {
  if (!catalog.some((p) => p.id === sku)) return;
  if (quantity) cart[sku] = Math.min(100, quantity);
  else delete cart[sku];
  try {
    localStorage.setItem(storageKey, JSON.stringify(cart));
  } catch {
    /* In-memory cart remains available. */
  }
  updateCount();
}

function showCart() {
  const items = lines();
  const total = items.reduce(
    (sum, item) => sum + item.quantity * item.price_minor,
    0,
  );
  select("#cart-body").innerHTML =
    `<div class="cart-title"><h2>Your BrightMart cart</h2><button data-cart-close type="button">Close</button></div>${items.map((item) => `<div class="cart-line"><div><a href="/product/${item.id}"><strong>${safe(item.name)}</strong></a><p>${moneyInr(item.price_minor)} each</p></div><label>Qty <input aria-label="Quantity for ${safe(item.name)}" data-quantity="${item.id}" type="number" min="0" max="100" value="${item.quantity}"></label><button type="button" data-remove="${item.id}">Remove</button></div>`).join("") || "<p>Your cart is empty.</p>"}${items.length ? `<div class="cart-total">Subtotal <strong>${moneyInr(total)}</strong></div><div class="cart-buttons"><button type="button" data-share="track">Track in ContextIQ</button><button type="button" data-share="checkout">Continue to payment</button></div><p class="fine-print">Shares a snapshot of these items and quantities. Your cart stays at BrightMart.</p>` : ""}`;
  if (!select("#cart").open) select("#cart").showModal();
}

document.addEventListener("click", async (event) => {
  const control = event.target.closest("button");
  if (!control) return;
  if (control.id === "open-cart") showCart();
  if (control.hasAttribute("data-cart-close")) select("#cart").close();
  if (control.dataset.remove) {
    setQuantity(control.dataset.remove, 0);
    showCart();
  }
  if (control.dataset.add) {
    setQuantity(
      control.dataset.add,
      (Number(cart[control.dataset.add]) || 0) + 1,
    );
    select("#message").textContent = "Added to your cart.";
  }
  if (control.dataset.share) {
    control.disabled = true;
    try {
      const response = await fetch(
        `${window.BRIGHTMART_API}/handoff?intent=${encodeURIComponent(control.dataset.share)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            items: lines().map(({ id, quantity }) => ({
              product_id: id,
              quantity,
            })),
          }),
        },
      );
      if (!response.ok) throw new Error("Cart sharing failed. Try again.");
      const result = await response.json();
      window.location.assign(result.url);
    } catch (error) {
      select("#cart-body").insertAdjacentHTML(
        "beforeend",
        `<p role="alert">${safe(error.message)}</p>`,
      );
      control.disabled = false;
    }
  }
});

document.addEventListener("change", (event) => {
  if (!event.target.dataset.quantity) return;
  setQuantity(
    event.target.dataset.quantity,
    Math.max(0, Math.floor(Number(event.target.value))),
  );
  showCart();
});

async function bootStore() {
  const shop = select("#shop");
  try {
    const response = await fetch(`${window.BRIGHTMART_API}/catalog`);
    if (!response.ok) throw new Error("Catalog unavailable.");
    const data = await response.json();
    catalog = data.products;
    const sku = location.pathname.split("/")[2];
    const shown = sku ? catalog.filter((p) => p.id === sku) : catalog;
    if (sku && !shown.length) throw new Error("Product not found.");
    shop.innerHTML = `<section class="shop-hero"><p>BRIGHTMART ELECTRONICS</p><h1>${sku ? safe(shown[0].name) : "Shop everyday electronics"}</h1><p>Fictional storefront for the ContextIQ demo.</p></section><div class="products">${shown.map((p) => `<article><a href="/product/${p.id}" class="product-image"><img src="${safe(p.image)}" alt="" loading="lazy"></a><div class="product-content"><h2><a href="/product/${p.id}">${safe(p.name)}</a></h2><p>${safe(p.description)}</p><div class="product-actions"><strong>${moneyInr(p.price_minor)}</strong><button type="button" data-add="${p.id}">Add to cart</button></div></div></article>`).join("")}</div>${sku ? `<section class="terms"><h2>Purchase terms</h2><p>${safe(data.policy)}</p></section>` : ""}`;
    updateCount();
  } catch (error) {
    shop.textContent = error.message;
  } finally {
    shop.setAttribute("aria-busy", "false");
  }
}
bootStore();
