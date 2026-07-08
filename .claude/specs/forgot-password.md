# Software Specification Document — Forgot / Reset Password

**Version:** 1.0.0
**Last Updated:** 2026-07-07
**Target Release Tag:** v2.1.0
**Parent Documents:** [PRD.md](../../docs/PRD.md), [TDD.md](../../docs/TDD.md), [app-foundation.md](./app-foundation.md)
**Tracking Issue:** Forgot / Reset Password — new item (not yet in README's "Feature Enhancements" table)

---

## 1. Overview / Purpose

This document specifies the **Forgot / Reset Password** enhancement. It is not one of the ten originally-planned README "Feature Enhancements" (all of which are now shipped through v2.0.0) — it closes a genuine, currently-missing capability: a local (username/password) account that has forgotten its password has **no self-service recovery path** in this repository today. The only ways back into such an account are (a) happening to also have Google linked to the same email, or (b) an administrator editing the SQLite file directly. This feature adds the standard "Forgot password?" → emailed reset link → "set a new password" flow.

**This is a new, unauthenticated entry point into the existing password flow — not a replacement for it.** It composes with every already-closed control and every already-shipped feature exactly the way Email Verification (v1.0.4) and Email OTP 2FA (v1.0.6) do:

| Stage | Control already in place | What this feature adds |
|---|---|---|
| Flood of POSTs | per-IP `RateLimitMiddleware` (VULN-7) | — (unchanged; covers the two new POSTs too) |
| Forged cross-site POST | synchronizer-token `CSRFMiddleware` (VULN-8) | — (unchanged; both new forms carry `csrf_token`) |
| Password storage | bcrypt `hash_password()` (VULN-5) | — (unchanged; the new password is hashed exactly like signup/change-password) |
| Email delivery | SendGrid HTTPS API mailer (`core/mailer.py`) | one new sender, `send_password_reset_email()`, same fail-safe contract |
| Per-account brute force | Account Lockout (v1.0.5) | a successful reset also **clears** the lockout counters (see §2.1) |
| Token model | `secrets.token_urlsafe(32)` + expiry, precedent from Email Verification (v1.0.4) | same primitive, new columns, new purpose |

The feature is built entirely on the project's existing primitives, with **no new third-party dependency** (stdlib `secrets` + `time`, the existing `core/mailer.py` SendGrid transport, the existing `core/config.py` env loader, the existing `CSRFMiddleware` / `RateLimitMiddleware`):

- **Reset state lives server-side on the user's row** — two new columns — mirroring the schema-on-`users` precedent set by Email Verification (v1.0.4), Account Lockout (v1.0.5), Email OTP 2FA (v1.0.6), and MFA-via-Authenticator-App (v1.0.7).
- **The token is a 256-bit `secrets.token_urlsafe(32)` value** — the identical primitive `verification_service.start_verification()` already uses — stored server-side with a 1-hour expiry (env-tunable), single-use, and validated on `POST /reset-password`.
- **No session, no JWT, no new cookie.** The whole flow is unauthenticated by design (a user who forgot their password, by definition, cannot present a session); the reset token in the URL is the only credential involved, exactly as the emailed verification link is the only credential in v1.0.4.
- **Enumeration-resistant by construction.** `POST /forgot-password` returns the **same** generic message ("If that email is registered, we've sent a reset link") whether or not the email exists, whether the account is Google-only, or whether SendGrid fails — mirroring the generic-401 posture `login()` and `resend_for_credentials()` already use for username/password.
- All new SQL is **parameterized** (VULN-1). The token is never reflected into any page or log line (VULN-3 posture, matching the OTP code's "never logged" rule). Usernames spliced into the reset email are `html.escape(..., quote=True)`'d (VULN-2 posture, matching `send_verification_email` / `send_otp_email`).

**Reset-target posture (product-owner choice): local accounts only.** A row is eligible for a password reset only when `password IS NOT NULL` (a local account, or a Google account that has since set a local password via some future feature — not possible today, but the guard is correct either way). A **Google-only** account (`password IS NULL`) matching the submitted email is silently skipped: the generic message is still shown (no enumeration of provider type), but no token is issued and no email is sent, because there is no password to reset. This is a deliberate, documented non-goal (see §2.2).

**Lockout-interaction posture (product-owner choice): a successful reset clears the lockout.** Completing a password reset is a stronger proof of account control than a login (it required clicking a link sent to the registered email address), so `reset_password_with_token()` clears `failed_login_attempts` and `locked_until` in the same statement that writes the new hash — mirroring `lockout_service.reset()`, which the existing `login()` already calls on every successful authentication. This prevents the confusing experience of successfully resetting a password only to immediately hit "account locked."

This feature does **not** change any of the eight closed vulnerabilities. After this change, all eight remain closed and the app gains its **sixth** database-schema change.

The implementation touches:

- One new backend module: `backend/app/services/password_reset_service.py` (token issue / validate / consume helpers, parameterized SQL — the password-reset analog of `verification_service.py`).
- Two new templates: `frontend/templates/forgot_password.html` (request-a-link form) and `frontend/templates/reset_password.html` (set-a-new-password form).
- Existing files: `backend/app/core/config.py` (reset-token TTL setting), `backend/app/core/mailer.py` (new `send_password_reset_email`), `backend/app/db/session.py` (additive migration, two columns), `backend/app/api/routes/auth.py` (four new routes), `frontend/templates/login.html` (a "Forgot password?" link near the password field).
- `.env.example`, `README.md`, and `CLAUDE.md` (documentation).

**No other file is touched.** In particular, `backend/app/main.py`, `backend/app/core/security.py`, `backend/app/core/csrf.py`, `backend/app/core/rate_limit.py`, `backend/app/core/oauth.py`, `backend/app/core/qr_login.py`, `backend/app/core/captcha.py`, `backend/app/services/auth_service.py`, `backend/app/services/oauth_service.py`, `backend/app/services/lockout_service.py`, `backend/app/services/verification_service.py`, `backend/app/services/otp_service.py`, `backend/app/services/totp_service.py`, and the other templates / CSS remain unchanged. No dependency is added.

---

## 2. Scope & Non-Goals

### 2.1 In Scope

- **Schema (additive, idempotent — sixth-ever schema change).** Add two columns to `users` in `init_db()`:
  - `password_reset_token TEXT` — the active single-use reset token (`secrets.token_urlsafe(32)`), or `NULL` when none is outstanding.
  - `password_reset_token_expires REAL` — Unix epoch seconds after which the token is dead, or `NULL`.
  - The migration adds any missing column with `ALTER TABLE users ADD COLUMN ...`, never dropping a row, exactly like every prior migration. **No grandfather `UPDATE` is needed:** both defaults are effectively `NULL` (no outstanding token), so every existing row starts correct — the same posture as the lockout, OTP, and TOTP columns.
- **Reset-link configuration (`core/config.py`).** One new, non-secret, env-tunable setting, following the exact pattern of `EMAIL_VERIFICATION_TTL_SECONDS`:
  - `PASSWORD_RESET_TTL_SECONDS` (default `3600`, i.e. **1 hour**) — reset-token lifetime.
  - No new `is_*_configured()` gate of its own: reset-link delivery depends on email, so both new routes reuse the existing **`is_email_configured()`** gate exactly as Email Verification and Email OTP already do.
- **Password-reset service (`services/password_reset_service.py`, new).** Stdlib-only helpers (`secrets`, `time`, `threading`, `logging`), all parameterized SQL, mirroring `verification_service.py`'s shape so a reader who already understands that file understands this one:
  - `request_reset(email: str, background: bool = True) -> None` — look up **one** row by `SELECT * FROM users WHERE email = ?` (an email is not `UNIQUE` in this schema — see EC-09); if a row exists **and** `row["password"] is not None` (a local account), generate a fresh token with `secrets.token_urlsafe(32)`, persist it + `password_reset_token_expires = time.time() + PASSWORD_RESET_TTL_SECONDS` via a parameterized `UPDATE`, and send the reset email (`background=True` → daemon thread, mirroring `start_verification`'s signup path; `background=False` → synchronous, for the (non-existent in this slice) resend case — kept for symmetry with `verification_service.start_verification`'s signature). If no row matches, or the matching row is Google-only (`password IS NULL`), this function does **nothing** and returns silently — **the route layer, not this function, is what makes the response look identical either way** (see FR-03).
  - `validate_token(token: str) -> dict` — read-only lookup (no consumption): `SELECT id, password_reset_token_expires FROM users WHERE password_reset_token = ?`. Returns `{"status": "ok" | "invalid" | "expired"}`. Used by `GET /reset-password` to decide whether to render the "choose a new password" form or an "this link is invalid or has expired" message, **without** spending the token on a mere page load (unlike `GET /verify`, which intentionally *does* consume on GET because clicking that link is the entire point of email verification; here, clicking the link should only ever *unlock the form*, and the token must survive a page refresh, a second tab, or an eager email-security scanner prefetching the URL).
  - `reset_password_with_token(token: str, new_password: str) -> dict` — the function that actually consumes the token. Returns `{"status": <str>, "user": <dict|None>}`:
    - `"ok"` — token matched, was unexpired, and `new_password` satisfies `auth_service.password_meets_policy()`; the row's `password` is set to `hash_password(new_password)`, **both** reset-token columns are cleared (single-use), and `failed_login_attempts` / `locked_until` are cleared in the same statement (see §1, lockout-interaction posture). `user` carries `{id, username, email}`.
    - `"invalid"` — no row has this token (never issued, already consumed, or malformed/empty input).
    - `"expired"` — a row matches but `time.time() > password_reset_token_expires`; the token is cleared so it cannot be retried after the clock check fails once.
    - `"weak_password"` — the token is valid but `new_password` fails `password_meets_policy()`; **no state changes** (token is left intact so the user can immediately retry with a stronger password instead of having to restart the whole email flow).
  - All SQL is parameterized; the bcrypt hash uses the existing `core.security.hash_password()` — this module does **not** implement its own hashing.
- **New routes (`api/routes/auth.py`).** Four thin handlers; both POSTs ride the existing CSRF + rate-limit middleware automatically:
  - `GET /forgot-password` — render `forgot_password.html` with a spliced CSRF token, same pattern as `login_page()` / `signup_page()`.
  - `POST /forgot-password` — read the `email` form field and call `password_reset_service.request_reset(email, background=True)`, **then always** return the same `200 {"success": true, "message": "If that email is registered, a reset link has been sent."}` regardless of whether a row existed, was Google-only, or SendGrid failed. This is the enumeration-resistance contract (FR-03) — the route, not the service, guarantees it.
  - `GET /reset-password?token=...` — call `validate_token`; on `"ok"` render `reset_password.html` with the token spliced into a hidden field and a CSRF token spliced into the form; on `"invalid"`/`"expired"` (or a missing/empty `token` query param) render a small fixed "this link is invalid or has expired — request a new one" message with a link back to `/forgot-password` (reuses the existing tiny-HTML-snippet style `signup()` already uses for its 400 responses — no new template needed for this branch).
  - `POST /reset-password` — read `token` + `new_password` form fields, call `reset_password_with_token`. On `"ok"`, return `200 {"success": true, "message": "Password updated. You can now log in.", "redirect": "/login"}` (no session is written — the user still has to log in with the new password, exactly as if they had just used `/profile/password`). On `"weak_password"`, return `400` with the identical policy-violation message `change_password()` already uses (kept word-for-word identical so the two flows read as one consistent product, not two different password-policy implementations). On `"invalid"`/`"expired"`, return `400` with a fixed generic message.
- **Templates.**
  - **New `forgot_password.html`** — same shared header / theme-toggle / pre-render theme IIFE as every other page; a form with a hidden `csrf_token`, a single `email` input, a Submit button, and a status element. Submits urlencoded via `URLSearchParams` (so the CSRF middleware's parser accepts it), reads JSON, and shows the returned message inline (modeled on `login.html`'s fetch handler). No redirect on success — the message itself ("check your email") is the terminal state, mirroring `check_email.html`'s role after signup.
  - **New `reset_password.html`** — same shared chrome; a form with a hidden `csrf_token`, a hidden `token` (server-spliced from the validated query param — never user-editable, never reflected from raw user input, only from the already-validated value `GET /reset-password` looked up), a `new_password` input, a `confirm_password` input (client-side match check only, mirroring `signup.html`'s existing confirm-password JS), a Submit button, and a status element. On `200 {"success": true}` it redirects to `/login` (via `data.redirect`) after a short delay, exactly like `otp_verify.html` and `login.html` redirect on their own success paths.
  - **`login.html`** — one additive line: a "Forgot your password?" link next to the password field, pointing at `/forgot-password`. No JS logic changes; the existing fetch handler, CAPTCHA widget, and OTP/TOTP redirect branches are untouched.
- **Mailer (`core/mailer.py`).** Add `send_password_reset_email(to_email, username, reset_url) -> bool` alongside `send_verification_email` and `send_otp_email`: identical fail-safe contract (returns `False`, never raises), identical SendGrid HTTPS-API transport, username **and** `reset_url` `html.escape(..., quote=True)`'d into the HTML part (the URL contains the token, so it gets the same output-encoding treatment `send_verification_email` already gives its verify link).
- **`.env.example`.** Append one commented placeholder (`PASSWORD_RESET_TTL_SECONDS`) with its default — a value, not a secret.
- **Docs.** Update `README.md` (add a "Forgot / Reset Password" row to the "Feature Enhancements" table, a v2.1.0 release row, and the four new routes to the API table) and `CLAUDE.md` (integration subsection, Important-Rules entry, Specification-Hierarchy entry).

### 2.2 Out of Scope (Intentionally)

- **No password reset for Google-only accounts.** A row with `password IS NULL` is skipped by `request_reset()` — there is no local password to reset, and inventing one would silently convert an OAuth-only account into a dual-auth account, which is a product decision this slice does not make. Documented future hardening: "allow a Google user to also set a local password from `/profile`" is a **separate**, larger feature (it touches the OAuth surface `CLAUDE.md` protects) and is explicitly not this one.
- **No invalidation of other active sessions.** This app's auth is a single signed cookie with no server-side session store (the QR-login in-memory store is unrelated pairing state, not a session registry), so there is no mechanism to enumerate or revoke "other logged-in devices" for a user. A password reset changes the hash so a *future* login needs the new password, but it cannot forcibly log out a browser that already holds a valid, unexpired session cookie. Documented as a known limitation, identical in spirit to `CLAUDE.md`'s existing session-only posture — implementing revocation would require a session-id table, which is out of scope for this slice.
- **No auto-verification of the email address.** Successfully resetting a password does **not** set `is_verified = 1`. Email Verification (v1.0.4) and Forgot Password are kept as two independent concerns with two independent token columns; conflating them would make each harder to reason about in isolation.
- **No 2FA / TOTP interaction.** A password reset does not touch `two_factor_enabled`, `otp_*`, `totp_*`, or the QR-login state. A user who resets a forgotten password and has 2FA enabled still completes the (unchanged) 2FA challenge on their next login — this feature only ever gets them as far as a correct password would.
- **No rate limit or lockout of the `/forgot-password` request itself beyond the existing per-IP `RateLimitMiddleware`.** A dedicated per-email cooldown (mirroring the OTP resend cooldown) is deliberately **not** added in this slice, to keep the change surgical; the per-IP limiter is judged sufficient given the token's 1-hour expiry and single-use consumption. Documented future hardening.
- **No change to the rate limiter, CSRF, session secret, bcrypt, lockout mechanics, OAuth, QR login, CAPTCHA, or TOTP/OTP services.** Those middlewares/services stay byte-for-byte unchanged; the two new POSTs inherit the existing CSRF + rate-limit protection.
- **No new dependency.** `pyproject.toml`, `backend/pyproject.toml`, and `uv.lock` are unchanged. The token uses stdlib `secrets`; delivery reuses the existing SendGrid mailer.
- **No template engine / JS framework.** Both new screens are hand-written HTML files with an inline `<script>`, like every other page.

### 2.3 Explicit Preservation Note — All Eight Closed Vulnerabilities Stay Closed

- **VULN-1 (SQL Injection):** every statement in `password_reset_service.py` uses parameterized `?` placeholders. No string concatenation.
- **VULN-2 (Stored XSS):** the reset email `html.escape(..., quote=True)`'s the username **and** the reset URL before splicing into the HTML part (same pattern as `send_verification_email`); `reset_password.html`'s spliced `token` field is a server-controlled value that was itself validated by an exact-match DB lookup, not raw user input.
- **VULN-3 (Reflected XSS):** the reset token is **never** reflected into any page except as the hidden-field value of a form the token itself unlocked (and only after a DB round-trip confirms it is real and unexpired) — it is never echoed from the raw query string without that check. All JSON messages on both new routes are fixed, server-controlled strings.
- **VULN-4 (Session Hijacking):** `main.py` is not modified; this feature writes no session data at all — it is fully unauthenticated by design, and completing a reset requires a normal subsequent login exactly like `change_password()` does not auto-extend a session either. `PASSWORD_RESET_TTL_SECONDS` comes from env/`.env` with a non-secret default.
- **VULN-5 (Weak Password Storage):** `core/security.py` is unchanged; the new password goes through the identical `hash_password()` (bcrypt) call `signup()` and `change_password()` already use, and is gated by the identical `password_meets_policy()` check `change_password()` already enforces.
- **VULN-6 (Exposed Database):** no `/download/db` route exists; none is added.
- **VULN-7 (No Rate Limiting):** `RateLimitMiddleware` stays registered and unchanged; `POST /forgot-password` and `POST /reset-password` are throttled by it like every other POST.
- **VULN-8 (CSRF):** both new POSTs carry the hidden `csrf_token`; `CSRFMiddleware` validates them. The two new GETs reflect nothing sensitive and are safe by construction (see VULN-3 note above).

### 2.4 Explicit Non-Goals

- This feature does **not** change `signup()`, `login()`, `change_password()`, `password_meets_policy()` (it is **imported and reused**, not reimplemented), the lockout helpers' public API, the verification helpers, the OTP/TOTP services, or the OAuth path.
- This feature does **not** add its own password-strength meter widget to `reset_password.html`; it reuses the same server-side `password_meets_policy()` gate `change_password()` uses, with the identical error message, so the two "set a new password" experiences are policy-identical without duplicating the check.
- This feature does **not** persist any token outside the `users` table. No Redis, no in-memory map, no extra cookie.

---

## 3. Affected Files

The change MUST touch only the following files (beyond this spec/plan pair and the prompt docs).

| Path | Change Type | Purpose |
|---|---|---|
| `backend/app/services/password_reset_service.py` | **New** | `request_reset()`, `validate_token()`, `reset_password_with_token()` — parameterized SQL, stdlib token generation, fail-safe send, reuses `hash_password()` / `password_meets_policy()` |
| `frontend/templates/forgot_password.html` | **New** | "Enter your email" screen (hidden `csrf_token`, single email input, fixed generic result message) |
| `frontend/templates/reset_password.html` | **New** | "Choose a new password" screen (hidden `csrf_token` + hidden validated `token`, new/confirm password inputs, fetch → JSON → redirect to `/login`) |
| `backend/app/core/config.py` | Modified | `PASSWORD_RESET_TTL_SECONDS` (3600); docstring note |
| `backend/app/core/mailer.py` | Modified | Add `send_password_reset_email()` (fail-safe, escaped username + URL) |
| `backend/app/db/session.py` | Modified | Additive idempotent migration (2 columns); no grandfather needed |
| `backend/app/api/routes/auth.py` | Modified | 4 new routes (`GET`+`POST /forgot-password`, `GET`+`POST /reset-password`) |
| `frontend/templates/login.html` | Modified | "Forgot your password?" link to `/forgot-password` |
| `.env.example` | Modified | Commented `PASSWORD_RESET_TTL_SECONDS` placeholder (default shown) |
| `README.md` | Modified | New "Forgot / Reset Password" feature row; v2.1.0 release row; API-endpoint rows |
| `CLAUDE.md` | Modified | Integration subsection, Important-Rules entry, hierarchy entry |

Files that MUST NOT be modified by this change:

- `backend/app/main.py` — middleware wiring / `SECRET_KEY` / `RATE_LIMIT_*` / port (VULN-4 / VULN-7 / VULN-8 closures). The reset logic is service/route-layer; no middleware is added.
- `backend/app/core/rate_limit.py`, `backend/app/core/csrf.py`, `backend/app/core/security.py` — VULN-7 / VULN-8 / VULN-5 closures stay exactly as-is (this feature **calls** `hash_password()`; it does not modify it).
- `backend/app/core/oauth.py`, `backend/app/services/oauth_service.py`, `backend/app/core/qr_login.py`, `backend/app/core/captcha.py` — no interaction; a Google-only row is deliberately skipped (§2.2), and QR login / CAPTCHA are unrelated login surfaces.
- `backend/app/services/auth_service.py` — `login()`, `signup()`, `change_password()`, `password_meets_policy()` are **called into**, never edited. (`password_meets_policy()` is imported by the new service, not duplicated.)
- `backend/app/services/lockout_service.py`, `backend/app/services/verification_service.py`, `backend/app/services/otp_service.py`, `backend/app/services/totp_service.py` — unchanged. (`reset_password_with_token()` clears the two lockout **columns** directly via its own parameterized `UPDATE`, mirroring what `lockout_service.reset()` does internally, rather than importing that module — kept this way so `password_reset_service.py` has no dependency on `lockout_service.py`'s internals; see FR-07.)
- The other templates (`signup.html`, `dashboard.html`, `profile.html`, `check_email.html`, `verify_result.html`, `email_not_configured.html`, `oauth_not_configured.html`, `otp_verify.html`, `totp_verify.html`, `qr_approve.html`) and `frontend/static/css/styles.css` — both new screens reuse existing classes; no CSS edit is required.
- `pyproject.toml`, `backend/pyproject.toml`, `uv.lock` — no dependency change.

---

## 4. Functional Requirements

### FR-01: Additive, Idempotent Schema Migration
- `init_db()` MUST add `password_reset_token TEXT` and `password_reset_token_expires REAL` to a fresh `CREATE TABLE users`, and MUST add either that is missing from a pre-existing DB via `ALTER TABLE users ADD COLUMN ...`. No row is dropped or rewritten.
- No grandfather `UPDATE` is run: both defaults are `NULL`, already meaning "no reset outstanding," so every existing row starts correct.

### FR-02: Reset-Link Configuration
- `config.PASSWORD_RESET_TTL_SECONDS` MUST be read from the environment as an `int`, defaulting to `3600`.
- This is not a secret; it is documented in `.env.example` with its default. No new `is_*_configured()` gate is added; reset-link delivery reuses `is_email_configured()`.

### FR-03: Enumeration-Resistant Request Endpoint
- `POST /forgot-password` MUST return the identical `200 {"success": true, "message": "..."}` body regardless of whether the submitted email matches zero rows, matches a Google-only row, matches a local row, or the subsequent email send fails. The route MUST NOT branch its HTTP response on any of these internal outcomes — the enumeration resistance is a property of the **route**, not merely of `request_reset()`'s return value (which is `None` either way, but the route must not, for example, add a try/except that surfaces a different message on a DB error).
- An empty/missing `email` field MAY short-circuit to the same generic message without a DB call (no distinguishable behavior either way).

### FR-04: Password-Reset Service Helpers (`password_reset_service.py`)
- `request_reset(email, background=True) -> None` MUST look up **one** row via a parameterized `SELECT * FROM users WHERE email = ?` (`fetchone()`). If no row, or `row["password"] is None` (Google-only), it MUST do nothing further and return. Otherwise it MUST generate `secrets.token_urlsafe(32)`, persist the token and `password_reset_token_expires = time.time() + PASSWORD_RESET_TTL_SECONDS` via a parameterized `UPDATE`, then send `mailer.send_password_reset_email(...)` — on a daemon thread when `background=True`, synchronously otherwise (mirroring `verification_service.start_verification`).
- `validate_token(token) -> dict` MUST be read-only (no `UPDATE`, no consumption) and MUST return `{"status": "invalid"}` for an empty/missing/non-matching token, `{"status": "expired"}` for a matching-but-expired token, and `{"status": "ok"}` otherwise.
- `reset_password_with_token(token, new_password) -> dict` MUST: return `{"status": "invalid", "user": None}` for an empty/missing/non-matching token; return `{"status": "expired", "user": None}` (and clear the token columns) for a matching-but-expired token; return `{"status": "weak_password", "user": None}` (with **no** column changes) when `auth_service.password_meets_policy(new_password)` is false; otherwise hash `new_password` with `core.security.hash_password()`, write it to `password`, clear both reset-token columns, clear `failed_login_attempts` (`= 0`) and `locked_until` (`= NULL`), and return `{"status": "ok", "user": {"id", "username", "email"}}`.
- All SQL MUST be parameterized. A malformed/empty `token` MUST be treated as `"invalid"`, never raising.

### FR-05: Request-Reset Route
- `GET /forgot-password` MUST render `forgot_password.html` with a spliced CSRF token, unauthenticated (no session check — a user who forgot their password by definition has none).
- `POST /forgot-password` MUST read the `email` form field, call `request_reset(email, background=True)`, and return the fixed generic `200` message described in FR-03 in every case.

### FR-06: Reset-Password Routes
- `GET /reset-password` MUST read the `token` query parameter and call `validate_token`. On `"ok"` it MUST render `reset_password.html` with the token spliced into a hidden field and a CSRF token spliced into the form. On `"invalid"` or `"expired"` (or a missing/empty `token`) it MUST render a fixed, generic "this link is invalid or has expired" message with a link to `/forgot-password`, and MUST NOT render the password-entry form.
- `POST /reset-password` MUST read the `token` and `new_password` form fields and call `reset_password_with_token`. On `"ok"` it MUST return `200 {"success": true, "message": "...", "redirect": "/login"}` and MUST NOT write any session key. On `"weak_password"` it MUST return `400` with the same policy-violation message `change_password()` uses. On `"invalid"`/`"expired"` it MUST return `400` with a fixed generic message.

### FR-07: Lockout Columns Cleared on Successful Reset
- A `reset_password_with_token()` call that reaches `"ok"` MUST clear `failed_login_attempts` (to `0`) and `locked_until` (to `NULL`) for that row in the **same** `UPDATE` statement that writes the new password hash and clears the reset-token columns. This is a direct, parameterized column write inside `password_reset_service.py` — it MUST NOT import or call into `lockout_service.py` (keeps the two modules independent, per §3's "files that MUST NOT be modified" note).

### FR-08: Parameterized SQL Everywhere (VULN-1 Preserved)
- Every SQL statement added by this feature (in `password_reset_service.py` and the route handlers, if any direct queries are added) MUST use `?` placeholders with a separate parameter list. String concatenation into SQL is forbidden.

### FR-09: Password Policy Reused, Not Reimplemented
- `reset_password_with_token()` MUST call `auth_service.password_meets_policy()` to validate `new_password` — the exact same function `change_password()` calls. No second implementation of the five-criteria check is written.

### FR-10: Token Never Reflected Except Through a Validated Round-Trip (VULN-3 Preserved)
- The reset token MUST NOT be echoed into any page directly from the raw query string. `GET /reset-password` MUST call `validate_token` first; only on `"ok"` may the **same, already-validated** token value be spliced into the hidden form field of `reset_password.html`. No response body, log line at INFO+, or error message may contain the token except in that one sanctioned position.

### FR-11: No New Dependency
- No entry is added to `pyproject.toml`, `backend/pyproject.toml`, or `uv.lock`. Token generation uses stdlib `secrets`; delivery reuses the existing SendGrid-based `core/mailer.py` transport.

### FR-12: Untouched Functions / Files
- `signup()`, `login()`, `change_password()` (beyond being called into), the lockout helpers' public functions, the verification helpers, every OTP/TOTP function, every OAuth function, `core/security.py`, `core/csrf.py`, `core/rate_limit.py`, `core/qr_login.py`, `core/captcha.py`, `main.py`, the non-listed templates, and all CSS MUST remain unchanged.

### FR-13: Email Delivery Is Fail-Safe
- `mailer.send_password_reset_email` MUST return `False` (never raise) on any unconfigured/API/network error, logging the cause server-side (never logging the token). A failed send MUST NOT crash `POST /forgot-password` nor change its response — FR-03's generic message is returned either way.

---

## 5. Non-Functional Requirements

### NFR-01: Surgical Scope
Exactly the files in §3 change (plus the spec/plan/prompt docs). No `main.py`, no `core/rate_limit.py`/`csrf.py`/`security.py`/`oauth.py`/`qr_login.py`/`captcha.py`, no `auth_service.py`/`oauth_service.py`/`lockout_service.py`/`verification_service.py`/`otp_service.py`/`totp_service.py` edits, no unrelated template/CSS, no lockfile.

### NFR-02: Configuration, Not Hardcoded Magic Numbers
`PASSWORD_RESET_TTL_SECONDS` comes from `core/config.py` (env/`.env`) with a documented default, mirroring `EMAIL_VERIFICATION_TTL_SECONDS`. Demos can set a short value (`PASSWORD_RESET_TTL_SECONDS=30`).

### NFR-03: Enumeration Resistance Is a First-Class Requirement
Every branch of `POST /forgot-password` — no such email, Google-only account, send failure, send success — is observationally identical from the response alone. This is the same posture `login()` already applies to "no such username" vs. "wrong password."

### NFR-04: Fail-Safe Delivery, Generic Failure Surface
Email sending is fail-safe (bool, never raises) exactly like `send_verification_email` / `send_otp_email`. Unlike the 2FA login path (which fails **closed** because a missing second factor must not silently grant access), a failed reset-email send has no equivalent "silently grant access" risk — the user simply does not receive a link and can retry — so `POST /forgot-password` fails **soft** (still returns the generic success message; see NFR-03).

### NFR-05: No Information Leakage
The reset-request response, the invalid/expired-link message, and the weak-password message are all fixed, server-controlled strings — no email address, no token, no internal field is reflected. DB exceptions are logged server-side, never surfaced.

### NFR-06: Consistency With Existing Patterns
Thin route → service; `get_db()` + `try/finally` per call; parameterized SQL; env config via `core/config.py`; additive idempotent migration like v1.0.4–v1.0.7; `time.time()`-based epoch column like `verification_token_expires` / `otp_expires`; background daemon-thread send like `start_verification` / `start_challenge`; fetch + `URLSearchParams` + hidden `csrf_token` like the login/profile/OTP forms; pre-render theme IIFE + shared header in both new templates; reused `password_meets_policy()` and `hash_password()` rather than reimplemented (matches how `change_password()` already reuses them).

### NFR-07: Reset Token Is Tamper-Resistant and Single-Use
The token is 256 bits of `secrets.token_urlsafe` entropy — infeasible to guess. It is looked up by exact match only, cleared on successful use (FR-04), and cleared on an expired-use attempt (so a stale token cannot be retried indefinitely against the clock). A `GET` request never consumes it (FR-06), so opening the emailed link (or having it prefetched by an email client's link scanner) does not burn the user's only chance to set a new password.

### NFR-08: Reset Does Not Extend Trust Beyond "Can Set a New Password"
Completing a reset writes no session and grants no dashboard access — the user is returned to `/login` and must authenticate normally with the new password (undergoing the unchanged 2FA/TOTP challenge if enabled). This mirrors `change_password()`'s posture of not re-authenticating the caller; a reset is not a login.

### NFR-09: Deliberate Lockout Interaction (Documented Trade-off)
Clearing `failed_login_attempts` / `locked_until` on a successful reset is a deliberate product decision (§1): it privileges "proved email control" as at least as strong a signal as "knows the current password" (which is what triggers `lockout_service.reset()` today). Accepted trade-off, documented in code comments and this spec: an attacker who has compromised the victim's **email** (not their password) could use this flow to reset the password **and** clear a lock, but that attacker already had a stronger foothold (mailbox access) than the lockout was ever designed to resist — the lockout defends the *password*, not the *mailbox*.

---

## 6. Success Paths

### SP-01: Request a Reset Link (Happy Path)
1. A user visits `/forgot-password` and submits their registered local-account email.
2. `request_reset()` finds the row, `password` is not `NULL`, so a token is generated, persisted, and emailed on a daemon thread.
3. The route returns the generic `200` success message immediately (does not wait on the email thread).

### SP-02: Follow the Link and Set a New Password
1. The user opens the emailed link, `GET /reset-password?token=<token>`.
2. `validate_token` returns `"ok"`; `reset_password.html` renders with the token in a hidden field.
3. The user enters a policy-satisfying new password (+ matching confirmation, checked client-side).
4. `POST /reset-password` → `reset_password_with_token` returns `"ok"`: the hash is updated, the token is cleared, the lockout columns are cleared, no session is written.
5. The page shows a success message and redirects to `/login`, where the user authenticates with the new password (subject to the unchanged 2FA/TOTP/CAPTCHA gates if enabled).

### SP-03: Unknown or Google-Only Email (Enumeration-Resistant)
1. A user submits an email with no matching row, or one belonging to a Google-only account.
2. `request_reset()` does nothing (no token, no email sent).
3. The route still returns the identical generic `200` success message as SP-01.

### SP-04: Weak New Password
1. A user follows a valid link and submits a new password that fails `password_meets_policy()`.
2. `reset_password_with_token` returns `"weak_password"` and makes **no** state change (the token remains valid).
3. `POST /reset-password` returns `400` with the policy message; the user retries on the same page without needing a new email.

### SP-05: Locked Account Recovers via Reset
1. An account is currently locked (`locked_until` in the future) after repeated failed logins.
2. The user requests and completes a password reset (SP-01 → SP-02).
3. `failed_login_attempts` and `locked_until` are cleared as part of the successful reset; the user can log in immediately with the new password (no lockout countdown).

---

## 7. Edge Cases

- **EC-01 — Expired token on `GET /reset-password`:** `validate_token` returns `"expired"`; the fixed "invalid or expired" message renders (no form), with a link to request a new one.
- **EC-02 — Expired token on `POST /reset-password`** (opened the form, waited past the TTL before submitting): `reset_password_with_token` returns `"expired"` (and clears the token); `400` with the fixed expired message. The user must request a new link.
- **EC-03 — Reused (already-consumed) token:** after a successful reset the columns are `NULL`; a second `GET` or `POST` with the same token value returns `"invalid"` (no row matches a `NULL` column via exact-match `?` comparison against a non-null string) — treated identically to a token that was never issued.
- **EC-04 — Missing/empty `token` query param or form field:** `validate_token` / `reset_password_with_token` return `"invalid"` without a DB error.
- **EC-05 — Google-only account requests reset:** SP-03 applies; no token, no email, generic success message. If that same email string is later submitted again, the same silent no-op recurs every time (no rate-limit distinction from the "unknown email" case).
- **EC-06 — Weak password, then immediate retry:** SP-04; the token survives exactly one "weak_password" rejection (and any number of them) since only an `"ok"`/`"expired"` outcome ever clears it.
- **EC-07 — SendGrid send fails (misconfigured key, network error, API 4xx/5xx):** `send_password_reset_email` returns `False` and logs server-side; `request_reset` does not propagate this to its caller (returns `None` either way); `POST /forgot-password` still returns the generic success message (NFR-04). The token **is** persisted even though the email failed to send — this is an accepted, documented limitation (a user cannot self-recover from this specific failure without contacting an operator, same as a lost/undelivered verification email today).
- **EC-08 — Email not configured at all (`is_email_configured()` is false):** `request_reset` still runs its DB lookup (harmless) but the mailer call returns `False` immediately; behavior is otherwise identical to EC-07 from the caller's perspective. (Unlike signup/OTP, this route does **not** gate on `is_email_configured()` before proceeding, specifically so its response shape never differs based on configuration state — which would itself be a distinguishing signal. This is a deliberate divergence from the OTP-toggle gate in FR-06 of the Email-OTP-2FA spec, called out here explicitly.)
- **EC-09 — Two rows share the same email** (the schema does not `UNIQUE`-constrain `email`; see `oauth_service.py`'s identical `SELECT ... WHERE email = ?` pattern): `fetchone()` returns the first match per SQLite's row order; a reset link is issued for that one row only. Documented pre-existing limitation of the schema, not newly introduced by this feature.
- **EC-10 — Password reset for an account with 2FA/TOTP enabled:** unaffected; the reset only ever changes the password hash. The next login still runs the unchanged OTP/TOTP challenge (§2.2 non-goal).
- **EC-11 — Reset link opened on a different device/browser than the one that requested it:** works by design — the token, not the session, is the credential. This mirrors the email-verification link's behavior in v1.0.4.
- **EC-12 — Reset requested while already logged in:** `GET`/`POST /forgot-password` and `GET`/`POST /reset-password` are unauthenticated by design (FR-05) and do not check for an existing session; a logged-in user could still complete a reset for their own (or, if they knew it, a different) email. This is intentional — resetting is orthogonal to the existing session, and `change_password()` remains the preferred authenticated-flow entry point (unchanged).
- **EC-13 — DB error inside `reset_password_with_token`:** caught, logged server-side, treated as `"invalid"` (no partial writes — the `UPDATE` either fully succeeds and commits, or the exception path never commits).

---

## 8. Acceptance Criteria

- **AC-01:** A fresh DB's `users` table has `password_reset_token` and `password_reset_token_expires` per `PRAGMA table_info(users)`.
- **AC-02:** A pre-existing DB gains both columns on first boot; existing rows read `NULL` for both; no grandfather `UPDATE` runs.
- **AC-03:** `POST /forgot-password` with a registered local email returns the generic `200` success message and results in a row with a non-`NULL` `password_reset_token` and a future `password_reset_token_expires`.
- **AC-04:** `POST /forgot-password` with an unregistered email, or with a Google-only account's email, returns the **byte-for-byte identical** `200` success message as AC-03, and leaves that row's reset columns `NULL`.
- **AC-05:** `GET /reset-password?token=<valid>` renders the new-password form with the token present in a hidden field.
- **AC-06:** `GET /reset-password?token=<invalid-or-missing>` renders the fixed "invalid or expired" message, not the form.
- **AC-07:** `GET /reset-password?token=<expired>` (set `PASSWORD_RESET_TTL_SECONDS=1`, wait) renders the same fixed "invalid or expired" message.
- **AC-08:** `POST /reset-password` with a valid token and a policy-satisfying password returns `200 {"success": true, "redirect": "/login"}`, updates the row's `password` to a new bcrypt hash, clears both reset-token columns, and clears `failed_login_attempts`/`locked_until`.
- **AC-09:** `POST /reset-password` with a valid token and a policy-violating password returns `400` with the same message text as `change_password()`'s policy error, and leaves the token columns unchanged (a second attempt with a strong password on the same token still succeeds).
- **AC-10:** `POST /reset-password` with an already-consumed or never-issued token returns `400` with the fixed invalid message.
- **AC-11:** After a successful reset (AC-08), logging in with the **old** password fails (`401`, generic invalid-credentials message) and logging in with the **new** password succeeds.
- **AC-12:** An account locked before the reset (`locked_until` in the future) can log in immediately with the new password after a successful reset — no lockout countdown is shown.
- **AC-13:** The reset token never appears in any HTTP response body except the one hidden-field position on a `GET /reset-password?token=<valid>` render, and never appears in a server log line.
- **AC-14:** All SQL in `password_reset_service.py` uses `?` placeholders (no concatenation).
- **AC-15:** `git diff` is empty for `main.py`, `core/rate_limit.py`, `core/csrf.py`, `core/security.py`, `core/oauth.py`, `core/qr_login.py`, `core/captcha.py`, `auth_service.py`, `oauth_service.py`, `lockout_service.py`, `verification_service.py`, `otp_service.py`, `totp_service.py`, `signup.html`, `dashboard.html`, `profile.html`, `styles.css`, and the lockfiles.
- **AC-16:** No new dependency: `pyproject.toml`, `backend/pyproject.toml`, `uv.lock` unchanged.
- **AC-17:** `uv run backend/app/main.py` boots with no traceback; normal signup/login/change-password flows are unaffected.
- **AC-18:** VULN-1…VULN-8 all remain closed (parameterized SQL; bcrypt intact via the reused `hash_password()`; rate-limit + CSRF + session middleware unchanged; no `/download/db`; env-sourced config; no raw token reflection except the one sanctioned, validated position).
- **AC-19:** `README.md` shows a new "Forgot / Reset Password" row in "Feature Enhancements," adds a v2.1.0 release row, and lists the four new routes. `CLAUDE.md` has the new subsection, rule, and hierarchy entry.

---

## 9. Test Cases

| ID | Scenario | Precondition | Expected Result |
|---|---|---|---|
| TC-01 | Columns on fresh DB | `rm` DB, boot | `PRAGMA table_info(users)` shows both new columns at `NULL` defaults |
| TC-02 | Migration on old DB | Pre-migration DB copy | Both columns added; existing rows `NULL`; no grandfather UPDATE |
| TC-03 | Request reset, known local email | Registered local user | `200` generic message; row gets a token + future expiry; email sent |
| TC-04 | Request reset, unknown email | No matching row | `200` **identical** generic message; no row affected |
| TC-05 | Request reset, Google-only email | Google-linked row, `password IS NULL` | `200` **identical** generic message; row's reset columns stay `NULL` |
| TC-06 | Valid token renders form | Token just issued | `GET /reset-password?token=...` → 200 HTML with form + hidden token |
| TC-07 | Invalid token blocked | Random/garbage token | `GET /reset-password?token=...` → fixed invalid message, no form |
| TC-08 | Expired token blocked | `PASSWORD_RESET_TTL_SECONDS=1`, wait 2s | `GET` → fixed invalid/expired message |
| TC-09 | Successful reset | Valid token, strong password | `POST /reset-password` → `200`; hash updated; token cleared; lockout cleared |
| TC-10 | Weak password rejected | Valid token, weak password | `POST` → `400` policy message; token still valid afterward |
| TC-11 | Old password fails post-reset | After TC-09 | `POST /login` with old password → `401` |
| TC-12 | New password succeeds post-reset | After TC-09 | `POST /login` with new password → `200` (or 2FA challenge if enabled) |
| TC-13 | Locked account recovers | Account locked, then reset completed | Login immediately succeeds post-reset, no lockout message |
| TC-14 | Token single-use | Reuse the token from TC-09 | Second `GET`/`POST` with same token → invalid |
| TC-15 | Token never reflected in logs/JSON | Full flow | No log line or JSON body contains the raw token except the one hidden-field render |
| TC-16 | Parameterized SQL | Repo checkout | `password_reset_service.py` uses `?` placeholders throughout |
| TC-17 | Untouched files | Repo checkout | `git diff --stat` empty for the forbidden files + lockfiles |
| TC-18 | No new dep | Repo checkout | `git diff --stat` empty for pyproject/uv.lock |
| TC-19 | App boots + normal flows | Repo checkout | `uv run …` no traceback; signup/login/change-password unaffected |
| TC-20 | Docs updated | Repo checkout | New feature row; v2.1.0 row; new routes; CLAUDE entries |

---

## 10. Verification Steps

Run from the repo root. Use a short reset-token window for the demo (`PASSWORD_RESET_TTL_SECONDS=60`), and raise the per-IP limit if exercising many POSTs from one IP (`RATE_LIMIT_MAX=100`).

### 10.1 Schema (AC-01, TC-01)
```bash
rm -f vulnerable_app.db
uv run backend/app/main.py &
sqlite3 vulnerable_app.db "PRAGMA table_info(users);" | grep -E 'password_reset_token|password_reset_token_expires'   # both
```

### 10.2 Request + Follow the Link (AC-03–AC-06, TC-03, TC-06)
```bash
# Sign up + verify a local user "alice", then:
curl -s -X POST http://localhost:3001/forgot-password \
  -d "email=alice@example.com" -d "csrf_token=<token-from-GET-/forgot-password>"
# → {"success": true, "message": "..."}  (same for any email — try a bogus one too)

sqlite3 vulnerable_app.db "SELECT password_reset_token, password_reset_token_expires FROM users WHERE username='alice';"
# copy the token, then:
curl -s "http://localhost:3001/reset-password?token=<token>"   # renders the form
```

### 10.3 Complete / Reject the Reset (AC-08–AC-10)
```bash
# Strong password → 200, redirect to /login; row's password hash changes.
# Weak password on the SAME token → 400 policy message, token still valid.
# Old password now fails POST /login; new password succeeds.
```

### 10.4 Lockout Interaction (AC-12, TC-13)
```bash
# Trip the lockout with ACCOUNT_LOCKOUT_MAX_ATTEMPTS wrong passwords, confirm locked_until is set:
sqlite3 vulnerable_app.db "SELECT failed_login_attempts, locked_until FROM users WHERE username='alice';"
# Complete a password reset for alice, then re-check the row — both columns should be back to 0 / NULL,
# and POST /login with the new password should succeed immediately (no lock message).
```

### 10.5 File Audit (AC-15, AC-16, TC-17, TC-18)
```bash
git diff --stat -- backend/app/main.py backend/app/core/rate_limit.py backend/app/core/csrf.py \
  backend/app/core/security.py backend/app/core/oauth.py backend/app/core/qr_login.py \
  backend/app/core/captcha.py backend/app/services/auth_service.py backend/app/services/oauth_service.py \
  backend/app/services/lockout_service.py backend/app/services/verification_service.py \
  backend/app/services/otp_service.py backend/app/services/totp_service.py \
  frontend/templates/signup.html frontend/templates/dashboard.html frontend/templates/profile.html \
  frontend/static/css/styles.css pyproject.toml backend/pyproject.toml uv.lock     # all empty
```

Expected `git status --porcelain` (declared files + docs only):
```
?? backend/app/services/password_reset_service.py
?? frontend/templates/forgot_password.html
?? frontend/templates/reset_password.html
 M backend/app/core/config.py
 M backend/app/core/mailer.py
 M backend/app/db/session.py
 M backend/app/api/routes/auth.py
 M frontend/templates/login.html
 M .env.example
 M README.md
 M CLAUDE.md
?? .claude/specs/forgot-password.md
?? .claude/specs/forgot-password-plan.md
?? docs/prompts/forgot-password-spec-prompt.txt
?? docs/prompts/forgot-password-spec-plan-prompt.txt
?? docs/prompts/forgot-password-spec-execution-prompt.txt
```