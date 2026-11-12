
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
MAIN = APP / "main.py"

source = MAIN.read_text()
lines = source.splitlines(keepends=True)
tree = ast.parse(source)

nodes = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.ClassDef))
}

required = [
    "get_db", "get_current_user",
    "LoginRequest", "login", "my_profile", "logout"
]

missing = [name for name in required if name not in nodes]
if missing:
    raise SystemExit(f"Missing functions/classes: {missing}")

targets = [
    APP / "core" / "database.py",
    APP / "core" / "security.py",
    APP / "routers" / "auth.py"
]

if any(path.exists() for path in targets):
    raise SystemExit(
        "A target module already exists. "
        "Check it before running this migration."
    )

if "app.include_router(auth_router)" in source:
    raise SystemExit("Authentication router already registered")


def extract(name):
    node = nodes[name]
    start = min(
        [node.lineno] +
        [decorator.lineno for decorator in node.decorator_list]
    )
    return "".join(lines[start - 1:node.end_lineno]).strip()


database_code = '''import sqlite3
from pathlib import Path

DB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "hospital.db"
)

''' + extract("get_db") + "\n"

security_code = '''import hashlib
from contextlib import closing
from datetime import datetime, timezone

from fastapi import HTTPException
from app.core.database import get_db

''' + extract("get_current_user") + "\n"

auth_imports = '''import hashlib
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import (
    VerifyMismatchError, VerificationError
)
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.database import get_db
from app.core.security import get_current_user

router = APIRouter()
password_hasher = PasswordHasher()
SESSION_COOKIE = "hospital_session"

'''

auth_parts = [extract("LoginRequest")]

for name in ["login", "my_profile", "logout"]:
    function_source = extract(name)
    function_source = function_source.replace(
        "@app.", "@router.", 1
    )
    auth_parts.append(function_source)

auth_code = auth_imports + "\n\n".join(auth_parts) + "\n"

# Remove moved definitions from main.py.
removed_lines = set()

for name in required:
    node = nodes[name]
    start = min(
        [node.lineno] +
        [decorator.lineno for decorator in node.decorator_list]
    )
    removed_lines.update(range(start, node.end_lineno + 1))

# These authentication constants now live in routers/auth.py.
for node in tree.body:
    if isinstance(node, ast.Assign):
        names = [
            target.id
            for target in node.targets
            if isinstance(target, ast.Name)
        ]
        if any(name in names for name in [
            "password_hasher", "SESSION_COOKIE"
        ]):
            removed_lines.update(
                range(node.lineno, node.end_lineno + 1)
            )

updated_main = "".join(
    line
    for number, line in enumerate(lines, start=1)
    if number not in removed_lines
)

# Bring the extracted functions back through imports.
updated_main = (
    "from app.core.database import get_db\n"
    "from app.core.security import get_current_user\n"
    "from app.routers.auth import router as auth_router\n\n"
    + updated_main
)

updated_main += "\n\napp.include_router(auth_router)\n"

# Validate all resulting source before replacing the original.
for filename, content in [
    ("database.py", database_code),
    ("security.py", security_code),
    ("auth.py", auth_code),
    ("main.py", updated_main),
]:
    ast.parse(content, filename=filename)

# Save a local source backup.
backup = ROOT / "main_before_refactor.py.bak"
backup.write_text(source)

(APP / "core" / "database.py").write_text(database_code)
(APP / "core" / "security.py").write_text(security_code)
(APP / "routers" / "auth.py").write_text(auth_code)
MAIN.write_text(updated_main)

print("Authentication refactoring completed.")
print("Created app/core/database.py")
print("Created app/core/security.py")
print("Created app/routers/auth.py")
print("Updated app/main.py")
print("Backup:", backup)
