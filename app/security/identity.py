"""Optional verified OIDC boundary; demo identity remains isolated and explicitly labelled."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import jwt
from fastapi import HTTPException
from sqlalchemy import delete, select, update, text
from sqlalchemy.exc import IntegrityError
from ..config import settings
from ..models import RateWindow, User, VerifiedIdentity, _id
from ..v2_models import DemoSession, Personalization


@lru_cache(maxsize=4)
def key_client(url):
    return jwt.PyJWKClient(url, timeout=5, lifespan=300)


def verify_token(token):
    if settings.auth_mode != "oidc" or not all((settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url)):
        raise HTTPException(503, "Verified identity provider is not configured")
    try:
        key = key_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256"],
                            issuer=settings.oidc_issuer, audience=settings.oidc_audience,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=10)
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError("Missing subject")
        return claims
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Identity verification failed") from None


def exchange(db, token):
    claims = verify_token(token)
    ident = hashlib.sha256((claims["iss"] + "\0" + claims["sub"]).encode()).hexdigest()
    if db.bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(bytes.fromhex(ident)[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
    # Subject, issuer, audience, signature and expiry are verified before database access.
    principal = db.scalar(select(VerifiedIdentity).where(VerifiedIdentity.id == ident).with_for_update())
    if not principal:
        uid = _id()
        principal = VerifiedIdentity(id=ident, workspace_id=_id(), buyer_id="account-" + uid, seller_id="demo-store-" + uid)
        db.add(principal)
        db.add_all([User(id=principal.buyer_id, name="Your account", available_balance=0, balance_source="user_recorded"),
                    User(id=principal.seller_id, name="Demo store", role="merchant")])
        db.add(Personalization(user_id=principal.buyer_id, data={
            "name": "Your account", "persona": "freelancer", "language": "en", "onboarded": False,
            "configuration": "business", "override": "auto", "workspace": "business",
            "features": ["budget", "purchases", "goals", "emi", "business"], "cart": [],
            "context_consent": False, "work_start": 9, "work_end": 18,
        }))
        db.flush()
    # One active browser session per account. Rotation revokes the previous cookie.
    db.execute(delete(DemoSession).where(DemoSession.workspace_id == principal.workspace_id))
    raw = secrets.token_urlsafe(32)
    expiry = min(datetime.fromtimestamp(claims["exp"], UTC), datetime.now(UTC) + timedelta(hours=1))
    session = DemoSession(token_hash=hashlib.sha256(raw.encode()).hexdigest(), workspace_id=principal.workspace_id,
                          buyer_id=principal.buyer_id, seller_id=principal.seller_id,
                          csrf=secrets.token_urlsafe(24), expires_at=expiry)
    db.add(session)
    db.flush()
    return raw, session


def rate_allowed(db, subject, limit=180):
    stamp = datetime.now(UTC)
    window = int(stamp.timestamp()) // 60
    key = hashlib.sha256(f"{subject}:{window}".encode()).hexdigest()
    if not db.get(RateWindow, key):
        try:
            with db.begin_nested():
                db.add(RateWindow(id=key, hits=0, expires_at=stamp + timedelta(minutes=2)))
                db.flush()
        except IntegrityError:
            pass
    return db.execute(update(RateWindow).where(RateWindow.id == key, RateWindow.hits < limit)
                      .values(hits=RateWindow.hits + 1)).rowcount == 1
