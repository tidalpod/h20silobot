"""Plaid API wrapper for ACH payments using aiohttp"""

from __future__ import annotations

import logging
import hashlib
import hmac
import json
import time
from typing import Optional

import aiohttp
import jwt

from webapp.config import web_config

logger = logging.getLogger(__name__)

_verification_keys: dict[str, tuple[float, dict]] = {}
PLAID_WEBHOOK_MAX_AGE_SECONDS = 5 * 60
PLAID_KEY_CACHE_SECONDS = 24 * 60 * 60

PLAID_ENVS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _base_url() -> str:
    return PLAID_ENVS.get(web_config.plaid_env, PLAID_ENVS["sandbox"])


def _headers() -> dict:
    return {"Content-Type": "application/json"}


def _auth_body() -> dict:
    return {
        "client_id": web_config.plaid_client_id,
        "secret": web_config.plaid_secret,
    }


async def _get_webhook_verification_key(key_id: str) -> Optional[dict]:
    cached = _verification_keys.get(key_id)
    if cached and cached[0] > time.time():
        return cached[1]

    url = f"{_base_url()}/webhook_verification_key/get"
    payload = {**_auth_body(), "key_id": key_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200 or not data.get("key"):
                logger.warning("Plaid webhook verification key lookup failed")
                return None
            key = data["key"]
            _verification_keys[key_id] = (time.time() + PLAID_KEY_CACHE_SECONDS, key)
            return key


async def verify_webhook_signature(payload: bytes, signed_jwt: str) -> bool:
    """Verify Plaid's ES256 JWT and the exact request-body SHA-256 digest."""
    if not signed_jwt:
        return False
    try:
        header = jwt.get_unverified_header(signed_jwt)
        if header.get("alg") != "ES256" or not header.get("kid"):
            return False
        key = await _get_webhook_verification_key(header["kid"])
        if not key:
            return False
        public_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(key))
        claims = jwt.decode(
            signed_jwt,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        issued_at = int(claims.get("iat", 0))
        if not issued_at or abs(time.time() - issued_at) > PLAID_WEBHOOK_MAX_AGE_SECONDS:
            return False
        expected_hash = claims.get("request_body_sha256", "")
        actual_hash = hashlib.sha256(payload).hexdigest()
        return bool(expected_hash) and hmac.compare_digest(expected_hash, actual_hash)
    except Exception:
        logger.warning("Plaid webhook signature verification failed", exc_info=True)
        return False


async def create_link_token(tenant_id: int, tenant_name: str) -> dict:
    """Create a Plaid Link token for the tenant to connect their bank account."""
    url = f"{_base_url()}/link/token/create"
    payload = {
        **_auth_body(),
        "user": {"client_user_id": str(tenant_id)},
        "client_name": "Blue Deer Property Management",
        "products": ["transfer"],
        "country_codes": ["US"],
        "language": "en",
    }
    if web_config.plaid_webhook_url:
        payload["webhook"] = web_config.plaid_webhook_url

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid link/token/create failed: {data}")
                return {"error": data.get("error_message", "Failed to create link token")}
            return {"link_token": data["link_token"]}


async def create_entity_link_token(entity_id: int, entity_name: str) -> dict:
    """Create a Plaid Link token for a landlord entity to connect their bank account."""
    auth = _auth_body()
    logger.info(f"Entity link token: client_id present={bool(auth.get('client_id'))}, secret present={bool(auth.get('secret'))}, env={web_config.plaid_env}")
    url = f"{_base_url()}/link/token/create"
    payload = {
        **auth,
        "user": {"client_user_id": f"entity_{entity_id}"},
        "client_name": "Blue Deer Property Management",
        "products": ["transfer"],
        "country_codes": ["US"],
        "language": "en",
    }
    if web_config.plaid_webhook_url:
        payload["webhook"] = web_config.plaid_webhook_url

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            logger.info(f"Plaid entity link response status={resp.status}")
            if resp.status != 200:
                logger.error(f"Plaid entity link/token/create failed: {data}")
                return {"error": data.get("error_message", "Failed to create link token")}
            return {"link_token": data["link_token"]}


async def exchange_public_token(public_token: str) -> dict:
    """Exchange a public token from Plaid Link for an access token."""
    url = f"{_base_url()}/item/public_token/exchange"
    payload = {
        **_auth_body(),
        "public_token": public_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid token exchange failed: {data}")
                return {"error": data.get("error_message", "Token exchange failed")}
            return {
                "access_token": data["access_token"],
                "item_id": data["item_id"],
            }


async def get_accounts(access_token: str) -> dict:
    """Get account information (name, mask, institution) for a linked item."""
    url = f"{_base_url()}/accounts/get"
    payload = {
        **_auth_body(),
        "access_token": access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid accounts/get failed: {data}")
                return {"error": data.get("error_message", "Failed to get accounts")}

            accounts = []
            for acct in data.get("accounts", []):
                accounts.append({
                    "account_id": acct["account_id"],
                    "name": acct.get("name", ""),
                    "official_name": acct.get("official_name", ""),
                    "mask": acct.get("mask", ""),
                    "type": acct.get("type", ""),
                    "subtype": acct.get("subtype", ""),
                })

            # Get institution name
            institution_name = ""
            item = data.get("item", {})
            institution_id = item.get("institution_id")
            if institution_id:
                inst_data = await get_institution(institution_id)
                institution_name = inst_data.get("name", "")

            return {"accounts": accounts, "institution_name": institution_name}


async def get_institution(institution_id: str) -> dict:
    """Get institution info by ID."""
    url = f"{_base_url()}/institutions/get_by_id"
    payload = {
        **_auth_body(),
        "institution_id": institution_id,
        "country_codes": ["US"],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                return {}
            inst = data.get("institution", {})
            return {"name": inst.get("name", ""), "institution_id": institution_id}


async def create_transfer(
    access_token: str,
    account_id: str,
    amount: str,
    description: str,
    legal_name: str,
    idempotency_key: str,
    metadata: dict | None = None,
    ach_class: str = "web",
) -> dict:
    """Authorize and initiate an ACH debit from a tenant account.

    Plaid requires an approved transfer authorization before /transfer/create.
    The authorization id then makes transfer creation idempotent.
    """
    authorization_url = f"{_base_url()}/transfer/authorization/create"
    authorization_payload = {
        **_auth_body(),
        "access_token": access_token,
        "account_id": account_id,
        "type": "debit",
        "network": "ach",
        "amount": str(amount),
        "ach_class": ach_class,
        "user": {
            "legal_name": legal_name,
        },
        "idempotency_key": idempotency_key,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            authorization_url,
            json=authorization_payload,
            headers=_headers(),
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid transfer/authorization/create failed: {data}")
                return {"error": data.get("error_message", "Transfer authorization failed")}

        authorization = data.get("authorization", {})
        authorization_id = authorization.get("id")
        decision = authorization.get("decision")
        if decision != "approved" or not authorization_id:
            rationale = authorization.get("decision_rationale") or {}
            message = rationale.get("description") or "Bank transfer was not approved"
            return {
                "error": message,
                "decision": decision,
                "authorization_id": authorization_id,
            }

        transfer_url = f"{_base_url()}/transfer/create"
        transfer_payload = {
            **_auth_body(),
            "access_token": access_token,
            "account_id": account_id,
            "authorization_id": authorization_id,
            "amount": str(amount),
            "description": description[:10],  # ACH descriptions are limited to 10 chars.
        }
        if metadata:
            transfer_payload["metadata"] = {str(key): str(value) for key, value in metadata.items()}

        async with session.post(transfer_url, json=transfer_payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid transfer/create failed: {data}")
                return {
                    "error": data.get("error_message", "Transfer creation failed"),
                    "authorization_id": authorization_id,
                }
            transfer = data.get("transfer", {})
            return {
                "authorization_id": authorization_id,
                "transfer_id": transfer.get("id"),
                "status": transfer.get("status"),
            }


async def get_transfer(transfer_id: str) -> dict:
    """Check transfer status."""
    url = f"{_base_url()}/transfer/get"
    payload = {
        **_auth_body(),
        "transfer_id": transfer_id,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid transfer/get failed: {data}")
                return {"error": data.get("error_message", "Failed to get transfer")}
            transfer = data.get("transfer", {})
            return {
                "transfer_id": transfer.get("id"),
                "status": transfer.get("status"),
                "failure_reason": transfer.get("failure_reason"),
            }


async def sync_transfer_events(after_id: int = 0, count: int = 500) -> dict:
    """Fetch the next ordered page of Plaid Transfer events."""
    url = f"{_base_url()}/transfer/event/sync"
    payload = {
        **_auth_body(),
        "after_id": int(after_id),
        "count": min(max(int(count), 1), 500),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid transfer/event/sync failed: {data}")
                return {"error": data.get("error_message", "Failed to sync transfer events")}
            return {
                "events": data.get("transfer_events", []),
                "has_more": bool(data.get("has_more")),
            }


async def remove_item(access_token: str) -> dict:
    """Remove a Plaid item (unlink bank account)."""
    url = f"{_base_url()}/item/remove"
    payload = {
        **_auth_body(),
        "access_token": access_token,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid item/remove failed: {data}")
                return {"error": data.get("error_message", "Failed to remove item")}
            return {"removed": True}
