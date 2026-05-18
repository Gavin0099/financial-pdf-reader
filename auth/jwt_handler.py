import time
from typing import Dict

try:
    import jwt  # type: ignore
except Exception:  # pragma: no cover - import fallback for envs without PyJWT
    jwt = None

from config.config import AuthConfig


def token_response(token: str):
    return {"access_token": token}


secret_key = AuthConfig.JWT_SECRET


def sign_jwt(user_id: str) -> Dict[str, str]:
    if jwt is None:
        raise RuntimeError("PyJWT is required to sign JWT tokens")
    # Set the expiry time.
    payload = {"user_id": user_id, "expires": time.time() + 2400}
    return token_response(jwt.encode(payload, secret_key, algorithm="HS256"))


def decode_jwt(token: str) -> dict:
    if jwt is None:
        return {}
    try:
        decoded_token = jwt.decode(token.encode(), secret_key, algorithms=["HS256"])
        return decoded_token if decoded_token["expires"] >= time.time() else {}
    except Exception:
        return {}
