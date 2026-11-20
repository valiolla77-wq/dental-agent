"""Securely store the agent-LLM API key in the local ``.env`` file.

Works for every OpenAI-compatible provider configured via
``AGENT_LLM_BASE_URL`` (LM Studio, AvalAI, vLLM, llama.cpp, ...).

The key is read with a hidden prompt (never echoed, never passed as a command
line argument) and written to the git-ignored ``.env``. By default the key is
verified with a read-only ``GET {base_url}/models`` call first; nothing is
saved when the endpoint rejects it.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\set_llm_key.py
    .\\.venv\\Scripts\\python.exe scripts\\set_llm_key.py --no-verify

Options:
    --env-file PATH   Target env file (default: <project root>/.env)
    --base-url URL    Override the endpoint instead of reading it from .env
    --no-verify       Store without contacting the provider (offline use)
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_env(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), had_bom


def _write_env(path: Path, text: str, had_bom: bool) -> None:
    encoded = text.encode("utf-8-sig" if had_bom else "utf-8")
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(encoded)
    os.replace(temp, path)


def _upsert(text: str, var_name: str, value: str) -> str:
    """Replace every ``VAR=`` line, or append it when absent."""
    lines = text.splitlines(keepends=True)
    pattern = re.compile(rf"^\s*{re.escape(var_name)}\s*=")
    found = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            ending = ""
            if line.endswith("\r\n"):
                ending = "\r\n"
            elif line.endswith("\n"):
                ending = "\n"
            lines[index] = f"{var_name}={value}{ending}"
            found = True
    if not found:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] = lines[-1] + "\n"
        lines.append(f"{var_name}={value}\n")
    return "".join(lines)


def _base_url(env_path: Path, override: str | None) -> str:
    if override:
        return override.strip().rstrip("/")
    match = re.search(r"^AGENT_LLM_BASE_URL\s*=\s*(\S+)", env_path.read_text(encoding="utf-8-sig"), re.M)
    if match:
        return match.group(1).strip().rstrip("/")
    return ""


def _verify(base_url: str, key: str) -> bool | None:
    """Read-only model-list check. Returns None when the network is unavailable."""
    if not base_url:
        print("AGENT_LLM_BASE_URL در .env تنظیم نشده؛ ابتدا آن را مقدارده کنید.")
        return False
    try:
        import httpx
    except ImportError:
        print("httpx نصب نیست؛ ابتدا pip install -r requirements.txt را اجرا کنید.")
        return False
    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=20,
        )
    except Exception:
        print(f"ارتباط با {base_url} برقرار نشد (شبکه/فایروال).")
        return None
    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        entries = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(entries, list) and entries:
            names = [str(item.get("id", "?")) for item in entries[:12] if isinstance(item, dict)]
            print(f"کلید پذیرفته شد؛ {len(entries)} مدل روی این endpoint موجود است.")
            print("چند نمونه: " + "، ".join(names))
            print("(برای انتخاب مدل، AGENT_LLM_MODEL را در .env بگذارید.)")
        else:
            print("کلید پذیرفته شد (endpoint فهرست مدل استاندارد بازنگرداند).")
        return True
    hint = {401: "کلید نامعتبر/نپذیرفته‌شده", 403: "کلید بدون دسترسی"} .get(
        response.status_code, "پاسخ غیرمنتظره"
    )
    print(f"endpoint کلید را نپذیرفت (HTTP {response.status_code} — {hint}).")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Store the agent-LLM API key in .env")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="target env file (default: project .env)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="provider base URL (default: AGENT_LLM_BASE_URL from .env)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="save without checking the key against the provider",
    )
    args = parser.parse_args()

    env_path: Path = args.env_file
    if not env_path.exists():
        print(f"فایل پیدا نشد: {env_path}")
        print("ابتدا از .env.example یک .env بسازید.")
        return 1

    base_url = _base_url(env_path, args.base_url)

    key = getpass.getpass("API key تأمین‌کننده مدل (تایپ آن دیده نمی‌شود): ").strip()
    if not key or any(char.isspace() for char in key):
        print("کلید خالی یا دارای فاصله است؛ چیزی ذخیره نشد.")
        return 1
    if not key.isascii():
        print("کلید باید فقط کاراکترهای ASCII داشته باشد؛ چیزی ذخیره نشد.")
        return 1

    if not args.no_verify:
        result = _verify(base_url, key)
        if result is False:
            print("کلید ذخیره نشد. یک کلید تازه بسازید و دوباره اجرا کنید.")
            return 1
        if result is None:
            print("برای ذخیره بدون بررسی شبکه، با --no-verify دوباره اجرا کنید.")
            return 1

    text, had_bom = _read_env(env_path)
    _write_env(env_path, _upsert(text, "AGENT_LLM_API_KEY", key), had_bom)

    print(f"کلید در {env_path} ذخیره شد (مقدار آن نمایش داده نشد).")
    print("سرور را دوباره اجرا کنید تا تنظیمات خوانده شوند.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
