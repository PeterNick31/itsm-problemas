import base64
import hashlib
import hmac
import json
import os
import time


def _decode_segment(segment):
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def verify_token(token, secret=None):
    secret = secret or os.environ.get("JWT_SECRET")
    if not secret:
        raise ValueError("JWT_SECRET no está configurado")
    if not isinstance(token, str) or len(token) > 8192:
        raise ValueError("Token JWT mal formado")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token JWT mal formado")

    header = json.loads(_decode_segment(parts[0]))
    claims = json.loads(_decode_segment(parts[1]))
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("Token JWT mal formado")
    if header.get("alg") != "HS256":
        raise ValueError("Algoritmo JWT no permitido")

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, _decode_segment(parts[2])):
        raise ValueError("Firma JWT inválida")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= time.time():
        raise ValueError("Token JWT vencido o sin expiración")
    if not claims.get("tenant_id") or not claims.get("sub") or not claims.get("rol"):
        raise ValueError("Faltan claims requeridos en el JWT")
    return claims


def _policy(principal_id, effect, resource, claims=None):
    context = {}
    if claims:
        context = {
            "tenant_id": str(claims["tenant_id"]),
            "usuario_id": str(claims["sub"]),
            "rol": str(claims["rol"]),
        }
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
        "context": context,
    }


def authorize(event, _context):
    token = event.get("authorizationToken", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        claims = verify_token(token)
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise Exception("Unauthorized")
    return _policy(claims["sub"], "Allow", event["methodArn"], claims)
