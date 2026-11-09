import base64
import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.auth import verify_token


def encode(value):
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")


def token(secret, payload):
    head = encode({"alg": "HS256", "typ": "JWT"})
    body = encode(payload)
    signature = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


class VerifyTokenTests(unittest.TestCase):
    def test_accepts_valid_token_and_returns_claims(self):
        claims = {"sub": "usr-acme-00001", "tenant_id": "acme", "rol": "ADMIN", "exp": 2_000_000_000}
        with patch("src.common.auth.time.time", return_value=1_900_000_000):
            self.assertEqual(verify_token(token("secret", claims), "secret"), claims)

    def test_rejects_bad_signature(self):
        claims = {"sub": "usr-acme-00001", "tenant_id": "acme", "rol": "ADMIN", "exp": 2_000_000_000}
        with self.assertRaisesRegex(ValueError, "Firma"):
            verify_token(token("other", claims), "secret")

    def test_rejects_expired_token(self):
        claims = {"sub": "usr-acme-00001", "tenant_id": "acme", "rol": "ADMIN", "exp": 1}
        with self.assertRaisesRegex(ValueError, "vencido"):
            verify_token(token("secret", claims), "secret")


if __name__ == "__main__":
    unittest.main()
