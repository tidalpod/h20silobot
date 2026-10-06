import hashlib
import json
import time
import asyncio

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.requests import Request

from database.encrypted import decrypt_sensitive_value, encrypt_sensitive_value, is_encrypted
from telegram_access import is_authorized
from webapp.auth.dependencies import require_auth
from webapp.config import web_config
from webapp.request_security import client_ip
from webapp.routes.api import router as api_router
from webapp.services import plaid_service
from webapp.services.storage_service import storage
from webapp.services.upload_security import safe_upload_extension


def _request(peer="127.0.0.1", headers=None):
    raw_headers = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer, 1234),
        "scheme": "https",
        "server": ("example.test", 443),
        "query_string": b"",
    })


def test_sensitive_values_are_encrypted_and_round_trip(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = encrypt_sensitive_value("bank-secret")

    assert is_encrypted(ciphertext)
    assert "bank-secret" not in ciphertext
    assert decrypt_sensitive_value(ciphertext) == "bank-secret"


def test_upload_extension_comes_from_verified_content():
    png = b"\x89PNG\r\n\x1a\n" + b"safe-image"
    assert safe_upload_extension("image/png", png, {"image/png"}) == ".png"
    with pytest.raises(ValueError):
        safe_upload_extension("image/jpeg", b"<script>alert(1)</script>", {"image/jpeg"})


def test_forwarded_ip_is_only_accepted_from_configured_proxy(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setattr(web_config, "trusted_proxy_ips", "10.0.0.2")
    headers = {"x-forwarded-for": "203.0.113.20"}

    assert client_ip(_request("198.51.100.9", headers)) == "198.51.100.9"
    assert client_ip(_request("10.0.0.2", headers)) == "203.0.113.20"


def test_railway_real_ip_is_accepted_only_on_railway(monkeypatch):
    headers = {"x-real-ip": "203.0.113.25"}
    monkeypatch.setattr(web_config, "trusted_proxy_ips", "")

    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    assert client_ip(_request("10.0.0.3", headers)) == "10.0.0.3"

    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert client_ip(_request("10.0.0.3", headers)) == "203.0.113.25"


def test_entire_api_router_requires_authentication():
    assert any(dependency.dependency is require_auth for dependency in api_router.dependencies)


def test_telegram_access_fails_closed_without_allowlist_or_database(monkeypatch):
    for name in (
        "BLUEDEER_BOT_USER_IDS", "BLUEDEER_VAULT_USER_IDS",
        "BLUEDEER_ADMIN_TELEGRAM_ID", "TELEGRAM_ADMIN_USER_IDS",
    ):
        monkeypatch.delenv(name, raising=False)

    update = type("Update", (), {"effective_user": type("User", (), {"id": 123})()})()
    context = type("Context", (), {"bot_data": {"db_available": False}})()
    assert asyncio.run(is_authorized(update, context)) is False


def test_plaid_webhook_verifies_jwt_and_exact_body(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))

    async def verification_key(_key_id):
        return public_jwk

    monkeypatch.setattr(plaid_service, "_get_webhook_verification_key", verification_key)
    payload = b'{"webhook_type":"TRANSFER"}'
    token = jwt.encode(
        {
            "iat": int(time.time()),
            "request_body_sha256": hashlib.sha256(payload).hexdigest(),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )

    assert asyncio.run(plaid_service.verify_webhook_signature(payload, token)) is True
    assert asyncio.run(plaid_service.verify_webhook_signature(payload + b" ", token)) is False


def test_sensitive_storage_keys_are_never_public_urls():
    assert storage._delivery_url("leases/signed/example.pdf") == "/protected-files/leases/signed/example.pdf"
    assert storage.is_protected_key("invoices/example.pdf") is True
    assert storage._extract_key("/protected-files/leases/../../.env") == ""
