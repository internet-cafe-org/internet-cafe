"""Cryptographic key generation utility (SEC-00).

Generates:
1. ES256 (ECDSA P-256) private and public PEM key pair for JWT signing/verification.
2. Versioned key ring for data encryption (DATA_ENC_KEYS) with AES-256-GCM keys.
3. Blind index key (BLIND_INDEX_KEY) for deterministic HMAC-SHA256 indexing.

Output files are stored by default in tools/keys/ (ignored by git).
"""

import argparse
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def generate_es256_keypair() -> tuple[str, str]:
    """Generate an ECDSA P-256 (secp256r1) keypair in PEM format.

    Returns:
        tuple[str, str]: (private_key_pem, public_key_pem)
    """
    private_key = ec.generate_private_key(ec.SECP256R1())

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def generate_data_enc_keys(initial_version: str = "1") -> dict[str, str]:
    """Generate a versioned key ring dictionary with a 256-bit AES key.

    Args:
        initial_version: Version identifier for the initial key.

    Returns:
        dict: Mapping version -> 64-character hexadecimal key representation.
    """
    key_hex = secrets.token_hex(32)
    return {str(initial_version): key_hex}


def generate_blind_index_key() -> str:
    """Generate a 256-bit random key for blind index HMAC computation.

    Returns:
        str: 64-character hexadecimal string representing 32 random bytes.
    """
    return secrets.token_hex(32)


def generate_all_keys(target_dir: str | Path | None = None) -> dict[str, str]:
    """Generate and persist all cryptographic keys required for SEC-00.

    Args:
        target_dir: Directory where keys will be written. Defaults to Backend/tools/keys.

    Returns:
        dict: Paths of generated artifacts.
    """
    if target_dir is None:
        base_dir = Path(__file__).resolve().parent
        out_dir = base_dir / "keys"
    else:
        out_dir = Path(target_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate ES256 Key Pair
    private_pem, public_pem = generate_es256_keypair()
    priv_file = out_dir / "jwt_es256_private.pem"
    pub_file = out_dir / "jwt_es256_public.pem"

    with open(priv_file, "w", encoding="utf-8") as f:
        f.write(private_pem)

    with open(pub_file, "w", encoding="utf-8") as f:
        f.write(public_pem)

    # 2. Generate DATA_ENC_KEYS ring
    enc_ring = generate_data_enc_keys("1")
    enc_file = out_dir / "data_enc_keys.json"
    with open(enc_file, "w", encoding="utf-8") as f:
        json.dump(enc_ring, f, indent=2)

    # 3. Generate BLIND_INDEX_KEY
    bidx_key = generate_blind_index_key()
    bidx_file = out_dir / "blind_index_key.txt"
    with open(bidx_file, "w", encoding="utf-8") as f:
        f.write(bidx_key + "\n")

    # 4. Generate local environment snippet (.env.keys) for local development convenience
    env_snippet_file = out_dir / "keys.env"
    escaped_priv = private_pem.replace("\n", "\\n")
    escaped_pub = public_pem.replace("\n", "\\n")
    enc_ring_json = json.dumps(enc_ring)

    with open(env_snippet_file, "w", encoding="utf-8") as f:
        f.write("# Generated development keys (do NOT commit to git)\n")
        f.write(f'JWT_PRIVATE_KEY="{escaped_priv}"\n')
        f.write(f'JWT_PUBLIC_KEY="{escaped_pub}"\n')
        f.write(f"DATA_ENC_KEYS='{enc_ring_json}'\n")
        f.write(f"BLIND_INDEX_KEY={bidx_key}\n")

    return {
        "jwt_private_key": str(priv_file),
        "jwt_public_key": str(pub_file),
        "data_enc_keys": str(enc_file),
        "blind_index_key": str(bidx_file),
        "env_snippet": str(env_snippet_file),
    }


def main() -> None:
    """CLI entry point for key generation script."""
    parser = argparse.ArgumentParser(
        description="Generate development cryptographic keys for Internet Cafe backend."
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        type=str,
        default=None,
        help="Target directory to write key files (default: Backend/tools/keys)",
    )
    args = parser.parse_args()

    results = generate_all_keys(args.out_dir)
    print("Cryptographic keys generated successfully.")
    print(f"Directory: {os.path.dirname(results['jwt_private_key'])}")
    print("Files created:")
    for name, path in results.items():
        print(f"  - {name}: {os.path.basename(path)}")


if __name__ == "__main__":
    main()
