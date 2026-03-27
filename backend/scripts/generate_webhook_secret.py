#!/usr/bin/env python3
"""
Generate a secure random webhook secret for WEBHOOK_SECRET.

Usage:
  python scripts/generate_webhook_secret.py

Copy the output into your .env as:
  WEBHOOK_SECRET=the_generated_value
"""

import secrets

if __name__ == "__main__":
    secret = secrets.token_urlsafe(32)
    print(secret)
    print("\n# Add to your .env file:")
    print(f"WEBHOOK_SECRET={secret}")
