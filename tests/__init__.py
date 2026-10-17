"""Test package initialization.

Sets DATABASE_URL before any test module imports app.database so the
in-memory SQLite engine is used for all tests instead of the default
file-based dental_agent.db.

This is necessary because unittest discover imports test modules
alphabetically, and test_agent_graph.py imports app.agent → app.auth
→ app.database before test_auth.py gets a chance to set DATABASE_URL.
"""

import os

# Must be set before any module imports app.database, because
# app.database creates its async engine at import time from this env var.
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# Ensure consistent test defaults for JWT as well.
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32-chars-long")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
