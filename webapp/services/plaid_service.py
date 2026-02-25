"""Plaid API wrapper for ACH payments using aiohttp"""

import logging
from typing import Optional

import aiohttp

from webapp.config import web_config

logger = logging.getLogger(__name__)

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
) -> dict:
    """Initiate an ACH debit transfer (pull money from tenant's account)."""
    url = f"{_base_url()}/transfer/create"
    payload = {
        **_auth_body(),
        "access_token": access_token,
        "account_id": account_id,
        "type": "debit",
        "network": "ach",
        "amount": str(amount),
        "ach_class": "ppd",
        "description": description[:10],  # Plaid limits to 10 chars
        "user": {
            "legal_name": "Tenant",
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"Plaid transfer/create failed: {data}")
                return {"error": data.get("error_message", "Transfer creation failed")}
            transfer = data.get("transfer", {})
            return {
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
