#!/usr/bin/env python3
[__all__] = ["hash_password, verify_password"]
import bcrypt

def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed_user_password = bcrypt.hashpw(plain_password.encode(), salt)
    return hashed_user_password.decode()

def verify_password(plain_password: str, stored_hash: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode(),
        stored_hash.encode()
    )
