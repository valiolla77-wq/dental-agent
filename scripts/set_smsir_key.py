"""Securely store the SMS.ir API key in the local ``.env`` file.

The key is read with a hidden prompt (never echoed, never passed as a command
line argument) and written to the git-ignored ``.env`` next to the project.
By default the key is verified with a read-only SMS.ir API call first; nothing
is saved when the panel rejects it.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\set_smsir_key.py
    .\\.venv\\Scripts\\python.exe scripts\\set_smsir_key.py --no-verify

Options:
    --env-file PATH   Target env file (default: <project root>/.env)
    --no-verify       Store without contacting SMS.ir (offline use)
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


def _upsert_key(text: str, key: str) -> str:
    """Replace every SMSIR_API_KEY line, or append one when absent."""
    lines = text.splitlines(keepends=True)
    pattern = re.compile(r"^\s*SMSIR_API_KEY\s*=")
    found = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            ending = ""
            if line.endswith("\r\n"):
                ending = "\r\n"
            elif line.endswith("\n"):
                ending = "\n"
            lines[index] = f"SMSIR_API_KEY={key}{ending}"
            found = True
    if not found:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] = lines[-1] + "\n"
        lines.append(f"SMSIR_API_KEY={key}\n")
    return "".join(lines)


def _verify(key: str) -> bool | None:
    """Read-only credit check. Returns None when the network is unavailable."""
    try:
        import httpx
    except ImportError:
        print("httpx نصب نیست؛ ابتدا pip install -r requirements.txt را اجرا کنید.")
        return False
    try:
        response = httpx.get(
            "https://api.sms.ir/v1/credit",
            headers={"X-API-KEY": key, "Accept": "application/json"},
            timeout=15,
        )
        data = response.json()
    except Exception:
        print("ارتباط با SMS.ir برقرار نشد (شبکه/فایروال).")
        return None
    if response.status_code == 200 and isinstance(data, dict) and data.get("status") == 1:
        print(f"کلید معتبر است. اعتبار فعلی پنل: {data.get('data')}")
        return True
    status = data.get("status") if isinstance(data, dict) else "?"
    print(f"SMS.ir این کلید را نپذیرفت (HTTP {response.status_code}، status {status}).")
    return False


def _print_lines(key: str) -> None:
    try:
        import httpx

        response = httpx.get(
            "https://api.sms.ir/v1/line",
            headers={"X-API-KEY": key, "Accept": "application/json"},
            timeout=15,
        )
        data = response.json()
    except Exception:
        return
    if isinstance(data, dict) and data.get("status") == 1:
        lines = data.get("data") or []
        if lines:
            print("خطوط خدماتی فعال روی این پنل:")
            for line in lines:
                print(f"  - {line}")
        else:
            print("هیچ خط خدماتی فعالی روی این پنل پیدا نشد (به قالب تأیید نیاز دارید).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Store the SMS.ir API key in .env")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="target env file (default: project .env)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="save without checking the key against SMS.ir",
    )
    args = parser.parse_args()

    env_path: Path = args.env_file
    if not env_path.exists():
        print(f"فایل پیدا نشد: {env_path}")
        print("ابتدا از .env.example یک .env بسازید.")
        return 1

    key = getpass.getpass("SMS.ir API key (تایپ آن دیده نمی‌شود): ").strip()
    if not key or any(char.isspace() for char in key):
        print("کلید خالی یا دارای فاصله است؛ چیزی ذخیره نشد.")
        return 1
    if not key.isascii():
        print("کلید باید فقط کاراکترهای ASCII داشته باشد؛ چیزی ذخیره نشد.")
        return 1

    if not args.no_verify:
        result = _verify(key)
        if result is False:
            print("کلید ذخیره نشد. از پنل SMS.ir یک کلید تازه بسازید و دوباره اجرا کنید.")
            return 1
        if result is None:
            print("برای ذخیره بدون بررسی شبکه، با --no-verify دوباره اجرا کنید.")
            return 1

    text, had_bom = _read_env(env_path)
    _write_env(env_path, _upsert_key(text, key), had_bom)

    print(f"کلید در {env_path} ذخیره شد (مقدار آن نمایش داده نشد).")
    print("سرور را دوباره اجرا کنید تا تنظیمات خوانده شوند.")
    if not args.no_verify:
        _print_lines(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
