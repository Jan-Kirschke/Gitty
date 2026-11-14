import base64
import hashlib
import secrets
import json
from typing import Optional
from datetime import datetime


def xor_encrypt(text: str, key: str) -> str:
    if not key:
        return text
    result = []
    for i, char in enumerate(text):
        key_char = key[i % len(key)]
        result.append(chr(ord(char) ^ ord(key_char)))
    return "".join(result)


def xor_encrypt_base64(text: str, key: str) -> str:
    encrypted = xor_encrypt(text, key)
    return base64.b64encode(encrypted.encode()).decode()


def xor_decrypt_base64(encrypted: str, key: str) -> str:
    try:
        decoded = base64.b64decode(encrypted.encode()).decode()
        return xor_encrypt(decoded, key)
    except Exception:
        return "[Decryption failed]"


def generate_session_id() -> str:
    return secrets.token_hex(16)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get_timestamp() -> str:
    return datetime.now().isoformat()


def format_message_packet(
    sender: str,
    content: str,
    target: Optional[str] = None,
    rating: int = 0,
) -> str:
    packet = {
        "from": sender,
        "to": target,
        "msg": content,
        "rating": rating,
        "timestamp": get_timestamp(),
    }
    return json.dumps(packet)


def parse_message_packet(data: str) -> dict:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}


def validate_username(username: str) -> tuple[bool, Optional[str]]:
    if not username or len(username) < 2:
        return False, "Username must be at least 2 characters"
    if len(username) > 32:
        return False, "Username must be at most 32 characters"
    if not username.replace("_", "").replace("-", "").isalnum():
        return False, "Username must be alphanumeric (underscores and hyphens allowed)"
    return True, None
