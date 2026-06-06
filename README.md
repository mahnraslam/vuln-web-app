# Vulnerable Web Application

An intentionally vulnerable web application designed to teach common security vulnerabilities through hands-on exploitation. Rather than studying vulnerabilities in theory, you'll exploit them in a working application to understand how real attacks work.

**Warning:** This application is deliberately insecure. It is designed for educational use only and should never be deployed to production or used on systems you do not own.

---

## Overview

This project contains a fully functional authentication system with 8 intentional security flaws:

| # | Vulnerability | Description |
|---|---|---|
| 1 | SQL Injection | Database queries built from raw user input |
| 2 | Stored XSS | Persistent JavaScript injected via the username field |
| 3 | Reflected XSS | JavaScript injected through URL query parameters |
| 4 | Session Hijacking | Weak hardcoded session secret key |
| 5 | Weak Password Storage | Passwords hashed with broken MD5 algorithm |
| 6 | Exposed Database Endpoint | Unauthenticated route serves the full SQLite database file |
| 7 | No Rate Limiting | Unlimited login attempts — no lockout or throttling |
| 8 | CSRF | No CSRF tokens on any form |

Built with FastAPI and SQLite — simple enough to read in one sitting, realistic enough to demonstrate actual attack techniques.

---

## Getting Started

### Prerequisites

- Python 3.9 or later
- Git (optional, for cloning)

### Installation

Clone the repository and enter the project folder:
```powershell
git clone <repository-url>
cd "vuln-app-cc"
```

Navigate to the backend directory and install dependencies:
```powershell
cd backend
pip install uv
uv sync
```

Activate the virtual environment:

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

### Running the Application

From the `backend/` directory:
```powershell
python app/main.py
```

Or from the project root:
```powershell
python backend/app/main.py
```

The app starts on `http://localhost:3001`. Open that URL to reach the login page.

---

## Project Structure

```
vuln-app-cc/
├── README.md
├── .gitignore
├── docs/
│   └── EXPLOITS.md         Step-by-step exploitation guide for all 8 vulnerabilities
│
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  Entry point — starts the server
│       ├── core/
│       │   └── security.py          Password hashing (MD5)
│       ├── db/
│       │   └── session.py           Database connection and schema setup
│       ├── services/
│       │   └── auth_service.py      Business logic for signup and login
│       └── api/
│           └── routes/
│               └── auth.py          All HTTP route handlers
│
└── frontend/
    ├── static/
    │   ├── css/
    │   │   └── styles.css
    │   └── images/
    │       ├── PUCIT_Logo.png
    │       ├── blue-logo-scl2.png
    │       └── excaliat-logo.png
    └── templates/
        ├── login.html
        ├── signup.html
        └── dashboard.html
```

---

## Learning Path

1. **Read the exploitation guide** — `docs/EXPLOITS.md` walks through each vulnerability with step-by-step attack instructions. No prior security knowledge needed.

2. **Explore the code** — After exploiting a vulnerability, find it in the source.

3. **Fix it** — Patch each vulnerability using secure coding practices: parameterized queries, output escaping, strong password hashing, rate limiting, and CSRF tokens.

---

## Useful Commands

Check the database contents:
```powershell
cd "D:\BSDS\8th Semester\Projects\Vulnerable app"
.venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect('vulnerable_app.db'); [print(r) for r in conn.execute('SELECT * FROM users').fetchall()]; conn.close()"
```

Install or update dependencies:
```powershell
cd backend
uv sync
```

Test the app is running:
```powershell
curl http://localhost:3001
```

---

## Technology Stack

- **Backend:** FastAPI + Uvicorn
- **Database:** SQLite3
- **Frontend:** HTML / CSS (no framework)
- **Python:** 3.9+

---

## Troubleshooting

**`python command not found`**
Install Python 3.9+ from https://www.python.org/downloads/

**`uv command not found`**
Run `pip install uv`

**`Port 3001 already in use`**
Find and kill the process using port 3001:
```powershell
Get-NetTCPConnection -LocalPort 3001 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

**`No such file or directory: main.py`**
You are running from the wrong directory. Run `python app/main.py` from `backend/`, not `python main.py`.

**`ModuleNotFoundError: No module named 'app'`**
Run the app as `python app/main.py` from the `backend/` directory — not `python app/main.py` from the project root, and not `python main.py`.

**`401 Unauthorized` on login after fresh install**
The database may contain users created before password hashing was added. Delete `vulnerable_app.db` from the project root and restart — it will be recreated automatically. Then sign up with a new account.

**Virtual environment won't activate**
On Windows, run this first:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Legal Notice

This application is provided strictly for educational purposes. Unauthorized access to computer systems is illegal. Ensure you have explicit permission before testing security vulnerabilities on any system you do not own. The authors are not responsible for misuse of this project.
# vuln-app-cc
