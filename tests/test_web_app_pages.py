"""HTTP tests for the clinic web application routes.

The UI served at ``/app`` is the React bundle built from ``webapp/`` (Vite).
If that bundle has not been built yet, the legacy page under ``web/`` is served
instead, and the bundle-specific assertions are skipped. File-serving behavior
is asserted here; UI internals are covered separately, and both UIs must never
ship backend secrets to the browser.
"""

import os
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import _WEBAPP_INDEX_PAGE, app  # noqa: E402

_WEBAPP_ROOT = Path(__file__).resolve().parent.parent / "webapp"
_BUILT = _WEBAPP_INDEX_PAGE.is_file()


class WebAppPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @unittest.skipUnless(_BUILT, "React bundle not built (run: npm run build in webapp/)")
    def test_react_app_is_served_same_origin(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        body = response.text
        for marker in (
            "lang=\"fa\"",
            "dir=\"rtl\"",
            "Dental Agent",
            "id=\"root\"",
            "/app-assets/assets/index-",
        ):
            self.assertIn(marker, body)

    @unittest.skipUnless(_BUILT, "React bundle not built (run: npm run build in webapp/)")
    def test_react_app_assets_are_served(self):
        js_files = list(_WEBAPP_ROOT.glob("dist/assets/index-*.js"))
        css_files = list(_WEBAPP_ROOT.glob("dist/assets/index-*.css"))
        self.assertTrue(js_files and css_files, "hashed JS/CSS bundles exist")
        js_name = js_files[0].name
        css_name = css_files[0].name

        for name in (js_name, css_name):
            response = self.client.get(f"/app-assets/assets/{name}")
            self.assertEqual(response.status_code, 200)
            for secret_marker in (
                "JWT_SECRET",
                "AGENT_LLM_API_KEY",
                "SMSIR_API_KEY",
                "argon2id",
            ):
                self.assertNotIn(secret_marker, response.text)

        js = js_files[0].read_text(encoding="utf-8")
        self.assertIn("/agent/chat", js, "the agent chat endpoint is used by the app")
        self.assertIn("/auth/otp", js, "OTP authentication is used by the app")

    def test_legacy_fallback_page_is_served_when_bundle_missing(self):
        # Deterministic: pretend the React bundle was never built, regardless
        # of whether the developer ran ``npm run build`` on this machine.
        from pathlib import Path
        from unittest.mock import patch

        import app.main as main_module

        missing = Path("/nonexistent/webapp/dist/index.html")
        with patch.object(main_module, "_WEBAPP_INDEX_PAGE", missing):
            response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/app-assets/app.css", response.text)
        legacy = (_WEBAPP_ROOT.parent / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("passwordLoginForm", legacy)
        self.assertIn("otpLoginForm", legacy)

    def test_root_advertises_topics_without_leaking(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["web_app"], "/app")
        self.assertNotIn("demo", payload)
        self.assertNotIn("secret", str(payload).lower())

    def test_legacy_demo_paths_are_gone(self):
        for path in ("/demo", "/demo/"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 404)

    def test_legacy_demo_assets_are_gone(self):
        self.assertEqual(self.client.get("/demo-assets/Vazirmatn-Arabic.woff2").status_code, 404)

    def test_unknown_assets_rejected(self):
        response = self.client.get("/app-assets/../.env")
        self.assertNotIn("JWT_SECRET", response.text)
        response2 = self.client.get("/app-assets/%2e%2e/%2e%2e/.env")
        self.assertNotIn("JWT_SECRET", response2.text)


if __name__ == "__main__":
    unittest.main()
