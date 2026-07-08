"""Password-reset request / validation / consumption helpers (token-based, self-service).

Implements the "Forgot / Reset Password" v2.1.0 feature. When a user forgets their
local password, they request a fresh sign-in by email; a single-use, time-limited
token is issued and they receive a reset link. Clicking the link presents a
"chose a new password" form; a successful submission clears the old password
and — as a side effect, since reset implies proven account control — also clears
any per-account lockout. An unincorporated token or one that has expired cannot
complete a reset.

Security posture:
- VULN-1 (SQL Injection): every SELECT and UPDATE here uses ? placeholders.
- VULN-3 (Reflected XSS): the token is NEVER echoed from the raw query string.
  Callers (the route layer) validate it server-side first; only the validated
  value is spliced into the form. All messages are fixed, server-controlled.
- VULN-5 (Weak Password Storage): new password is hashed with hash_password()
  (bcrypt) and validated with password_meets_policy() before storage. The
  plaintext never persists.
- Enumeration resistance: request_reset() is silent on Google-only or missing
  accounts; the route layer ensures the POST always returns the same generic
  200 response. The token itself provides no information about the account.
- Lockout interaction: a successful reset clears failed_login_attempts AND
  locked_until in the same UPDATE that writes the new password, so a user who
  resets a forgotten password is not then locked out on their first login.
"""

import logging
import secrets
import threading
import time

from app.core import config, mailer, security
from app.db.session import get_db

logger = logging.getLogger(__name__)

def request_reset(email: str, background: bool = True) -> str:
    """
    ...
    Return value is one of "sent" / "not_found". NOTE (deliberate product
    trade-off): returning a distinguishable status here, and the route layer
    surfacing it as a different message, REOPENS the account-enumeration
    protection this feature originally shipped with (an attacker can now
    learn which emails have local accounts by trying /forgot-password).
    This is intentional per the ticket's explicit request, not an oversight.
    """
    if not email:
        return "not_found"

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, username, password FROM users WHERE email = ?",
            [email],
        ).fetchone()

        if not row or row["password"] is None:
            return "not_found"

        token = secrets.token_urlsafe(32)
        expires = time.time() + config.PASSWORD_RESET_TTL_SECONDS
        conn.execute(
            "UPDATE users SET password_reset_token = ?, password_reset_token_expires = ? WHERE id = ?",
            [token, expires, row["id"]],
        )
        conn.commit()

        if background:
            threading.Thread(
                target=mailer.send_password_reset_email,
                args=(email, row["username"], token),
                daemon=True,
            ).start()
        else:
            mailer.send_password_reset_email(email, row["username"], token)

        return "sent"
    finally:
        conn.close()
def validate_token(token: str) -> dict:
    """Validate a password reset token without consuming it."""
    if not token:
        return {"status": "invalid"}

    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, password_reset_token_expires
            FROM users
            WHERE password_reset_token = ?
            """,
            [token],
        ).fetchone()

        if not row:
            return {"status": "invalid"}

        expires = row["password_reset_token_expires"]

        if expires is None or time.time() > float(expires):
            conn.execute(
                """
                UPDATE users
                SET password_reset_token = NULL,
                    password_reset_token_expires = NULL
                WHERE id = ?
                """,
                [row["id"]],
            )
            conn.commit()

            return {"status": "expired"}

        return {"status": "ok"}

    except Exception:
        logger.exception("validate_token failed")
        return {"status": "invalid"}

    finally:
        conn.close()
def reset_password_with_token(token: str, new_password: str) -> dict:
    """Consume a reset token and set a new password.

    Returns a dict with "status" and "user" keys:
    - "ok": token matched, was unexpired, and new_password satisfied
      password_meets_policy(). The row's password is set to the bcrypt hash;
      BOTH reset-token columns are cleared (single-use consumption); AND the
      account lockout counters (failed_login_attempts / locked_until) are
      cleared in the SAME UPDATE statement (a successful reset implies proven
      account control, so any lockout is lifted). `user` carries
      {"id", "username", "email"}.
    - "invalid": no row has this token (never issued, already consumed, or
      malformed/empty input). No state changes.
    - "expired": a row matches but time.time() > password_reset_token_expires.
      The token is cleared. No password change. No lockout clear. `user` is None.
    - "weak_password": the token is valid but new_password fails
      password_meets_policy(). NO state changes (token is left intact so the
      user can immediately retry with a stronger password instead of having to
      re-request and wait for another email). `user` is None.

    The four UPDATE variants below ensure that on success, the password, token,
    and lockout state are all updated atomically (single statement). Failures
    (invalid/expired/weak) touch no state or only clear the token (expired case).
    """
    if not token:
        return {"status": "invalid", "user": None}

    conn = get_db()
    try:
        # FIXED: SQL Injection closed -- parameterized SELECT by token.
        row = conn.execute(
            "SELECT id, username, email, password_reset_token_expires FROM users WHERE password_reset_token = ?",
            [token],
        ).fetchone()

        if not row:
            return {"status": "invalid", "user": None}

        # Check expiry.
        expires = row["password_reset_token_expires"]
        if expires is None or time.time() > float(expires):
            # Clear the expired token so it cannot be retried.
            conn.execute(
                "UPDATE users SET password_reset_token = NULL, password_reset_token_expires = NULL WHERE id = ?",
                [row["id"]],
            )
            conn.commit()
            return {"status": "expired", "user": None}

        # Validate the new password against the five-criteria strength policy.
        # (Same policy signup advertises, and change-password enforces.)
        if not security.password_meets_policy(new_password):
            # Token is left intact; user can retry immediately.
            return {"status": "weak_password", "user": None}

        # FIXED: Weak Password Storage closed -- hash the new password with
        # bcrypt before it touches the DB. The plaintext never persists.
        hashed = security.hash_password(new_password)

        # FIXED: SQL Injection closed -- parameterized UPDATE by id. Single
        # statement updates four columns: password (new hash), the two reset
        # tokens (cleared, single-use), and the lockout counters (cleared,
        # because a successful reset proves account control).
        conn.execute(
            "UPDATE users SET password = ?, password_reset_token = NULL, "
            "password_reset_token_expires = NULL, failed_login_attempts = 0, "
            "locked_until = NULL WHERE id = ?",
            [hashed, row["id"]],
        )
        conn.commit()

        return {
            "status": "ok",
            "user": {"id": row["id"], "username": row["username"], "email": row["email"]},
        }
    except Exception as exc:
        logger.exception(
            "reset_password_with_token failed for token=%s: %s",
            token[:8] + "...",
            exc,
        )
        return {"status": "invalid", "user": None}
    finally:
        conn.close()
