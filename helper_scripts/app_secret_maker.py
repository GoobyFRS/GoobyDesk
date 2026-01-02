#!/usr/bin/env python3
# Generate a cryptographically secure random string to be used as the FLASKAPP_SECRET_KEY.
import secrets
import string

def generate_flask_secret_key(length=30):
    alphabet = string.ascii_uppercase + string.digits
    secret_key = ''.join(secrets.choice(alphabet) for _ in range(length))
    return secret_key

def main():
    key = generate_flask_secret_key()
    print(f"GENERATED NEW {key}")
    print(f"\nAdd this to your .env file or configuration:")
    print(f"FLASKAPP_SECRET_KEY={key}")

if __name__ == "__main__":
    main()