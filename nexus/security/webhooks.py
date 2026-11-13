import base64
import hashlib
import hmac
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def fresh(timestamp: str) -> bool:
    try:
        return timestamp.isdigit() and abs(int(time.time()) - int(timestamp)) <= 300
    except (ValueError, OverflowError):
        return False


def verify_n8n(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    if len(secret) < 32 or not fresh(timestamp):
        return False
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_manus(public_key: str, url: str, body: bytes, timestamp: str, signature: str) -> bool:
    if not fresh(timestamp):
        return False
    try:
        key = serialization.load_pem_public_key(public_key.encode())
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            return False
        content = f"{timestamp}.{url}.{hashlib.sha256(body).hexdigest()}".encode()
        key.verify(
            base64.b64decode(signature, validate=True), content, padding.PKCS1v15(), hashes.SHA256()
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
