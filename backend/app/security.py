"""Password hashing and session-token helpers; no plaintext credentials in DB."""
from argon2 import PasswordHasher, exceptions
from hashlib import sha256
from secrets import token_urlsafe
from hmac import compare_digest

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    if not (12 <= len(password) <= 256):
        raise ValueError("Password harus 12–256 karakter.")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (exceptions.VerifyMismatchError, exceptions.VerificationError, exceptions.InvalidHashError):
        return False


def fresh_secret() -> str:
    return token_urlsafe(32)


def digest(secret: str) -> str:
    return sha256(secret.encode('utf-8')).hexdigest()


def equal_hash(a: str, b: str) -> bool:
    return compare_digest(a, b)
