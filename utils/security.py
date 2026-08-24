"""
security.py

Password hashing (using PBKDF2-HMAC-SHA256) and database credentials encryption (using Fernet).
No external bcrypt or passlib dependencies required.
"""

import os
import base64
import hashlib
import secrets
from cryptography.fernet import Fernet

ITERATIONS = 600000  # OWASP recommendation for PBKDF2-HMAC-SHA256
SALT_SIZE = 16


def hash_password(password: str) -> str:
    """
    Hash a password securely using PBKDF2-HMAC-SHA256 with a random salt.
    Format returned: salt_hex:iterations:hash_hex
    """
    salt = secrets.token_bytes(SALT_SIZE)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    
    salt_hex = salt.hex()
    hash_hex = hash_bytes.hex()
    
    return f"{salt_hex}:{ITERATIONS}:{hash_hex}"


def verify_password(password: str, hashed_str: str) -> bool:
    """
    Verify a password against the stored secure hash.
    """
    try:
        parts = hashed_str.split(":")
        if len(parts) != 3:
            return False
        
        salt_hex, iter_str, hash_hex = parts
        salt = bytes.fromhex(salt_hex)
        iters = int(iter_str)
        
        test_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return secrets.compare_digest(test_hash.hex(), hash_hex)
    except Exception:
        return False


def derive_encryption_key(password: str, salt_str: str) -> str:
    """
    Derive a base64-encoded Fernet encryption key from the user's password and a salt string (e.g. email).
    """
    salt_bytes = hashlib.sha256(salt_str.encode("utf-8")).digest()
    key_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 100000)
    return base64.urlsafe_b64encode(key_bytes).decode("utf-8")


def encrypt_data(data: str, key_str: str) -> str:
    """
    Encrypt text using Fernet symmetric encryption.
    """
    fernet = Fernet(key_str.encode("utf-8"))
    return fernet.encrypt(data.encode("utf-8")).decode("utf-8")


def decrypt_data(encrypted_str: str, key_str: str) -> str:
    """
    Decrypt text using Fernet symmetric encryption.
    """
    fernet = Fernet(key_str.encode("utf-8"))
    return fernet.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
