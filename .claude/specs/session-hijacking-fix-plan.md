# Implementation Plan — Session Hijacking Fix (Secret Key Hardening)

**Version:** 1.0.0
**Last Updated:** June 13, 2026
**Parent Spec:** [session-hijacking-fix.md](./session-hijacking-fix.md)
**Foundation Spec:** [app-foundation.md](./app-foundation.md)
**Parent Documents:** [PRD.md](../../docs/PRD.md), [TDD.md](../../docs/TDD.md)
**Tracking Issue:** [Session Hijacking — hardcoded session secret](https://github.com/arifpucit/vuln-web-app/issues)

---

## 0. Plan Overview

This plan implements the fix specified in [session-hijacking-fix.md](./session-hijacking-fix.md). It closes the **Session Hijacking** vulnerability and **only** that vulnerability, by replacing the hardcoded session secret in `backend/app/main.py` with a secret sourced from the `SECRET_KEY` environment variable, falling back to a strong random key (`secrets.token_hex(32)`) when the variable is unset. The work is split into **three phases** so the change is small, individually verifiable, and easy to revert.

The other intentional vulnerabilities (Stored XSS, Reflected XSS, No Rate Limiting, CSRF) MUST remain exploitable after every phase, and the already-closed fixes (bcrypt password hashing, SQL injection, exposed-DB endpoint) stay closed. Each phase ends with an explicit "MUST NOT" callout listing things that would silently alter another vulnerability.

### Phase Summary

| # | Phase | Files Touched | Goal |
|---|-------|--------------|------|
| 1 | Replace the hardcoded secret in `main.py` | `backend/app/main.py` | `SECRET_KEY` sourced from env with strong random fallback; no hardcoded secret left |
| 2 | End-to-end verification | None (read-only) | Walk every Verification Step in spec §10 |
| 3 | Vulnerability preservation audit | None (read-only) | Confirm the other vulnerabilities still fire |

### Files Modified (Authored)

Exactly the one source file declared in spec §3:

- `backend/app/main.py`

No dependency change (`secrets` is in the standard library), so no `pyproject.toml` or `uv.lock` edit (and no `uv sync`).

### Files That MUST NOT Be Modified

- `backend/app/api/routes/auth.py` — preserves the `{{username}}` Stored XSS and the `/search` Reflected XSS paths.
- `backend/app/services/auth_service.py` — SQL injection already closed (parameterized); do not revert or alter.
- `backend/app/core/security.py` — bcrypt stays; do not revert.
- `backend/app/db/session.py` — schema and connection layer; untouched.
- Any HTML template or CSS — preserves the XSS surfaces.
- `CLAUDE.md`, `README.md`, `docs/PRD.md`, `docs/TDD.md`, `.claude/specs/app-foundation.md`, and this spec/plan pair.

### Vulnerability Preservation Checklist (Carry Through Every Phase)

After the edit, re-confirm:

1. **SQL Injection.** Already CLOSED — `auth_service.py` uses parameterized queries (`WHERE username = ?`). Not touched by this plan; stays closed.
2. **Stored XSS.** `auth.py:welcome_page()` still does `html.replace('{{username}}', username)` — not touched.
3. **Reflected XSS.** `/search` still interpolates `q` into HTML unescaped — not touched.
4. **Session Hijacking.** **This is the only vulnerability being closed.** After Phase 1, the hardcoded secret is gone.
5. **Weak Password (bcrypt).** `security.py` still uses bcrypt; no MD5 re-introduced — not touched.
6. **Exposed Database endpoint.** Already CLOSED — `/download/db` route removed. Not touched; stays closed.
7. **No Rate Limiting.** No throttling middleware added — not touched.
8. **CSRF.** No CSRF token field or middleware added — not touched.

---

## Phase 1 — Replace the Hardcoded Secret

### 1.1 Goal

Source the session signing secret from the environment with a strong random fallback, so no usable secret is committed to the repository. All edits are confined to `main.py`.

### 1.2 File to Modify

- `backend/app/main.py`

### 1.3 Edit A — Add the `secrets` import

**Before** (L1–2):

```python
import sys
import os
```

**After**:

```python
import sys
import os
import secrets
```

`os` is already imported (used for `sys.path` and `PORT`); `secrets` is the standard-library CSPRNG used for the fallback key.

### 1.4 Edit B — Replace the hardcoded secret assignment

**Before** (L17–18):

```python
# VULNERABILITY #4: Session Hijacking -- hardcoded weak secret key
SECRET_KEY = "super-secret-key-12345"
```

**After**:

```python
# FIXED: Session Hijacking closed -- secret loaded from the environment,
# with a strong random fallback so a fresh checkout never ships a known key.
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
```

The `app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)` line on L19 is **left unchanged** — it continues to consume `SECRET_KEY`.

### 1.5 Edit Summary

Two edits inside `main.py`:

1. Add `import secrets`.
2. Replace the `SECRET_KEY = "super-secret-key-12345"` line (and its `VULNERABILITY #4` comment) with the env-sourced assignment.

No other line in the file changes. The `add_middleware` call, the router include, the static mounts, `init_db()`, and the `__main__` block are all untouched.

### 1.6 What NOT to Change in Phase 1

- **DO NOT** keep the old secret as a fallback (e.g. `os.environ.get("SECRET_KEY", "super-secret-key-12345")`). The fallback MUST be a fresh random key; a known fallback would leave the vulnerability open (spec FR-02, FR-03, NFR-02).
- **DO NOT** add a `.env` file or `python-dotenv`. The secret is read from the process environment using the standard library only (spec §2.3, FR-05).
- **DO NOT** change the `SessionMiddleware` wiring or add other cookie parameters (`max_age`, `same_site`, `https_only`). Only the secret source changes (spec §2.3).
- **DO NOT** touch any other handler, mount, or the database init.
- **DO NOT** edit `auth.py`, `auth_service.py`, `security.py`, `session.py`, templates, CSS, or any pyproject/lock file.

### 1.7 Phase 1 Verification (Pre-Server)

```bash
grep -n 'super-secret-key-12345' backend/app/main.py || echo '(hardcoded secret removed)'
grep -n 'import secrets' backend/app/main.py
grep -n 'os.environ.get("SECRET_KEY"' backend/app/main.py
cd backend && uv run python -c "import app.main; print('import ok')" && cd ..
```

Expected: the first grep prints `(hardcoded secret removed)`; the next two print the new lines; the import smoke test prints `import ok`.

---

## Phase 2 — End-to-End Verification

This phase walks every Verification Step in spec §10 in order. **No edits** are made; if a step fails, return to Phase 1 to repair.

### 2.1 Hardcoded Secret Gone (spec §10.1 — AC-01, TC-01)

```bash
grep -n 'super-secret-key-12345' backend/app/main.py || echo '(hardcoded secret removed)'
```

Expected: `(hardcoded secret removed)`.

### 2.2 New Secret Source Present (spec §10.2 — AC-02, TC-02)

```bash
grep -n 'import secrets' backend/app/main.py
grep -n 'os.environ.get("SECRET_KEY"' backend/app/main.py
```

Expected: both lines present.

### 2.3 App Boots With No Env Var (spec §10.3 — AC-03, TC-03)

```bash
uv run backend/app/main.py
```

Confirm the server boots with no traceback and `http://localhost:3001/login` responds 200. Stop it (`Ctrl+C`) before the next step.

### 2.4 App Boots With an Env Var (spec §10.4 — TC-04)

```bash
SECRET_KEY=a-strong-operator-secret uv run backend/app/main.py
```

Expected: app starts normally; cookies are signed with the provided secret. Stop it before continuing.

### 2.5 Full Auth Flow (spec §10.5 — AC-04, TC-05–TC-07)

With the app running:

```bash
curl -s -c jar.txt -X POST http://localhost:3001/signup \
     --data-urlencode 'username=alice' --data-urlencode 'email=alice@test.com' --data-urlencode 'password=pass123'
curl -s -c jar.txt -b jar.txt -X POST http://localhost:3001/login \
     --data-urlencode 'username=alice' --data-urlencode 'password=pass123'
curl -s -b jar.txt -o /dev/null -w 'welcome=%{http_code}\n' http://localhost:3001/welcome
curl -s -o /dev/null -w 'welcome_anon=%{http_code}\n' http://localhost:3001/welcome
curl -s -b jar.txt -o /dev/null -w 'logout=%{http_code}\n' http://localhost:3001/logout
```

Expected: login returns success JSON; `welcome=200` with the session cookie; `welcome_anon` is a redirect (307/302); `logout` is a redirect to `/login`.

### 2.6 Affected-Files Audit (spec §10.7 — AC-06, TC-13)

```bash
git status --porcelain
```

Expected: `backend/app/main.py` modified, plus the two new spec docs. No other path.

---

## Phase 3 — Vulnerability Preservation Audit

Read-only confirmation that the other intentional vulnerabilities still fire and that the already-closed ones stay closed.

### 3.1 Reflected XSS (AC-05, TC-08)

```bash
curl -s 'http://localhost:3001/search?q=<script>alert(1)</script>' | grep -o '<script>alert(1)</script>'
```

Expected: the literal payload is printed back (reflected unescaped).

### 3.2 Stored XSS (AC-05, TC-09)

```bash
curl -s -X POST http://localhost:3001/signup \
     --data-urlencode 'username=<img src=x onerror=alert(1)>' \
     --data-urlencode 'email=xss@x' --data-urlencode 'password=p'
```

Then log in as that user and visit `/welcome` in a browser — the unescaped markup renders.

### 3.3 SQL Injection Stays Closed (AC-05, TC-10)

```bash
grep -n 'WHERE username = ?' backend/app/services/auth_service.py
```

Expected: the parameterized query is present (SQLi remains closed).

### 3.4 Exposed Database Stays Closed (AC-05, TC-11)

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3001/download/db
```

Expected: `404` (route removed, stays removed).

### 3.5 No Rate Limiting (AC-05)

```bash
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3001/login \
       --data-urlencode 'username=ghost' --data-urlencode "password=$i"
done | sort -u
```

Expected: only `401` appears — no `429`, no throttling.

### 3.6 No CSRF (AC-05, TC-12)

```bash
curl -s http://localhost:3001/login  | grep -i csrf || echo '(no csrf field — preserved)'
curl -s http://localhost:3001/signup | grep -i csrf || echo '(no csrf field — preserved)'
```

Expected: each prints `(no csrf field — preserved)`.

### 3.7 Spec Acceptance Criteria Roll-Up

- [ ] AC-01 Hardcoded Secret Gone (Phase 2.1)
- [ ] AC-02 Env-Sourced with Random Fallback (Phase 1.7, Phase 2.2)
- [ ] AC-03 Application Boots — No Env Var (Phase 2.3)
- [ ] AC-04 Session Flow Works Within a Run (Phase 2.5)
- [ ] AC-05 Other Vulnerabilities Preserved (Phase 3.1–3.6)
- [ ] AC-06 Only `main.py` Modified (Phase 2.6)

### 3.8 Stop the Server

`Ctrl+C` to stop. Plan complete.

---

## Risk Log & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Keeping the old secret as the fallback (`os.environ.get("SECRET_KEY", "super-secret-key-12345")`) — leaves the vulnerability fully open | Medium | High | Spec FR-02/FR-03 + Phase 1.6 "MUST NOT"; Phase 2.1 grep catches a residual literal |
| Using a weak/insufficient-entropy fallback (e.g. a short token) | Low | Medium | Spec FR-02 mandates `secrets.token_hex(32)` (256 bits); Phase 2.2 grep confirms |
| Forgetting `import secrets` — `NameError` at startup | Low | Medium | Phase 1.3 adds it; Phase 1.7 import smoke test catches a missing import |
| Adding a `.env`/`python-dotenv` dependency — scope creep + lockfile change | Low | Medium | Spec §2.3 + Phase 1.6 "MUST NOT"; Phase 2.6 affected-files audit catches stray edits |
| Touching `auth.py`/templates "while in here" — re-escapes XSS or alters another vuln | Low | High | MUST-NOT list; Phase 3.1/3.2 confirm XSS still fires; Phase 2.6 file audit |

---

## Rollback Procedure

If verification fails and cannot be repaired quickly:

```bash
git restore backend/app/main.py
```

The single authored file snaps back to its pre-fix state. No dependency, schema, or data migration is involved.

---

## Out-of-Band: What This Plan Deliberately Does NOT Do

- **No known fallback secret.** The fallback is a fresh random key per process start; the old literal is removed entirely.
- **No `.env` file or new dependency.** The secret is read from the process environment using the standard library (`os`, `secrets`).
- **No cookie-attribute changes.** Only the `secret_key` source changes; `SessionMiddleware` wiring is otherwise identical.
- **No change to other vulnerabilities.** Stored XSS, Reflected XSS, No Rate Limiting, and CSRF all remain. bcrypt, SQL-injection, and exposed-DB fixes stay closed.
- **No dependency change.** No `pyproject.toml`/`uv.lock` edit, no `uv sync`.
- **No new file** beyond this spec/plan pair.
