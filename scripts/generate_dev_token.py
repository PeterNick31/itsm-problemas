import argparse
import base64
import hashlib
import hmac
import json
import os
import time


def encode(value):
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")


def main():
    parser = argparse.ArgumentParser(description="Genera un JWT local para probar la API.")
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--user")
    parser.add_argument("--role", choices=("ADMIN", "AGENTE"), default="ADMIN")
    args = parser.parse_args()
    secret = os.environ.get("JWT_SECRET")
    if not secret or secret == "local-only-change-me":
        parser.error("Configura JWT_SECRET con un valor local no compartido antes de generar el token.")
    user_id = args.user or f"usr-{args.tenant}-00001"

    header = encode({"alg": "HS256", "typ": "JWT"})
    now = int(time.time())
    payload = encode({
        "sub": user_id,
        "tenant_id": args.tenant,
        "rol": args.role,
        "iat": now,
        "exp": now + 3600,
    })
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{header}.{payload}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    print(f"{header}.{payload}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}")


if __name__ == "__main__":
    main()
