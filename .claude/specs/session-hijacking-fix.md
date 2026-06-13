# Software Specification Document — Session Hijacking Fix (Secret Key Hardening)

**Version:** 1.0.0
**Last Updated:** June 13, 2026
**Parent Documents:** [PRD.md](../../docs/PRD.md), [TDD.md](../../docs/TDD.md), [app-foundation.md](./app-foundation.md)
**Tracking Issue:** [Session Hijacking — hardcoded session secret](https://github.com/arifpucit/vuln-web-app/issues)

---

## 1. Overview / Purpose

This document specifies the remediation of the **Session Hijacking** vulnerability (OWASP **A07:2021 — Identification and Authentication Failures**). In `backend/app/main.py` the Starlette `SessionMiddleware` is initialised with a hardcoded, publicly-known secret:

```python
SECRET_KEY = "super-secret-key-12345"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
```

Starlette signs the session cookie with this key. Because the key is a constant committed to the public repository, **anyone** can forge a validly-signed session cookie for any `user_id`/`username`/`email` and impersonate any user without credentials. The signing secret is the only thing standing between an attacker and arbitrary session forgery, and it is currently common knowledge.

This fix replaces the hardcoded constant with a secret loaded from the **environment** (`SECRET_KEY`), falling back to a **strong, randomly-generated key** (`secrets.token_hex(32)`) when the environment variable is not set. This means:

- In any real deployment, operators set `SECRET_KEY` to a strong secret that is **not** in the repository.
- For local/lab use, the app still boots with zero configuration, using a fresh random key each start. The trade-off — sessions do not survive a restart when no env var is set — is acceptable and documented.

This fix is **surgical** and closes the **Session Hijacking** vulnerability **only**. The other intentional vulnerabilities remain exploitable for educational use, and the bcrypt password-hashing fix remains permanently in place.

---

## 2. Scope & Non-Goals

### 2.1 In Scope

- Add `import secrets` to `backend/app/main.py`.
- Replace the hardcoded `SECRET_KEY = "super-secret-key-12345"` assignment with `SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))`.
- Leave the `app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)` call intact (it continues to consume `SECRET_KEY`).
- Leave every other line of `main.py` unchanged.

### 2.2 Out of Scope (Intentionally Unfixed)

This fix addresses only the Session Hijacking vulnerability. The following intentional vulnerabilities remain in place after this change and MUST NOT be remediated here:

| Vulnerability | OWASP | Status under this fix |
|---------------|-------|-----------------------|
| SQL Injection (`auth_service.py` string-concatenated queries) | A03:2021 | Already CLOSED (parameterized) — stays closed |
| Stored XSS (`{{username}}` substitution in dashboard) | A03:2021 | Intentionally unchanged |
| Reflected XSS (`/search?q=` reflection) | A03:2021 | Intentionally unchanged |
| **Session Hijacking (hardcoded `"super-secret-key-12345"`)** | **A07:2021** | **CLOSED by this spec** |
| Weak Password Storage | A02:2021 | Already CLOSED (bcrypt) — stays closed |
| Exposed Database endpoint (`/download/db`) | A01:2021 | Already CLOSED (route removed) — stays closed |
| No Rate Limiting | A07:2021 | Intentionally unchanged |
| CSRF (no tokens) | A01:2021 | Intentionally unchanged |

### 2.3 Explicit Non-Goals

- This fix does **not** add rate limiting, CSRF protection, output escaping, or any other control. It hardens the session signing secret; nothing else.
- This fix does **not** change the session cookie's other attributes (name, `max_age`, `same_site`, `https_only`); only the `secret_key` source changes.
- This fix does **not** add a `.env` file or a new dependency (e.g. `python-dotenv`). The secret is read from the process environment using the standard library only.
- This fix does **not** change the database schema, the on-disk database file, or any route's behavior.

---

## 3. Affected Files

The fix MUST touch only the following file (plus the two specification documents). No other repository file may be created or modified.

| Path | Change Type | Purpose |
|------|-------------|---------|
| `backend/app/main.py` | Modified | Add `import secrets`; source `SECRET_KEY` from the environment with a strong random fallback |

Files that MUST NOT be modified by this change:

- `backend/app/api/routes/auth.py` (unescaped `{{username}}` / `q` reflection — preserves Stored & Reflected XSS).
- `backend/app/services/auth_service.py` (stays bcrypt + parameterized; SQL Injection already closed).
- `backend/app/core/security.py` (bcrypt — stays closed).
- `backend/app/db/session.py` (schema and connection layer — untouched).
- Any HTML template under `frontend/templates/` or CSS under `frontend/static/`.
- `CLAUDE.md`, `README.md`, `docs/PRD.md`, `docs/TDD.md`, `.claude/specs/app-foundation.md`.
- `pyproject.toml` / `backend/pyproject.toml` / `uv.lock` (no dependency change — `secrets` is stdlib).

---

## 4. Functional Requirements

### FR-01: Secret Sourced from Environment

- `SECRET_KEY` MUST be read from the `SECRET_KEY` environment variable when it is set and non-empty.
- When the variable is set, that value MUST be the one passed to `SessionMiddleware`.

### FR-02: Strong Random Fallback

- When the `SECRET_KEY` environment variable is **not** set, the application MUST generate a strong random key at startup using `secrets.token_hex(32)` (256 bits of entropy).
- The fallback key MUST be generated once at import time and reused for the lifetime of the process.

### FR-03: No Hardcoded Secret Remains

- The literal `"super-secret-key-12345"` MUST be removed from the codebase.
- No other hardcoded session secret may be introduced in its place.

### FR-04: Middleware Wiring Unchanged

- The `app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)` call MUST remain, consuming the new `SECRET_KEY` value.
- No other middleware parameters are added or removed.

### FR-05: Standard-Library Only

- The fix MUST use only the Python standard library (`os`, `secrets`). No third-party dependency is added.

---

## 5. Non-Functional Requirements

### NFR-01: Surgical Scope

- Exactly one vulnerability (Session Hijacking) is closed. The diff MUST NOT touch the XSS surfaces, the SQL construction, rate limiting, or CSRF posture.

### NFR-02: Secure by Default

- With no configuration, the application MUST start with an unpredictable secret. A fresh checkout that is simply run MUST NOT fall back to any known or guessable key.

### NFR-03: Zero-Config Local Boot

- The application MUST still boot via `uv run backend/app/main.py` with no environment variable set and no error. (Sessions will not persist across restarts in this mode; this is acceptable and documented in §11.)

### NFR-04: No Behavioral Regression

- Within a single process run, login, session persistence across requests, `/welcome` access, and `/logout` MUST behave exactly as before.

---

## 6. Success Paths

### SP-01: Deployment with Env Secret

1. Operator sets `SECRET_KEY` to a strong secret in the environment.
2. The app boots and signs session cookies with that secret.
3. Sessions remain valid across restarts because the same secret is supplied each time.

### SP-02: Local Lab Boot (No Env Secret)

1. A student runs `uv run backend/app/main.py` with no `SECRET_KEY` set.
2. The app generates a fresh `secrets.token_hex(32)` key and boots normally.
3. Login, `/welcome`, and `/logout` all work within that process run.

---

## 7. Edge Cases

### EC-01: Empty Env Variable

- If `SECRET_KEY` is set but empty (`""`), the fallback behavior is governed by `os.environ.get`, which returns the empty string. Operators MUST treat an empty value as "unset"; for the lab, the recommended invocation is to leave it unset (random fallback) or set a non-empty value. (A non-empty operator secret is the supported production path; an intentionally-empty value is an operator error, not a supported mode.)

### EC-02: Restart Without Env Secret Invalidates Old Cookies

- When running with the random fallback, restarting the process generates a new key, so previously-issued session cookies no longer validate and users must log in again. This is expected and is the documented trade-off of the zero-config mode.

### EC-03: No Import-Time Regression

- Adding `import secrets` and changing the assignment MUST NOT affect module import order or any other symbol. The server starts normally (NFR-03).

---

## 8. Acceptance Criteria

### AC-01: Hardcoded Secret Gone

- `grep -n 'super-secret-key-12345' backend/app/main.py` returns no matches.

### AC-02: Env-Sourced with Random Fallback

- `backend/app/main.py` contains `os.environ.get("SECRET_KEY", secrets.token_hex(32))` (or equivalent) and `import secrets`.

### AC-03: Application Boots (No Env Var)

- The app starts via `uv run backend/app/main.py` with no `SECRET_KEY` set, with no `ImportError`, `NameError`, or traceback.

### AC-04: Session Flow Works Within a Run

- signup → login → `/welcome` works in a single process run; `/welcome` still redirects anonymous users to `/login`; `/logout` clears the session.

### AC-05: Other Vulnerabilities Preserved

- Reflected XSS: `/search?q=<script>alert(1)</script>` still reflects the payload unescaped.
- Stored XSS: a user registered with `<script>` in the username still triggers script execution on `/welcome`.
- SQL Injection: already closed (parameterized) and stays closed.
- Exposed Database endpoint: already closed (route removed) and stays closed.
- No Rate Limiting: no throttling middleware was added.
- CSRF: no CSRF token field was added to the login or signup form.

### AC-06: Only `main.py` Modified

- `git status --porcelain` shows `backend/app/main.py` as the only modified source file (plus the two new spec documents under `.claude/specs/`).

---

## 9. Test Cases

| ID | Scenario | Precondition | Expected Result |
|----|----------|--------------|-----------------|
| TC-01 | Hardcoded secret removed | Repo checkout | `grep 'super-secret-key-12345' backend/app/main.py` returns no matches |
| TC-02 | Env-sourced with fallback present | Repo checkout | `main.py` contains `os.environ.get("SECRET_KEY", secrets.token_hex(32))` and `import secrets` |
| TC-03 | App boots with no env var | Fresh checkout, `SECRET_KEY` unset | `uv run backend/app/main.py` starts with no traceback |
| TC-04 | App boots with env var | `SECRET_KEY=somestrongvalue` set | App starts; sessions signed with that value |
| TC-05 | Full auth flow works | Empty DB, single run | signup → login returns success JSON; `/welcome` shows dashboard |
| TC-06 | Anonymous redirect preserved | App running | `GET /welcome` with no session → redirect to `/login` |
| TC-07 | Logout clears session | Logged-in session | `GET /logout` → redirect to `/login`; `/welcome` then redirects to `/login` |
| TC-08 | Reflected XSS preserved | App running | `GET /search?q=<script>alert(1)</script>` reflects payload unescaped |
| TC-09 | Stored XSS preserved | User with `<script>` username | `/welcome` renders the script unescaped |
| TC-10 | SQL injection stays closed | Repo checkout | `auth_service.py` uses `WHERE username = ?` (parameterized) |
| TC-11 | Exposed DB stays closed | App running | `GET /download/db` → HTTP 404 |
| TC-12 | No CSRF tokens added | App running | `/login` and `/signup` HTML contain no `csrf_token` field |
| TC-13 | Affected-files audit | After change | `git status --porcelain` shows only `main.py` modified plus the two new spec docs |

---

## 10. Verification Steps

Run from the repository root.

### 10.1 Confirm the Hardcoded Secret Is Gone (AC-01, TC-01)

```bash
grep -n 'super-secret-key-12345' backend/app/main.py || echo '(hardcoded secret removed)'
```

Expected: `(hardcoded secret removed)`.

### 10.2 Confirm the New Secret Source (AC-02, TC-02)

```bash
grep -n 'import secrets' backend/app/main.py
grep -n 'os.environ.get("SECRET_KEY"' backend/app/main.py
```

Expected: both lines present.

### 10.3 Start the Application With No Env Var (AC-03, TC-03)

```bash
uv run backend/app/main.py
```

The server listens on `http://localhost:3001` with no import/boot error.

### 10.4 Start the Application With an Env Var (TC-04)

```bash
SECRET_KEY=a-strong-operator-secret uv run backend/app/main.py
```

Expected: app starts normally; cookies are signed with the provided secret.

### 10.5 Confirm Full Auth Flow (AC-04, TC-05–TC-07)

```bash
curl -s -c jar.txt -X POST http://localhost:3001/signup \
     --data-urlencode 'username=alice' --data-urlencode 'email=alice@test.com' --data-urlencode 'password=pass123'
curl -s -c jar.txt -b jar.txt -X POST http://localhost:3001/login \
     --data-urlencode 'username=alice' --data-urlencode 'password=pass123'
curl -s -b jar.txt -o /dev/null -w 'welcome=%{http_code}\n' http://localhost:3001/welcome
curl -s -o /dev/null -w 'welcome_anon=%{http_code}\n' http://localhost:3001/welcome
```

Expected: login returns `{"success": true, "redirect": "/welcome"}`; `welcome=200` with the session cookie; `welcome_anon=307/302` redirect for the anonymous request.

### 10.6 Vulnerability Preservation Walkthrough (AC-05, TC-08–TC-12)

```bash
# Reflected XSS still fires (TC-08)
curl -s 'http://localhost:3001/search?q=<script>alert(1)</script>' | grep -o '<script>alert(1)</script>'

# SQL injection stays closed — parameterized (TC-10)
grep -n 'WHERE username = ?' backend/app/services/auth_service.py

# Exposed DB stays closed (TC-11)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3001/download/db   # expect 404

# No CSRF tokens (TC-12)
curl -s http://localhost:3001/login  | grep -i csrf || echo '(no csrf field — preserved)'
curl -s http://localhost:3001/signup | grep -i csrf || echo '(no csrf field — preserved)'
```

### 10.7 Affected-Files Audit (AC-06, TC-13)

```bash
git status --porcelain
```

Expected: `backend/app/main.py` modified, plus the two new files
`.claude/specs/session-hijacking-fix.md` and `.claude/specs/session-hijacking-fix-plan.md`. No other path.

---

## 11. Operational Note

After this change, the session signing secret is no longer baked into the source.

- **Production / shared deployments:** set `SECRET_KEY` in the environment to a strong, secret value (for example `python -c "import secrets; print(secrets.token_hex(32))"`). Supplying the same value on every start keeps existing sessions valid across restarts.
- **Local lab use:** run with no `SECRET_KEY` set. The app generates a fresh random key each start. The only visible effect is that sessions do not survive a restart — users simply log in again. There is no migration and no data change; only the secret source has changed.
