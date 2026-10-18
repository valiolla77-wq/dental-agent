"""Initialize process-wide test configuration before test module imports.

``unittest discover`` imports matching test modules in lexical path order. This
module therefore runs before modules that import ``app.database``, whose engine
is configured when it is imported. Keeping this setup in ``tests`` avoids
changing the production database default.
"""

import os
import unittest


os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32-chars-long")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault(
    "CONFIRMATION_HMAC_SECRET",
    "test-confirmation-hmac-secret-32-chars-long",
)


class TestEnvironmentInitialization(unittest.TestCase):
    def test_database_uses_in_memory_default(self) -> None:
        from app.database import DATABASE_URL

        self.assertEqual(DATABASE_URL, "sqlite+aiosqlite:///:memory:")
