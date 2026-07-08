"""Password hashing primitives.

Closes VULN-5 (Weak Password Storage). The pre-fix code hashed passwords with
unsalted MD5; this module replaces that with bcrypt at cost factor 12, which
produces a per-call random salt and is intentionally slow to make
brute-forcing expensive even if the database is leaked.

Public surface: hash_password() and verify_password(). The auth service uses
hash_password() on signup to produce the stored hash, and verify_password()
on login to check a candidate password against that stored hash.
"""
import re
import bcrypt

# Work factor for bcrypt. 12 ~= ~250 ms per hash on modern hardware -- slow
# enough to make brute-force impractical, fast enough that legitimate logins
# feel instant. Bumping this raises the per-attempt cost roughly 2x per step.
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage in the users table.

    bcrypt.gensalt() produces a fresh random salt every call, so two users
    with identical passwords get different hashes (defeats rainbow tables).
    The salt is embedded in the returned hash string, so verify_password()
    does not need to know it separately.
    """
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a candidate password against a stored bcrypt hash.

    Returns False (never raises) on malformed hashes. This matters because
    the database may still contain legacy MD5 hex digests from before the
    bcrypt fix -- bcrypt.checkpw() raises ValueError on those, and a raise
    here would crash the login handler. Failing closed (returning False)
    means legacy MD5 accounts simply cannot authenticate, which is the
    correct security posture: operators are expected to wipe the DB or have
    affected users re-register (see CLAUDE.md "Login Flow After the Bcrypt
    Fix").
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
    


def password_meets_policy(password: str) -> bool:
    """Return True if the password satisfies the application's policy.

    Policy:
    - at least 8 characters
    - one uppercase letter
    - one lowercase letter
    - one digit
    - one special character
    """
    if not password or len(password) < 8:
        return False

    if not re.search(r"[A-Z]", password):
        return False

    if not re.search(r"[a-z]", password):
        return False

    if not re.search(r"\d", password):
        return False

    if not re.search(r"[^A-Za-z0-9]", password):
        return False

    return True
