#!/usr/bin/env python3
"""Generate a Fernet encryption key for storing credentials"""

from cryptography.fernet import Fernet

key = Fernet.generate_key()
print("Generated Encryption Key:")
print(key.decode())
print("\nAdd this to your .env file as:")
print(f"ENCRYPTION_KEY={key.decode()}")
