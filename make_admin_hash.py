# make_admin_hash.py
import os, base64, hashlib, hmac

_DEF_ITERS = 260000  # same as modern Django defaults

def _pbkdf2_sha256(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def hash_password(password: str, iterations: int = _DEF_ITERS) -> str:
    """Return Django-style: pbkdf2_sha256$iters$salt$hash"""
    salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
    dk = _pbkdf2_sha256(password, base64.urlsafe_b64decode(salt + "=="), iterations)
    digest_b64 = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt}${digest_b64}"

def hash_password_legacy_b64pack(password: str, iterations: int = _DEF_ITERS) -> str:
    """Legacy format we used earlier: base64(salt+digest) without metadata."""
    salt = os.urandom(16)
    dk = _pbkdf2_sha256(password, salt, iterations)
    return base64.b64encode(salt + dk).decode("ascii")

def _consteq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)

def verify_password(password: str, stored: str) -> bool:
    """
    Accepts multiple PBKDF2 SHA-256 formats:
      - pbkdf2_sha256$iters$salt$hash
      - pbkdf2:sha256:iters$salt$hash
      - $pbkdf2-sha256$iters$salt$hash
      - base64(salt+digest) legacy pack
    """
    s = (stored or "").strip()

    try:
        if s.startswith("pbkdf2_sha256$"):
            # Django style
            _, iters, salt_b64, dig_b64 = s.split("$", 3)
            iters = int(iters)
            salt = base64.urlsafe_b64decode(salt_b64 + "==")
            want = base64.urlsafe_b64decode(dig_b64 + "==")
            got = _pbkdf2_sha256(password, salt, iters)
            return _consteq(got, want)

        if s.startswith("pbkdf2:sha256:"):
            # Flask/Passlib style
            _, algo, iters_salt_hash = s.split(":", 2)
            parts = iters_salt_hash.split("$")
            iters = int(parts[0])
            salt_b64, dig_b64 = parts[1], parts[2]
            salt = base64.urlsafe_b64decode(salt_b64 + "==")
            want = base64.urlsafe_b64decode(dig_b64 + "==")
            got = _pbkdf2_sha256(password, salt, iters)
            return _consteq(got, want)

        if s.startswith("$pbkdf2-sha256$"):
            # Modular crypt style: $pbkdf2-sha256$iters$salt$hash
            _, scheme, iters, salt_b64, dig_b64 = s.split("$", 4)
            iters = int(iters)
            salt = base64.urlsafe_b64decode(salt_b64 + "==")
            want = base64.urlsafe_b64decode(dig_b64 + "==")
            got = _pbkdf2_sha256(password, salt, iters)
            return _consteq(got, want)

        # Fallback: legacy base64(salt+digest)
        raw = base64.b64decode(s)
        if len(raw) >= 16:
            salt, want = raw[:16], raw[16:]
            got = _pbkdf2_sha256(password, salt, _DEF_ITERS)
            # We don't know iterations here; assume default used on creation.
            return _consteq(got, want)

    except Exception:
        return False

    return False

if __name__ == "__main__":
    pw = input("Enter password to hash for admin: ").strip()
    print(hash_password(pw))  # Django-style line to paste into the sheet
