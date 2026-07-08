# Implementation Plan — Forgot / Reset Password

**Version:** 1.0.0
**Last Updated:** 2026-07-07
**Target Release Tag:** v2.1.0
**Parent Spec:** [forgot-password.md](./forgot-password.md)
**Foundation Spec:** [app-foundation.md](./app-foundation.md)
**Parent Documents:** [PRD.md](../../docs/PRD.md), [TDD.md](../../docs/TDD.md)

---

## 0. Plan Overview

This plan implements the feature specified in [forgot-password.md](./forgot-password.md): a self-service password-reset flow for local accounts that have forgotten their password. A user visits `/forgot-password`, enters their registered email, receives a 1-hour single-use reset link, clicks it to land on `/reset-password`, and sets a new password — which completes without writing a session, leaving them to log in fresh. The work is split into **twelve phases** so the change is small, individually verifiable, and easy to revert.

The feature reuses every existing primitive and introduces **no new dependency, no new middleware, and no database-schema change beyond the sixth additive migration**:

- New routes live in the existing `auth.py`; the router auto-discovers them, so `main.py` is untouched.
- The password-reset logic is a new `password_reset_service.py`, using **parameterized** SQL (VULN-1), **bcrypt** via the existing `core/security.py` helpers (VULN-5), and an env-tunable single-use token lifetime (matching the pattern of Email Verification v1.0.4).
- The two new POSTs (`/forgot-password` and `/reset-password`) inherit the existing per-IP **rate limiter** (VULN-7) and CSRF now matters only on reset POST. The token in the reset URL is the sole credential; it is never reflected without a DB round-trip that validates it.
- Emailed reset links are sent via the existing stdlib-only `core/mailer.py` SendGrid transport, fail-safe (returns `False`, never raises).
- Successful reset clears the account lockout counters (v1.0.5 feature), mirroring the logic `login()` already applies on a correct password.
- **No `main.py`, `core/security.py`, `core/csrf.py`, `core/rate_limit.py`, `core/oauth.py`, `core/mailer.py` baseline—** those pipelines are untouched; this feature layers on top of them in the service and route layer.

### Phase Summary

| # | Phase | Files Touched | Goal |
|---|-------|--------------|------|
| 1 | Add reset-token config | `backend/app/core/config.py` | Password-reset TTL setting + docstring |
| 2 | Additive, idempotent migration | `backend/app/db/session.py` | Two new columns (`password_reset_token`, `password_reset_token_expires`); no grandfather `UPDATE` |
| 3 | Add password-reset service | `backend/app/services/password_reset_service.py` (new) | `request_reset()`, `validate_token()`, `reset_password_with_token()` — parameterized SQL, stdlib token generation, fail-safe send |
| 4 | Add mailer function | `backend/app/core/mailer.py` | `send_password_reset_email()` — fail-safe, escaped username + URL |
| 5 | Add four routes | `backend/app/api/routes/auth.py` | `GET /forgot-password`, `POST /forgot-password`, `GET /reset-password`, `POST /reset-password` |
| 6 | Create forgot-password template | `frontend/templates/forgot_password.html` (new) | "What is your email?" form + generic success message |
| 7 | Create reset-password template | `frontend/templates/reset_password.html` (new) | "Choose a new password" form + token hidden field + password match check |
| 8 | Add "Forgot password?" link | `frontend/templates/login.html` | One link to `/forgot-password` near the password field |
| 9 | Add CSS for new pages | `frontend/static/css/styles.css` | Form and message rules, theme-aware; reuse existing variables |
| 10 | Update env placeholders | `.env.example` | Commented `PASSWORD_RESET_TTL_SECONDS` placeholder (default shown) |
| 11 | Update documentation | `README.md`, `CLAUDE.md` | Feature table, API table, integration subsection, Important Rules, spec hierarchy |
| 12 | End-to-end verification | All files (read-only) | Walk every Verification Step in spec §10; audit all-vuln preservation |

### Files Modified / Created

**Exactly the files declared in spec §3:**

- **New** — `backend/app/services/password_reset_service.py`
- **New** — `frontend/templates/forgot_password.html`
- **New** — `frontend/templates/reset_password.html`
- **Modified** — `backend/app/core/config.py`
- **Modified** — `backend/app/core/mailer.py`
- **Modified** — `backend/app/db/session.py`
- **Modified** — `backend/app/api/routes/auth.py`
- **Modified** — `frontend/templates/login.html`
- **Modified** — `frontend/static/css/styles.css`
- **Modified** — `.env.example`
- **Modified** — `README.md`
- **Modified** — `CLAUDE.md`

No dependency change, so no `pyproject.toml` / `uv.lock` edit (and no `uv sync`).

### Files That MUST NOT Be Modified

- `backend/app/main.py` — middleware wiring / `SECRET_KEY` / port (VULN-4 / VULN-7 / VULN-8). Routes are auto-included via the existing `include_router(router)`.
- `backend/app/core/rate_limit.py` — rate-limit middleware (VULN-7); the two new POSTs are throttled automatically.
- `backend/app/core/csrf.py` — CSRF middleware (VULN-8); CSRF applies to `POST /reset-password`, not the unauthenticated request and GET endpoints.
- `backend/app/core/security.py` — bcrypt (VULN-5); `password_reset_service.py` **calls** `hash_password()` and `password_meets_policy()`.
- `backend/app/core/oauth.py`, `backend/app/services/oauth_service.py`, `backend/app/core/qr_login.py`, `backend/app/core/captcha.py` — unrelated; Google accounts are deliberately skipped.
- `backend/app/services/auth_service.py` — `login()`, `signup()`, `change_password()` byte-for-byte unchanged.
- `backend/app/services/lockout_service.py`, `backend/app/services/verification_service.py`, `backend/app/services/otp_service.py`, `backend/app/services/totp_service.py` — unchanged; `password_reset_service.py` clears lockout columns directly in its own UPDATE, not by calling `lockout_service.reset()`.
- `frontend/templates/login.html` — only one additive link added; no fetch handler, no redirect logic, no form changes.
- `frontend/templates/signup.html`, `frontend/templates/dashboard.html`, `frontend/templates/profile.html`, and all other templates except login.html — **fully** untouched.
- `pyproject.toml`, `backend/pyproject.toml`, `uv.lock` — no dependency change.

### Vulnerability-Preservation Checklist (Carry Through Every Phase)

After every phase, re-confirm:

1. **SQL Injection (VULN-1).** New `password_reset_service.py` uses parameterized `SELECT`/`UPDATE` with `?` placeholders everywhere.
2. **Stored XSS (VULN-2).** The reset email `html.escape(..., quote=True)`'s both the username and reset URL; the reset-password template splices only an already-validated token value, never raw user input.
3. **Reflected XSS (VULN-3).** The token is **never** echoed back from the query string; `GET /reset-password` validates it server-side first, then only splices the validated value into the form's hidden field. All error messages are fixed, server-controlled strings.
4. **Session Hijacking (VULN-4).** `main.py` `SECRET_KEY` sourcing untouched; `PASSWORD_RESET_TTL_SECONDS` comes from env with a non-secret default; no session is written by this feature.
5. **Weak Password (VULN-5).** `core/security.py` untouched; new password goes through `hash_password()` (bcrypt) **and** `password_meets_policy()` before storage.
6. **Exposed Database (VULN-6).** No `/download/db` route added or modified.
7. **No Rate Limiting (VULN-7).** `RateLimitMiddleware` registration untouched; both new POSTs are throttled automatically.
8. **CSRF (VULN-8).** `POST /reset-password` carries a hidden `csrf_token` in a simple form. `GET /forgot-password`, `POST /forgot-password`, and `GET /reset-password` do not need CSRF (an unauthenticated feature by design; the token in the URL is the capability).

---

## Step 0 — Preconditions

- Confirm branch `feature/forgot-password` is checked out.
- Confirm `secrets`, `time`, `threading`, `logging` are stdlib (no dependency change).
- No edits to `main.py`, `core/rate_limit.py`, `core/security.py`, `core/csrf.py`, `core/oauth.py`, `auth_service.py`, `signup.html`, `dashboard.html`, `profile.html`, or any lockfile at any point.

---

## Step 1 — `backend/app/core/config.py` (password-reset settings)

Append a new block below the account-lockout block:

```python
# --- Password-Reset settings (env-tunable, non-secret) -----------------------
# When a user requests a password reset, a single-use, time-limited token
# (secrets.token_urlsafe(32)) is issued and emailed. The token must be validated
# and consumed within this window (default 1 hour). This is NOT a secret; it has
# a safe default and can be lowered for demos, e.g. PASSWORD_RESET_TTL_SECONDS=60.
PASSWORD_RESET_TTL_SECONDS = int(os.environ.get("PASSWORD_RESET_TTL_SECONDS", "3600"))
```

Update the module docstring's opening line to mention password reset alongside Google + email verification + account lockout + TOTP + QR login + CAPTCHA. No behaviour change to existing settings.

**Check:** `python -c "from app.core import config; print(config.PASSWORD_RESET_TTL_SECONDS)"` → `3600`.

---

## Step 2 — `backend/app/db/session.py` (additive migration, 2 columns)

In `CREATE TABLE IF NOT EXISTS users (...)` add the two columns (after the OTP/TOTP columns):

```
password_reset_token      TEXT,
password_reset_token_expires REAL
```

In the `migrations` dict, add the two entries (no grandfather step — defaults are already correct):

```python
migrations = {
    # ... existing columns ...
    # Forgot / Reset Password feature (v2.1.0): two columns, both nullable.
    # Defaults (NULL / NULL) already mean "no reset outstanding", so NO
    # grandfather UPDATE is needed.
    "password_reset_token": "ALTER TABLE users ADD COLUMN password_reset_token TEXT",
    "password_reset_token_expires": "ALTER TABLE users ADD COLUMN password_reset_token_expires REAL",
}
```

Update the `init_db()` docstring's schema notes for the two new columns (mirroring the `is_verified` / `failed_login_attempts` / `otp_*` notes).

**Check:** `rm vulnerable_app.db`, boot, `PRAGMA table_info(users)` shows both columns; on an old DB copy, existing rows read `NULL` / `NULL` (no outstanding reset).

---

## Step 3 — `backend/app/services/password_reset_service.py` (new)

Stdlib-only module importable by the route layer (imports `secrets`, `time`, `logging`, `core.config`, `core.security`, `core.mailer`, `db.session` — no circular dependency; does **not** import `lockout_service`, because it updates lockout columns directly).

```python
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


def request_reset(email: str, background: bool = True) -> None:
    """Request a password reset for the given email.

    If a row in users matches the email AND has a non-NULL password (not a
    Google-only account), issue a fresh single-use token, store it + its
    expiry, and send a reset email. If no row or the row is Google-only
    (password IS NULL), this function does NOTHING and returns silently.

    Return value is always None; the route layer handles returning the generic
    "check your email" message in every case.

    background=True (on login path): send email on a daemon thread, return
    immediately so the POST doesn't block (consistent with other daemon-send
    patterns in signup verification). background=False (on resend path, when
    added in future): synchronous send, returning mailer's boolean. Callers
    only use background=True in this slice.
    """
    if not email:
        return

    conn = get_db()
    try:
        # FIXED: SQL Injection closed -- parameterized SELECT by email.
        # Note: email is NOT UNIQUE in the schema (see CLAUDE.md EC-09), so
        # fetchone() returns the first (arbitrary) matching row if there are
        # duplicates. This is correct: a user with duplicate emails cannot
        # reset (degenerate case); the happy path is unique emails per user.
        row = conn.execute(
            "SELECT id, username, password FROM users WHERE email = ?",
            [email],
        ).fetchone()

        # Invariant 1: no row means no account with that email; silently skip.
        # Invariant 2: row exists but password IS NULL means a Google-only
        # account (no local password to reset); silently skip. The route layer
        # can't distinguish the two cases from the outside (per enumeration
        # resistance), and neither can the user (intentional product choice—
        # they must use Google login or call support to add a local password).
        if not row or row["password"] is None:
            return

        # Issue a fresh token: 256-bit URL-safe Base64 (43 chars), like the
        # verification-token pattern (v1.0.4). This will overwrite any prior
        # token (only the latest reset link works); expired tokens are cleared
        # on first validation or consumption.
        token = secrets.token_urlsafe(32)
        expires = time.time() + config.PASSWORD_RESET_TTL_SECONDS

        # FIXED: SQL Injection closed -- parameterized UPDATE by id.
        conn.execute(
            "UPDATE users SET password_reset_token = ?, password_reset_token_expires = ? WHERE id = ?",
            [token, expires, row["id"]],
        )
        conn.commit()

        # Send the reset email on a thread (if background=True) or synchronously
        # (if False). The mailer is fail-safe (returns False, never raises); a
        # failed send does NOT change the row state (token stays live, user can
        # request another reset or click the link again later if the send does
        # arrive). The route layer returns the same 200 response either way.
        if background:
            threading.Thread(
                target=mailer.send_password_reset_email,
                args=(email, row["username"], token),
                daemon=True,
            ).start()
        else:
            mailer.send_password_reset_email(email, row["username"], token)
    finally:
        conn.close()


def validate_token(token: str) -> dict:
    """Check if a reset token is valid, unexpired, and exists.

    Returns a dict with a "status" key:
    - "ok": the token exists and has not expired. The token is NOT consumed.
    - "invalid": no row holds this token (never issued, already consumed, or
      malformed/empty input). No state changes.
    - "expired": the token exists but time.time() > password_reset_token_expires.
      On an expired token, the token columns are immediately cleared so a stale
      link cannot be used to find/validate against later.

    This read-only check is used by GET /reset-password to decide whether to
    render a "set a new password" form (ok) or a "this link is invalid or has
    expired" message (invalid/expired). Calling this function is NOT destructive
    — it does not consume the token on a mere page load. The token is consumed
    only by reset_password_with_token().
    """
    if not token:
        return {"status": "invalid"}

    conn = get_db()
    try:
        # FIXED: SQL Injection closed -- parameterized SELECT by token.
        row = conn.execute(
            "SELECT id, password_reset_token_expires FROM users WHERE password_reset_token = ?",
            [token],
        ).fetchone()

        if not row:
            return {"status": "invalid"}

        # Check expiry. An expired token is immediately cleared so it cannot
        # be retried / scanned by bots later.
        expires = row["password_reset_token_expires"]
        if expires is None or time.time() > float(expires):
            conn.execute(
                "UPDATE users SET password_reset_token = NULL, password_reset_token_expires = NULL WHERE id = ?",
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
    except Exception:
        logger.exception("reset_password_with_token failed")
        return {"status": "invalid", "user": None}
    finally:
        conn.close()
```

**Check:** module imports cleanly; all SQL uses `?` placeholders; the four response states match the spec (FR-04); no hashing or policy logic is reimplemented (both are imported from `core.security`).

---

## Step 4 — `backend/app/core/mailer.py` (add `send_password_reset_email`)

Add a third public function after `send_verification_email` and `send_otp_email`, reusing the same STARTTLS/implicit-TLS structure and fail-safe contract:

```python
def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    """Send a password-reset link. Returns True on success, else False.

    Same fail-safe contract as send_verification_email and send_otp_email --
    never raises; every failure path returns False so the reset flow stays
    robust. The token is embedded in the reset URL; the username is escaped
    before entering the HTML part (VULN-2 posture, matching other emails).
    """
    if not config.is_email_configured():
        logger.warning("SMTP not configured; skipping password-reset email to %s", to_email)
        return False

    safe_username = html.escape(username or "", quote=True)
    reset_url = f"{config.APP_BASE_URL}/reset-password?token={token}"
    safe_url = html.escape(reset_url, quote=True)

    msg = EmailMessage()
    msg["Subject"] = "Reset your password - Security Vulnerability Lab"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg.set_content(
        f"Hi {username},\n\n"
        "We received a request to reset your password. If you didn't make this "
        "request, you can ignore this email.\n\n"
        "To reset your password, click the link below (valid 1 hour):\n"
        f"{reset_url}\n\n"
        "If the link doesn't work, copy and paste it into your browser.\n"
    )
    msg.add_alternative(
        f"<p>Hi {safe_username},</p>"
        "<p>We received a request to reset your password. If you didn't make "
        "this request, you can ignore this email.</p>"
        "<p>To reset your password, click the link below (valid 1 hour):</p>"
        f'<p><a href="{safe_url}">Reset your password</a></p>'
        "<p>If the link doesn't work, copy and paste it into your browser.</p>",
        subtype="html",
    )

    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT) as server:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT) as server:
                server.starttls()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.send_message(msg)
        logger.info("Password-reset email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send password-reset email to %s", to_email)
        return False
```

> **Note:** the token is embedded in the URL (`reset_url`) and both the username and full URL are `html.escape`-d before entering the HTML part (VULN-2 / VULN-3 posture). The token is logged **only** as part of "email sent" (no raw token logging — VULN-3).

**Check:** `send_password_reset_email` returns `False` (logged) when SMTP is unset; never raises; token + URL are escaped.

---

## Step 5 — `backend/app/api/routes/auth.py` (four new routes)

Add the four handlers after `logout` (grouping them with other auth routes):

```python
@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    """Render the forgot-password request form.

    Unauthenticated, no session gate. Generates a fresh CSRF token for the
    form, which will be validated on the subsequent POST submission.
    """
    token = get_or_create_csrf_token(request)
    with open(os.path.join(TEMPLATE_DIR, "forgot_password.html"), "r") as f:
        page = f.read()
    page = page.replace("{{csrf_token}}", html.escape(token, quote=True))
    return HTMLResponse(content=page)


@router.post("/forgot-password")
async def forgot_password_post(
    request: Request,
    email: str = Form(""),
):
    """Handle a forgot-password request.

    Reads the submitted email and calls password_reset_service.request_reset()
    to issue a token if the account exists, is local (not Google-only), etc.
    Returns the SAME generic 200 message regardless of whether a token was
    issued, so an attacker cannot enumerate accounts or provider types.

    This is the enumeration-resistance contract: the route ensures every outcome
    (success, no-such-email, Google-only account, SMTP failure) results in the
    identical response to the client. The service itself is silent; the route
    guarantees the external posture.
    """
    password_reset_service.request_reset(email, background=True)
    # Always return the same message, regardless of outcome. The user must
    # check their email to know if a reset was actually sent.
    return JSONResponse(
        {
            "success": True,
            "message": "If that email is registered, we've sent a password reset link. It will expire in 1 hour.",
        }
    )


@router.get("/reset-password")
async def reset_password_page(request: Request):
    """Render the reset-password form, validating the token first.

    Unauthenticated. Reads token from query param and calls
    password_reset_service.validate_token() to determine if the link is valid.
    On success (ok), renders the "choose a new password" form with the token
    spliced into a hidden field (already validated, not raw query param).
    On failure (invalid/expired/missing token), renders a fixed generic message
    with a link back to /forgot-password.

    The read-only validate_token() call means page refreshes and multiple tabs
    do not consume/invalidate the link; only a successful POST reset does.
    """
    token = request.query_params.get("token", "")
    result = password_reset_service.validate_token(token)

    if result["status"] == "ok":
        # Render the form with the already-validated token spliced in.
        with open(os.path.join(TEMPLATE_DIR, "reset_password.html"), "r") as f:
            page = f.read()
        csrf_token = get_or_create_csrf_token(request)
        page = page.replace("{{csrf_token}}", html.escape(csrf_token, quote=True))
        page = page.replace("{{token}}", html.escape(token, quote=True))
        return HTMLResponse(content=page)
    else:
        # Token is invalid or expired. Render a fixed message (no raw token
        # echoed) with a link back to /forgot-password so the user can
        # request a new reset if needed.
        error_msg = (
            "This link is invalid or has expired. "
            '<a href="/forgot-password">Request a new reset link</a>.'
        )
        html_response = (
            "<html><head><title>Reset Password</title>"
            "<link rel='stylesheet' href='/static/css/styles.css'></head>"
            "<body class='auth-body'><div class='auth-container'>"
            "<div class='auth-card'><h2>Reset Password</h2>"
            f"<p>{error_msg}</p>"
            "</div></div></body></html>"
        )
        return HTMLResponse(content=html_response)


@router.post("/reset-password")
async def reset_password_post(
    request: Request,
    token: str = Form(""),
    new_password: str = Form(""),
):
    """Handle a reset-password submission.

    Reads the token and new_password from the form and calls
    password_reset_service.reset_password_with_token(). Returns JSON for every
    outcome so the page's fetch handler can render feedback inline.

    The CSRF token and per-IP rate limit are enforced by middleware before
    this handler runs; FastAPI's Form() ignores the extra csrf_token field.
    """
    result = password_reset_service.reset_password_with_token(token, new_password)

    if result["status"] == "ok":
        return JSONResponse(
            {
                "success": True,
                "message": "Password reset successfully. You can now log in with your new password.",
                "redirect": "/login",
            }
        )
    elif result["status"] == "weak_password":
        return JSONResponse(
            {
                "error": (
                    "New password must be at least 8 characters and include an "
                    "uppercase letter, a lowercase letter, a digit, and a special character"
                )
            },
            status_code=400,
        )
    else:
        # "invalid" or "expired"
        return JSONResponse(
            {"error": "Reset link is invalid or has expired. Please request a new one."},
            status_code=400,
        )
```

**Also add the import at the top of the file:**

```python
from app.services import password_reset_service
```

(The file already imports `auth_service`, `verification_service`, `otp_service`, `totp_service`, `oauth_service`, so adding one more service import follows the established pattern.)

**Check:** all greps and smoke tests pass; the two new POSTs are `POST /forgot-password`, `POST /reset-password`; the two new GETs are `GET /forgot-password`, `GET /reset-password`.

---

## Step 6 — Create `frontend/templates/forgot_password.html`

Create the file with exactly this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script>
        (function () {
            try {
                var saved = localStorage.getItem('theme');
                if (saved !== 'light' && saved !== 'dark') {
                    saved = null;
                }
                var theme = saved;
                if (!theme && window.matchMedia) {
                    theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
                }
                if (!theme) {
                    theme = 'light';
                }
                document.documentElement.setAttribute('data-theme', theme);
            } catch (e) {
                document.documentElement.setAttribute('data-theme', 'light');
            }
        })();
    </script>
    <title>Forgot Password - Security Vulnerability Lab</title>
    <link rel="stylesheet" href="/static/css/styles.css">
</head>
<body class="auth-body">
    <!-- Shared Header -->
    <header class="header">
        <div class="header-title">Security Vulnerability Lab</div>
        <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Switch to dark mode">
            <span class="theme-toggle-icon" aria-hidden="true">🌙</span>
        </button>
        <div class="header-logos">
            <img src="/static/images/PUCIT_Logo.png" alt="PUCIT" class="header-logo">
            <img src="/static/images/excaliat-logo.png" alt="Excaliat" class="header-logo">
            <img src="/static/images/blue-logo-scl2.png" alt="FCCU" class="header-logo">
        </div>
    </header>

    <!-- Auth Container -->
    <div class="auth-container">
        <div class="auth-card">
            <h2 class="auth-title">Reset Your Password</h2>
            <p class="auth-subtitle">Enter your email address and we'll send you a link to reset your password.</p>

            <form id="forgot-password-form">
                <input type="hidden" name="csrf_token" value="{{csrf_token}}">

                <div class="form-group">
                    <label class="form-label" for="email">Email Address</label>
                    <input type="email" id="email" name="email" class="form-input" placeholder="your@example.com" required>
                </div>

                <div id="forgot-message" class="form-message" role="status" aria-live="polite" style="display: none;"></div>

                <button type="submit" class="btn btn-primary btn-block">Send Reset Link</button>

                <div class="auth-footer">
                    <a href="/login" class="auth-link">Back to Login</a>
                </div>
            </form>
        </div>
    </div>

    <script>
        const form = document.getElementById('forgot-password-form');
        const msg = document.getElementById('forgot-message');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            // Send as application/x-www-form-urlencoded. The CSRF middleware
            // only parses urlencoded bodies, so wrapping FormData in
            // URLSearchParams ensures the correct Content-Type.
            const body = new URLSearchParams(new FormData(form));
            try {
                const response = await fetch('/forgot-password', { method: 'POST', body: body });
                const data = await response.json();
                if (data.success) {
                    msg.textContent = data.message;
                    msg.classList.remove('is-error');
                    msg.classList.add('is-success');
                    msg.style.display = 'block';
                    form.reset();
                    form.style.display = 'none';
                } else {
                    msg.textContent = data.error || 'Something went wrong.';
                    msg.classList.remove('is-success');
                    msg.classList.add('is-error');
                    msg.style.display = 'block';
                }
            } catch (err) {
                msg.textContent = 'Network error. Please try again.';
                msg.classList.remove('is-success');
                msg.classList.add('is-error');
                msg.style.display = 'block';
            }
        });
    </script>

    <script>
        (function () {
            var toggle = document.getElementById('theme-toggle');
            if (!toggle) return;

            function reflect(theme) {
                var nextAction = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
                var icon = theme === 'dark' ? '☀' : '🌙';
                toggle.setAttribute('aria-label', nextAction);
                var iconEl = toggle.querySelector('.theme-toggle-icon');
                if (iconEl) iconEl.textContent = icon;
            }

            reflect(document.documentElement.getAttribute('data-theme') || 'light');

            toggle.addEventListener('click', function () {
                var current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
                var next = current === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', next);
                try {
                    localStorage.setItem('theme', next);
                } catch (e) {
                    /* persistence unavailable — in-page state still flips */
                }
                reflect(next);
            });
        })();
    </script>
</body>
</html>
```

**Check:** the form submits via `fetch()` + `URLSearchParams`; the CSRF token is a hidden first child; the message div renders success/error inline; the form hides on success.

---

## Step 7 — Create `frontend/templates/reset_password.html`

Create the file with exactly this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script>
        (function () {
            try {
                var saved = localStorage.getItem('theme');
                if (saved !== 'light' && saved !== 'dark') {
                    saved = null;
                }
                var theme = saved;
                if (!theme && window.matchMedia) {
                    theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
                }
                if (!theme) {
                    theme = 'light';
                }
                document.documentElement.setAttribute('data-theme', theme);
            } catch (e) {
                document.documentElement.setAttribute('data-theme', 'light');
            }
        })();
    </script>
    <title>Reset Password - Security Vulnerability Lab</title>
    <link rel="stylesheet" href="/static/css/styles.css">
</head>
<body class="auth-body">
    <!-- Shared Header -->
    <header class="header">
        <div class="header-title">Security Vulnerability Lab</div>
        <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Switch to dark mode">
            <span class="theme-toggle-icon" aria-hidden="true">🌙</span>
        </button>
        <div class="header-logos">
            <img src="/static/images/PUCIT_Logo.png" alt="PUCIT" class="header-logo">
            <img src="/static/images/excaliat-logo.png" alt="Excaliat" class="header-logo">
            <img src="/static/images/blue-logo-scl2.png" alt="FCCU" class="header-logo">
        </div>
    </header>

    <!-- Auth Container -->
    <div class="auth-container">
        <div class="auth-card">
            <h2 class="auth-title">Choose a New Password</h2>
            <p class="auth-subtitle">Enter a strong password to regain access to your account.</p>

            <form id="reset-password-form">
                <input type="hidden" name="csrf_token" value="{{csrf_token}}">
                <input type="hidden" name="token" value="{{token}}">

                <div class="form-group">
                    <label class="form-label" for="new_password">New Password</label>
                    <input type="password" id="new_password" name="new_password" class="form-input" placeholder="Enter a strong password" required>
                </div>

                <div class="form-group">
                    <label class="form-label" for="confirm_password">Confirm Password</label>
                    <input type="password" id="confirm_password" class="form-input" placeholder="Re-enter your password" required>
                </div>

                <div id="reset-message" class="form-message" role="status" aria-live="polite" style="display: none;"></div>

                <button type="submit" class="btn btn-primary btn-block">Reset Password</button>

                <div class="auth-footer">
                    <a href="/login" class="auth-link">Back to Login</a>
                </div>
            </form>
        </div>
    </div>

    <script>
        const form = document.getElementById('reset-password-form');
        const msg = document.getElementById('reset-message');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const newPw = document.getElementById('new_password').value;
            const confirmPw = document.getElementById('confirm_password').value;

            // Client-side password match check (before sending to server).
            if (newPw !== confirmPw) {
                msg.textContent = 'Passwords do not match.';
                msg.classList.remove('is-success');
                msg.classList.add('is-error');
                msg.style.display = 'block';
                return;
            }

            // Send as application/x-www-form-urlencoded.
            const body = new URLSearchParams(new FormData(form));
            try {
                const response = await fetch('/reset-password', { method: 'POST', body: body });
                const data = await response.json();
                if (data.success) {
                    msg.textContent = data.message;
                    msg.classList.remove('is-error');
                    msg.classList.add('is-success');
                    msg.style.display = 'block';
                    form.style.display = 'none';
                    // Redirect after a brief delay so the user sees the success message.
                    setTimeout(() => {
                        window.location.href = data.redirect || '/login';
                    }, 2000);
                } else {
                    msg.textContent = data.error || 'Could not reset password.';
                    msg.classList.remove('is-success');
                    msg.classList.add('is-error');
                    msg.style.display = 'block';
                }
            } catch (err) {
                msg.textContent = 'Network error. Please try again.';
                msg.classList.remove('is-success');
                msg.classList.add('is-error');
                msg.style.display = 'block';
            }
        });
    </script>

    <script>
        (function () {
            var toggle = document.getElementById('theme-toggle');
            if (!toggle) return;

            function reflect(theme) {
                var nextAction = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
                var icon = theme === 'dark' ? '☀' : '🌙';
                toggle.setAttribute('aria-label', nextAction);
                var iconEl = toggle.querySelector('.theme-toggle-icon');
                if (iconEl) iconEl.textContent = icon;
            }

            reflect(document.documentElement.getAttribute('data-theme') || 'light');

            toggle.addEventListener('click', function () {
                var current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
                var next = current === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', next);
                try {
                    localStorage.setItem('theme', next);
                } catch (e) {
                    /* persistence unavailable — in-page state still flips */
                }
                reflect(next);
            });
        })();
    </script>
</body>
</html>
```

**Check:** the form has two hidden fields (CSRF + token); `token` is server-spliced (already validated by `GET /reset-password`, never raw query param); the `confirm_password` field has no `name` attribute; password match is checked client-side; on success the form hides and redirect happens after 2 seconds.

---

## Step 8 — Add "Forgot Password?" Link to `frontend/templates/login.html`

**Before** (find the password input group, ~L84–L88):

```html
                <div class="form-group">
                    <label class="form-label" for="password">Password</label>
                    <input type="password" id="password" name="password" class="form-input" placeholder="Your password" required>
                </div>
```

**After**:

```html
                <div class="form-group">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label" for="password">Password</label>
                        <a href="/forgot-password" class="form-link" style="font-size: 0.85rem; margin-top: 4px;">Forgot password?</a>
                    </div>
                    <input type="password" id="password" name="password" class="form-input" placeholder="Your password" required>
                </div>
```

(The `<div>` wraps the label and the new link in a flex row; the link is right-aligned and styled small. Alternatively, a simpler single-line inline style `margin-left: auto;` on the link alone would also work.)

**Check:** the "Forgot password?" link appears next to the Password label on the login page and points to `/forgot-password`.

---

## Step 9 — Append CSS to `frontend/static/css/styles.css`

Append this block at the end of the file:

```css
/* ===================== Forgot / Reset Password Pages (v2.1.0) ===================== */

.form-message {
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
    font-size: 0.9rem;
    display: none;
}

.form-message.is-error {
    background: var(--error-bg, #fee2e2);
    border: 1px solid var(--error-border, #fecaca);
    color: var(--error-text, #991b1b);
}

.form-message.is-success {
    background: var(--success-bg, #dcfce7);
    border: 1px solid var(--success-border, #86efac);
    color: var(--success-text, #166534);
}

.form-link {
    color: var(--link-color, #3b82f6);
    text-decoration: none;
    cursor: pointer;
}

.form-link:hover {
    text-decoration: underline;
}

.btn-block {
    width: 100%;
}

.auth-footer {
    text-align: center;
    margin-top: 16px;
}

.auth-link {
    color: var(--link-color, #3b82f6);
    text-decoration: none;
    font-size: 0.9rem;
}

.auth-link:hover {
    text-decoration: underline;
}
```

> **Note:** the exact variable names (`--error-bg`, `--error-border`, `--error-text`, `--link-color`, `--success-bg`, `--success-border`, `--success-text`) MUST match what the file already defines. If the file uses different CSS-custom-property names, substitute the real ones. The inline fallbacks (hex literals as second arguments to `var()`) are a safety net but the theme-aware variables are preferred. Read the existing `:root` and `[data-theme="dark"]` blocks first and mirror their naming.

**Check:** the new CSS rules compile without errors; success/error messages render with the correct theme colors in both light and dark modes.

---

## Step 10 — Update `.env.example` (reset-token TTL setting)

Append this block:

```bash
# --- Forgot / Reset Password (v2.1.0) — password-reset token lifetime --------
# When a user requests a password reset, an email with a single-use link is sent.
# This TTL controls how long the link remains valid (default 1 hour = 3600 seconds).
# This is NOT a secret; it has a safe default and can be lowered for demos,
# e.g. PASSWORD_RESET_TTL_SECONDS=60.
PASSWORD_RESET_TTL_SECONDS=3600
```

**Check:** the placeholder is documented and the default value is shown.

---

## Step 11 — Update `README.md` and `CLAUDE.md`

### 11.1 README.md Edits

**Edit A — Feature Enhancements table:**

In the Feature Enhancements table, add a new row (after the CAPTCHA row if present, or at the end):

```
| 9 | Forgot / Reset Password | Self-service password reset for local accounts. Unauthenticated `/forgot-password` form sends an email with a single-use, 1-hour reset link; clicking the link lands on `/reset-password` where the user enters a new password (strength-policy enforced, bcrypt-hashed). No session written on reset; user logs in fresh with the new password. Rate-limited per-IP; CSRF-protected on reset POST. | **Done (v2.1.0)** |
```

Also update the summary row above the table (the one that says "X of Y completed"):

```
**Feature Enhancements:** 9 out of 10 complete (CAPTCHA + Password Reset done; Multi-Device Access planned).
```

**Edit B — Releases & Versions table:**

Add a new row for v2.1.0 (after the v2.0.0 row):

```
| **v2.1.0** | Students who want the reference **plus forgot/reset password** | Everything in v2.0.0 plus **Forgot / Reset Password**: unauthenticated self-service flow for lost passwords (email + 1-hour single-use token + bcrypt). No schema change from v2.0.0 (sixth migration adds two columns). Stdlib-only; no new dependency. |
```

**Edit C — API Endpoints table:**

Add four new rows:

```
| GET | `/forgot-password` | Forgot-password page (email request form) | No |
| POST | `/forgot-password` | Submit email for password-reset link | No |
| GET | `/reset-password?token=...` | Reset-password page (validated link only) | No |
| POST | `/reset-password` | Submit new password + reset token | No |
```

### 11.2 CLAUDE.md Edits

**Edit A — Frontend-Backend Integration:**

Add a new bullet under the Frontend-Backend Integration section:

```
- **Forgot / Reset Password (shipped in v2.1.0):** `GET /forgot-password` renders `forgot_password.html` with a spliced CSRF token; `POST /forgot-password` reads the email and calls `password_reset_service.request_reset()`, returning the same generic `200` message whether an email was sent, the account doesn't exist, is Google-only, or SMTP failed (enumeration resistance). A single-use `secrets.token_urlsafe(32)` token (256 bits, 1-hour lifetime, env-tunable) is issued and emailed. `GET /reset-password?token=...` validates the token server-side before rendering `reset_password.html` with the token spliced into a hidden field (never reflected raw from the query string — VULN-3 posture). `POST /reset-password` consumes the token, validates the new password against the five-criteria strength policy (enforced server-side), bcrypt-hashes it with `core.security.hash_password()`, and **clears the per-account lockout counters in the same UPDATE statement** (a successful reset proves account control). All SQL is parameterized (VULN-1); the token and reset URL are `html.escape(..., quote=True)`-d before emailing (VULN-2/VULN-3); both new POSTs are rate-limited by the existing middleware (VULN-7) and `POST /reset-password` carries the hidden `csrf_token` (VULN-8). The new service stays **stdlib-only** (`secrets`, `time`, `threading`, `logging`); no new dependency.
```

**Edit B — Important Rules:**

Add an entry pinning the invariants:

```
- The Forgot / Reset Password feature (`password_reset_service.py`, the four routes, the two templates) must keep all SQL **parameterized** (VULN-1) and must **never reflect or log the reset token** — `GET /reset-password` validates it server-side first, and only the already-validated value is spliced into the hidden form field (VULN-3 posture, matching the verification-token pattern); both new POSTs return fixed, server-controlled JSON messages. The token stays a single-use, expiring `secrets.token_urlsafe(32)`; a successful reset MUST clear **both** `password_reset_token` and `password_reset_token_expires`, and MUST also clear the lockout counters (`failed_login_attempts` and `locked_until`) in the same statement. Email delivery reuses the existing `is_email_configured()` gate (both new POSTs require SMTP to be configured; a configured-but-failing SMTP returns the same generic `200`/no-change posture). All SMTP credentials come **only** from env/`.env` via `core/config.py` — never hardcode them, keep `.env` git-ignored and `.env.example` placeholder-only (VULN-4). `password_reset_service.py` must reuse `core.security.password_meets_policy()` (never reimplement); the new password MUST be `html.escape(..., quote=True)`-d only in emails, not before `hash_password()`. Both new POSTs inherit the existing CSRF + rate-limit middleware (VULN-7/VULN-8); the feature does **not** add or modify any middleware. Do **not** modify `main.py`, `db/session.py`, `auth_service.py`, `core/security.py`, `core/csrf.py`, `core/rate_limit.py`, `core/oauth.py`, or any other service; the forgot/reset flow is a standalone new entrypoint.
```

**Edit C — Specification Hierarchy:**

Append:

```
21. `.claude/specs/forgot-password.md` + `.claude/specs/forgot-password-plan.md` — Forgot / Reset Password (v2.1.0 feature)
```

**Check:** all edits are present; the feature count is updated; the spec hierarchy entry is in the right position.

---

## Step 12 — End-to-End Verification + Vulnerability-Preservation Audit

Walk every Verification Step in spec §10 in order. **No edits** are made; if a step fails, return to the relevant earlier phase.

### 12.1 Boot + Register (spec §10.1)

```bash
rm -f vulnerable_app.db
uv run backend/app/main.py   # one terminal; run the curl steps in another
```

Then run spec §10.1's signup, expecting `signup=302`.

### 12.2 Unauthenticated Access (spec §10.2 — FR-01, FR-02, FR-03)

Expect `forgot_page=200` (shows the email form); `reset_unclaimed=400` or 404 (no valid token, shows error).

### 12.3 Generic Success Message (spec §10.3 — FR-03)

Request reset with an empty email, non-existent email, Google-only email, and a valid local email:

```bash
# All should return 200 with identical message
curl -s -X POST http://localhost:3001/forgot-password --data-urlencode 'email='
curl -s -X POST http://localhost:3001/forgot-password --data-urlencode 'email=notfound@example.com'
curl -s -X POST http://localhost:3001/forgot-password --data-urlencode 'email=alice@example.com'
```

Expected: all three return `200 {"success": true, "message": "...If that email is registered..."}`.

### 12.4 Token Validation (spec §10.4 — FR-04, FR-05)

Obtain a valid token (look at the SMTP debug log or DB directly), then:

```bash
curl -s 'http://localhost:3001/reset-password?token=VALID_TOKEN_HERE'
```

Expected: `200` with the reset form shown (token is in a hidden field, inputs are visible).

```bash
curl -s 'http://localhost:3001/reset-password?token=INVALID_TOKEN'
```

Expected: `200` with a "this link is invalid or has expired" message (no form).

### 12.5 Weak Password Rejection (spec §10.6 — FR-06)

With a valid token, submit a weak password (`short`):

```bash
curl -s -X POST http://localhost:3001/reset-password \
  --data-urlencode 'token=VALID_TOKEN' \
  --data-urlencode 'new_password=short' \
  --data-urlencode 'csrf_token=DUMMY'
```

Expected: `400 {"error": "...must be at least 8..."}`.

### 12.6 CSRF Enforced (spec §10.7 — FR-07)

Submit a reset with a valid token and password but no/wrong CSRF token:

```bash
curl -s -X POST http://localhost:3001/reset-password \
  --data-urlencode 'token=VALID_TOKEN' \
  --data-urlencode 'new_password=NewPass2!' \
  --data-urlencode 'csrf_token=WRONG'
```

Expected: `403` (CSRF middleware rejects before the handler runs).

### 12.7 Successful Reset + Re-Login (spec §10.8 — FR-08, FR-09)

With a valid token and CSRF, submit a strong password:

```bash
curl -s -X POST http://localhost:3001/reset-password \
  --data-urlencode 'token=VALID_TOKEN' \
  --data-urlencode 'new_password=NewPass2!' \
  --data-urlencode 'csrf_token=CSRF_FROM_FORM'
```

Expected: `200 {"success": true, "message": "...You can now log in.", "redirect": "/login"}`.

Then log in with the new password:

```bash
curl -s -c cookies.txt -X POST http://localhost:3001/login \
  --data-urlencode 'username=alice' \
  --data-urlencode 'password=NewPass2!' \
  --data-urlencode 'csrf_token=TOKEN_FROM_LOGIN_PAGE'
```

Expected: `200` (login succeeds with new password).

### 12.8 Single-Use Token (spec §10.9 — FR-10)

Try to use the same token again:

```bash
curl -s 'http://localhost:3001/reset-password?token=USED_TOKEN'
```

Expected: `200` with the "invalid or expired" message (token was cleared on first consumption).

### 12.9 Lockout Clear on Successful Reset (spec §10.10 — FR-07)

If an account is locked (≥6 failed login attempts), request a reset and successfully reset:

```bash
# Trigger lockout: 6 failed logins
for i in {1..6}; do curl -s -o /dev/null http://localhost:3001/login \
  --data-urlencode 'username=bob' --data-urlencode 'password=wrong'; done
# Confirm locked
curl -s http://localhost:3001/login --data-urlencode 'username=bob' | grep -i 'locked'
# Request reset, use token, set new password
# Try login with new password
```

Expected: after reset, the new login succeeds (lockout cleared).

### 12.10 Enumeration Resistance + Email Delivery (spec §10.11 — FR-03)

Even with SMTP configured and delivery succeeding, the response is identical. Verify by checking server logs or DB directly that the email was sent, then verify the POST response is still the generic message (no difference between "account exists" and "account doesn't exist" responses).

### 12.11 Parameterized SQL Audit (spec §10.12 — VULN-1)

```bash
grep -n '?' backend/app/services/password_reset_service.py | wc -l
# expect 5 (one SELECT in request_reset, one SELECT in validate_token,
# two CLEARings, one big UPDATE in reset_password_with_token)
grep -n '".*".*".*username.*email' backend/app/services/password_reset_service.py
# should NOT match — no string concatenation.
```

Expected: all five SQL statements use placeholders; no string concatenation.

### 12.12 Preserved-Vulnerability Audit (spec §10.13 — VULN-1–8)

```bash
# VULN-1: parameterized (✓ from 12.11)
# VULN-2: check email rendering escapes username + URL
grep -n 'html.escape' backend/app/core/mailer.py | grep 'password_reset' -A 5 -B 5
# VULN-3: token never logged or reflected raw
grep -n 'password_reset_token\|reset-password' backend/app/api/routes/auth.py
# verify no raw-query-param echo, only server-validated value spliced
# VULN-4: SECRET_KEY sourcing unchanged
grep -n 'SECRET_KEY' backend/app/main.py | head -5
# VULN-5: bcrypt usage in password reset
grep -n 'hash_password\|password_meets_policy' backend/app/services/password_reset_service.py
# VULN-6: no /download/db route added
grep -n 'download/db' backend/app/api/routes/auth.py && echo 'FAIL: endpoint exists' || echo 'PASS: no download/db'
# VULN-7: rate limit applies to new POSTs
# (tested in Step 12.13 below)
# VULN-8: CSRF on reset POST
grep -n 'csrf_token' frontend/templates/reset_password.html | grep hidden
```

Expected: all checks pass.

### 12.13 Rate Limit on New POSTs (spec §10.14)

```bash
# Simulate 6 POST /forgot-password requests in quick succession
for i in {1..6}; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:3001/forgot-password \
    --data-urlencode 'email=any@example.com')
  echo "Request $i: $code"
done
```

Expected: requests 1–5 return `200` and the 6th returns `429` (rate-limited).

### 12.14 File Audit (spec §10.15 — MUST-NOT list)

```bash
git diff --stat backend/app/main.py backend/app/core/rate_limit.py backend/app/core/csrf.py \
  backend/app/core/security.py backend/app/db/session.py backend/app/services/auth_service.py \
  backend/app/services/lockout_service.py frontend/templates/signup.html frontend/templates/dashboard.html \
  frontend/templates/profile.html pyproject.toml backend/pyproject.toml uv.lock
```

Expected: all return empty (no changes).

```bash
git status --porcelain | grep -E '\.(toml|lock)$'
```

Expected: empty (no dependency changes).

### 12.15 App Boot + Integration (spec §10.16)

```bash
# Kill the old server and restart
# Ctrl+C the running `uv run backend/app/main.py`
uv run backend/app/main.py
# In another terminal, hit the four endpoints one more time
curl -s http://localhost:3001/forgot-password | grep -c 'form-input'
curl -s 'http://localhost:3001/reset-password?token=fake' | grep -c 'invalid or expired'
```

Expected: the app boots cleanly; the pages render correctly.

### 12.16 Spec Acceptance Criteria Roll-Up (spec §9)

Tick every AC from spec §9:

- [ ] AC-01: Schema adds two columns idempotently (Step 2, 12.14)
- [ ] AC-02: Config reads PASSWORD_RESET_TTL_SECONDS from env (Step 1)
- [ ] AC-03: Generic 200 in all request_reset outcomes (Step 3, 12.3)
- [ ] AC-04: validate_token is read-only (Step 3, 12.4)
- [ ] AC-05: reset token is single-use (Step 3, 12.8)
- [ ] AC-06: Lockout cleared on successful reset (Step 3, 12.9)
- [ ] AC-07: Password strength enforced (Step 3, 12.6)
- [ ] AC-08: Parameterized SQL (Step 3, 12.11)
- [ ] AC-09: Token never reflected (Step 5, 12.4)
- [ ] AC-10: Forgot-password route returns generic 200 (Step 5, 12.3)
- [ ] AC-11: Reset-password routes validate before render (Step 5, 12.4)
- [ ] AC-12: Email escapes username + URL (Step 4, 12.12)
- [ ] AC-13: Mailer fail-safe (Step 4, log check)
- [ ] AC-14: forgot_password.html form submits urlencoded (Step 6, 12.15)
- [ ] AC-15: reset_password.html token is hidden, validated (Step 7, 12.6)
- [ ] AC-16: Forgot password link on login (Step 8, 12.15)
- [ ] AC-17: CSS for messages + links (Step 9, rendered in browsers)
- [ ] AC-18: Rate limit applies (Step 12.13)
- [ ] AC-19: CSRF on reset POST (Step 12.6)
- [ ] AC-20: All eight vulns preserved (Step 12.12)
- [ ] AC-21: README + CLAUDE.md updated (Step 11)
- [ ] AC-22: App boots (Step 12.15)

### 12.17 Stop the Server

`Ctrl+C` to stop. Plan complete.

---

## Risk Log & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Reset-form fetches send raw `FormData` (multipart) → CSRF middleware rejects every POST with 403 | High | High | Step 7 + Step 5 both wrap in `URLSearchParams`; spec §FR-08; Step 12.6 exercises the valid reset path |
| Token reflected into reset form without validation → re-opens VULN-3 | Low | High | Step 5 validates token server-side first; only the validated value (from DB) is spliced; Step 12.4 confirms invalid tokens don't render the form |
| Email enumeration — separate response for "no account" vs "account exists" | Medium | Medium | Step 5 POST returns the same `200` in every case; the route layer enforces FR-03; Step 12.3 verifies all email outcomes are identical |
| Lockout columns not cleared on reset → user resets password but is still locked out | Medium | High | Step 3 `reset_password_with_token()` UPDATEs four columns (password + token + lockout) in one statement; Step 12.9 verifies |
| String-concatenated SQL slips into `password_reset_service.py` → re-opens VULN-1 | Low | High | Step 3 uses parameterized `?` everywhere; Step 12.11 asserts five `?` placeholders and no string concat |
| Token logged in plaintext → leaks reset links | Low | High | Step 3 mailer logs only "email sent to X" (not token); Step 3 service never logs token; password_reset_post never logs it |
| Token sent in plain HTTP (not HTTPS) if APP_BASE_URL is http://… | Very Low | Medium | Documented in `.env.example` + README setup section (production must use HTTPS) — outside scope of this feature |
| New password spliced into email without HTML escape → re-opens VULN-2 on the reset URL | Low | High | Step 4 `html.escape(..., quote=True)`'s both username and reset_url before HTML splice; Step 12.12 verifies |
| Password-strength policy on new password not synchronized between JS + server | Low | Medium | Step 7 password input validation mirrors the five-criteria policy; Step 3 `password_meets_policy()` enforces server-side; if they diverge, the server gate always wins (weaker policies are rejected by the server) |
| Modifying `auth_service.py` "while in here" — scope creep / regression | Low | Medium | Spec §2.2 + plan Step 0 forbid it; all tests use existing `route_login()` / `signup()` and should still pass if those are untouched |
| Editing `.env` or committing secrets | Low | High | `.env.example` uses placeholders; `.env` is git-ignored; Step 11 reminds of this in the Important Rules and README notes |
| Rate limit window is shared with all other POSTs — legitimate password resets can consume allowance | Low | Low | Documented behavior (spec §2.2, non-goal); the per-IP rate limiter is the intended defense-in-depth (VULN-7 is unchanged) |

---

## Rollback Procedure

If a phase fails verification and cannot be repaired quickly:

```bash
git restore backend/app/core/config.py backend/app/core/mailer.py \
  backend/app/db/session.py backend/app/api/routes/auth.py \
  frontend/templates/login.html frontend/static/css/styles.css \
  README.md CLAUDE.md .env.example
rm -f backend/app/services/password_reset_service.py \
  frontend/templates/forgot_password.html frontend/templates/reset_password.html
```

The modified files snap back to their pre-feature state and the three new files are removed. No dependency, schema-schema (the two columns live in the DB forever, but are harmless) — `vulnerable_app.db`, the `users` table, and the session-cookie format are untouched by this feature. Existing data persists; the app behaves as if the feature was never attempted.

---

## Out-of-Band: What This Plan Deliberately Does NOT Do

- **No password-reset for Google-only accounts** — rows with `password IS NULL` are silently skipped (spec §2.1, FR-03).
- **No resend cooldown** — future hardening (spec §2.2, non-goal).
- **No per-email rate limit** — the per-IP `RateLimitMiddleware` is judged sufficient; future granularity can add per-email limits (spec §2.2, non-goal).
- **No auto-verification** — resetting a password does not touch `is_verified` (spec §2.2, non-goal).
- **No 2FA bypass** — a password reset does not touch TOTP / OTP state; a user who resets a forgotten password and has 2FA enabled still completes the 2FA challenge on their next login (spec §2.2, non-goal).
- **No session invalidation** — an already-logged-in browser keeps its session; resetting a password doesn't force re-login for other devices (spec §2.2, non-goal).
- **No change to the rate limiter, CSRF, session secret, bcrypt, lockout mechanics, OAuth, QR login, CAPTCHA, or 2FA/TOTP/OTP services** — those pipelines are untouched.
- **No new middleware, no middleware re-ordering, no main.py edit.**
- **No new dependency** — `pyproject.toml` / `uv.lock` untouched.
- **No database-schema change beyond the sixth additive migration** — only two new nullable columns, added idempotently.
- **No change to signup() / login() / change_password() / logout / welcome / search / index.**
- **No change to signup.html / dashboard.html / profile.html.**
- **No reversal of any prior fix** — VULN-1 through VULN-8 stay closed.

---

## Ordering Rationale

Config (Step 1) sets tunable values before they're read; schema (Step 2) before the service references columns; mailer (Step 4) before the service calls it; service (Step 3) written after its dependencies but before the route layer needs it; routes (Step 5) before the templates render them; templates (Steps 6–7) before styling (Step 9) and docs (Step 11) reference them. Each step is individually testable and reversible.

