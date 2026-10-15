"""CLI command to bootstrap the first admin user.

This module provides a secure way to create the first admin user without
exposing credentials in command line arguments, logs, or environment variables.
"""

import argparse
import asyncio
import getpass
import sys
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models.user import User
from app.auth.security import hash_password


async def create_admin_user(phone: str, password: str) -> bool:
    """Create the first admin user.

    Args:
        phone: Admin phone number
        password: Admin password (already obtained securely)

    Returns:
        True if admin was created, False if admin already exists
    """
    async with SessionLocal() as db:
        # Check if any admin already exists
        result = await db.execute(select(User).where(User.role == "admin"))
        existing_admin = result.scalar_one_or_none()

        if existing_admin is not None:
            print("Admin user already exists. Bootstrap not allowed.", file=sys.stderr)
            return False

        # Validate phone format (basic)
        if not phone or len(phone) < 10:
            print("Invalid phone number", file=sys.stderr)
            return False

        if not password or len(password) < 8:
            print("Password must be at least 8 characters", file=sys.stderr)
            return False

        # Check if phone already exists
        result = await db.execute(select(User).where(User.phone == phone))
        if result.scalar_one_or_none() is not None:
            print("Phone number already registered", file=sys.stderr)
            return False

        # Create admin user
        admin = User(
            full_name="System Administrator",
            phone=phone,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )

        db.add(admin)
        await db.commit()
        await db.refresh(admin)

        print(f"Admin user created successfully:")
        print(f"  ID: {admin.id}")
        print(f"  Name: {admin.full_name}")
        print(f"  Phone: {admin.phone}")
        print(f"  Role: {admin.role}")
        print(f"  Active: {admin.is_active}")
        return True


def main() -> int:
    """Main entry point for the bootstrap admin CLI command."""
    parser = argparse.ArgumentParser(
        description="Bootstrap the first admin user for Dental Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m app.auth.bootstrap_admin 09123456789\n"
            "  python -m app.auth.bootstrap_admin --phone 09123456789\n"
            "\n"
            "Password will be prompted securely (not echoed to terminal)."
        ),
    )
    parser.add_argument(
        "phone",
        nargs="?",
        help="Admin phone number (e.g., 09123456789)",
    )
    parser.add_argument(
        "--phone",
        dest="phone_opt",
        help="Admin phone number (alternative to positional argument)",
    )

    args = parser.parse_args()

    # Get phone from positional or optional argument
    phone = args.phone or args.phone_opt
    if not phone:
        parser.error("Phone number is required. Provide as positional argument or --phone")

    # Get password securely
    try:
        password = getpass.getpass("Enter admin password: ")
        confirm = getpass.getpass("Confirm admin password: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        return 1

    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    if not password or len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 1

    # Initialize database and create admin
    async def run():
        await init_db()
        success = await create_admin_user(phone, password)
        return 0 if success else 1

    try:
        return asyncio.run(run())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())