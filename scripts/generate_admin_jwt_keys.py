#!/usr/bin/env python3
"""Generate RS256 JWT key pair for admin-service (dev / sops template)."""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    """Print PEM keys with escaped newlines for ``.env`` / sops."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    private_one_line = private_pem.replace("\n", "\\n")
    public_one_line = public_pem.replace("\n", "\\n")
    print("JWT_PRIVATE_KEY=" + private_one_line)
    print("JWT_PUBLIC_KEY=" + public_one_line)


if __name__ == "__main__":
    main()
