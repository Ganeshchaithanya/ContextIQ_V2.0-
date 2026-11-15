"""Read a single, explicitly identified publicly offered product price."""
import http.client
import ipaddress
import json
import socket
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_DOCUMENT = 2_000_000
SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP", "CAD", "AUD", "SGD", "AED"}


class PriceUnavailable(ValueError):
    pass


class ProductMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.collecting = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.collecting = True
            self.parts = []

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.collecting:
            self.collecting = False
            try:
                self.documents.append(json.loads("".join(self.parts)))
            except (ValueError, RecursionError):
                pass


def nodes(value):
    queue = [value]
    while queue:
        value = queue.pop()
        if isinstance(value, list):
            queue.extend(value)
        elif isinstance(value, dict):
            yield value
            queue.append(value.get("@graph"))


def has_type(value, expected):
    types = value if isinstance(value, list) else [value]
    return any(isinstance(item, str) and item.rstrip("/").rsplit("/", 1)[-1] == expected for item in types)


def parse_price(html, merchant):
    parser = ProductMetadata()
    parser.feed(html)
    candidates = []
    for product in nodes(parser.documents):
        if not has_type(product.get("@type"), "Product") or not isinstance(product.get("name"), str):
            continue
        offers = product.get("offers", [])
        for offer in offers if isinstance(offers, list) else [offers]:
            if not isinstance(offer, dict) or not has_type(offer.get("@type"), "Offer"):
                continue
            if str(offer.get("availability", "")).rsplit("/", 1)[-1] in {"OutOfStock", "SoldOut", "Discontinued", "PreOrder"}:
                continue
            price = offer.get("price", "")
            currency = offer.get("priceCurrency")
            if not price and isinstance(offer.get("priceSpecification"), dict):
                price = offer["priceSpecification"].get("price", "")
                currency = currency or offer["priceSpecification"].get("priceCurrency")
            try:
                minor = Decimal(str(price)) * 100
                if not minor.is_finite() or not 0 < minor < 100_000_000_000 or minor != minor.to_integral_value():
                    continue
            except InvalidOperation:
                continue
            if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
                continue
            title = product["name"].strip()[:160]
            key = str(product.get("sku") or product.get("gtin") or title).strip()[:160]
            candidates.append((title, key, int(minor), currency))
    unique = set(candidates)
    if len(unique) != 1:
        raise PriceUnavailable("This page does not publish one unambiguous, in-stock product price.")
    title, key, minor, currency = unique.pop()
    return {"title": title, "key": key, "minor": minor, "currency": currency, "merchant": merchant}


def read_public_product(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise PriceUnavailable("Use a public HTTPS product URL.")
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise PriceUnavailable("Private or local network locations cannot be tracked.")
        # Keep TLS verification on the URL's hostname and pin the socket to the approved DNS result.
        connection = http.client.HTTPSConnection(host, timeout=6)
        ip = sorted(addresses, key=lambda address: (":" in address, address))[0]
        connection._create_connection = lambda _, timeout, source_address=None: socket.create_connection((ip, 443), timeout, source_address)
        try:
            path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            connection.request("GET", path, headers={"User-Agent": "ContextIQPriceMonitor/1.0", "Accept": "text/html", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status != 200 or "text/html" not in response.getheader("Content-Type", "").lower():
                raise PriceUnavailable("Open the final public product page. This address did not return product HTML.")
            body = response.read(MAX_DOCUMENT + 1)
        finally:
            connection.close()
        if len(body) > MAX_DOCUMENT:
            raise PriceUnavailable("This page is too large to inspect reliably.")
        return parse_price(body.decode("utf-8", errors="replace"), host)
    except PriceUnavailable:
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise PriceUnavailable("The product page could not be reached or read.") from exc
