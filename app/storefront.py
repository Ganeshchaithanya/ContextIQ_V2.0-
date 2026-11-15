"""Standalone BrightMart storefront. The browser cart stays on the shop origin."""
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .security.crypto import sign_message
from .config import settings
from .v2 import CATALOG, CartIn, POLICY, cart_items

app = FastAPI(title="BrightMart storefront", docs_url=None, redoc_url=None, openapi_url=None)
if settings.hosted_demo:
    app.add_middleware(CORSMiddleware, allow_origins=[settings.store_url],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
ASSETS = Path(__file__).parent.parent / "brightmart"
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


@app.get("/", response_class=HTMLResponse)
def index():
    return (ASSETS / "index.html").read_text(encoding="utf-8")


@app.get("/catalog")
def catalog():
    return {"products": CATALOG, "policy": POLICY}


@app.get("/product/{sku}", response_class=HTMLResponse)
def product(sku: str):
    row = next((row for row in CATALOG if row["id"] == sku), None)
    if not row:
        raise HTTPException(404, "Product not found")
    metadata = {"@context": "https://schema.org", "@type": "Product", "sku": sku, "name": row["name"],
                "offers": {"@type": "Offer", "price": f"{row['price_minor'] / 100:.2f}", "priceCurrency": "INR",
                           "availability": "https://schema.org/InStock"}}
    document = (ASSETS / "index.html").read_text(encoding="utf-8")
    return document.replace("<!-- product metadata -->", '<script type="application/ld+json">' + json.dumps(metadata).replace("<", "\\u003c") + "</script>")


@app.post("/handoff")
def handoff(body: CartIn, request: Request, intent: Literal["track", "checkout"] = "track"):
    origin = request.headers.get("origin")
    expected = settings.store_url if settings.hosted_demo else str(request.base_url).rstrip("/")
    if origin != expected:
        raise HTTPException(403, "Open the BrightMart cart to share items")
    items = cart_items(body.items)
    if not items or len({row["product_id"] for row in items}) != len(items):
        raise HTTPException(422, "A cart must contain distinct products")
    # Share only product identifiers and quantities. ContextIQ reads current prices independently.
    lines = [{"product_id": row["product_id"], "quantity": row["quantity"]} for row in items]
    token = sign_message({"typ": "brightmart.cart/1", "lines": lines, "intent": intent}, ttl=600)
    context_url = settings.app_url or settings.public_base_url.rstrip("/")
    route = "watch" if intent == "track" else "purchases/during"
    return {"url": f"{context_url}/#/{route}?cart={token}"}
