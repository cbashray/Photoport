#!/usr/bin/env python3
"""
PhotoPort - Account Inspection and Safe Switching Workflow.

Safely inspect the currently authenticated Google account, check its actual
storage quota against required archive size (e.g. 45 GB), and switch accounts
with interactive account selection (`prompt="select_account consent"`).

Security rule: NEVER prints or exposes access tokens, refresh tokens, client secrets,
or upload tokens.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from photoport.google_photos.quota_service import QuotaService, StorageInfo
from photoport.migration.storage_preflight import StoragePreflightService
from photoport.utils.formatting import format_bytes

logger = logging.getLogger("photoport.switch_account")


def display_preflight_audit(preflight_res, target_gb: float) -> None:
    """Display authenticated account details and storage capacity analysis using StoragePreflightService."""
    print("=" * 70)
    print("GOOGLE ACCOUNT IDENTITY & STORAGE AUDIT")
    print("=" * 70)

    storage_info = preflight_res.storage_info
    if not storage_info or not storage_info.available:
        print("Status: NOT AUTHENTICATED OR QUOTA UNKNOWN")
        if storage_info and storage_info.error:
            print(f"Error : {storage_info.error}")
        print("=" * 70)
        return

    email = storage_info.user_email or "Unknown (email not returned by API)"
    name = storage_info.display_name or "Unknown"

    print(f"Authenticated Email : {email}")
    print(f"Display Name        : {name}")
    print("Identity Source     : Google Drive API (about.get?fields=user)")
    print("-" * 70)
    print(f"Total Storage       : {format_bytes(storage_info.total_bytes)}")
    print(f"Used Storage        : {format_bytes(storage_info.used_bytes)} ({storage_info.usage_percent:.1f}% used)")
    print(f"Available Storage   : {format_bytes(storage_info.free_bytes)}")
    print(f"Drive Usage         : {format_bytes(storage_info.drive_usage_bytes)}")
    print("Quota Source        : Google Drive API (about.get?fields=storageQuota)")
    print("-" * 70)

    # Google One tier detection based on total storage
    total_gb = storage_info.total_bytes / (1024**3)
    if total_gb >= 1900:
        tier_est = "Google One 2 TB plan"
    elif total_gb >= 190:
        tier_est = "Google One 200 GB plan"
    elif total_gb >= 95:
        tier_est = "Google One 100 GB plan"
    elif total_gb >= 14:
        tier_est = "Standard Free 15 GB plan (NOT a Google One plan)"
    else:
        tier_est = "Custom / Workspace pooled plan"

    print(f"Detected Plan Tier  : {tier_est}")
    print(f"Target Payload      : {format_bytes(preflight_res.remaining_upload_bytes)}")
    print(f"Safety Buffer (5%)  : {format_bytes(preflight_res.safety_margin_bytes)}")
    print(f"Total Required      : {format_bytes(preflight_res.total_required_bytes)}")
    print(f"Preflight Status    : {preflight_res.status.value}")

    if preflight_res.can_proceed:
        print("✅ Storage check PASSED: Target payload fits within available capacity.")
    else:
        print("❌ Storage check FAILED: Insufficient space for the target payload!")
        print(f"   Missing capacity : {format_bytes(preflight_res.shortfall_bytes)}")
        print("\nPractical Options:")
        for rec in preflight_res.recommendations:
            print(f"   • {rec}")

    print("=" * 70)


def get_account_and_quota_info(oauth, quota_svc: QuotaService) -> StorageInfo:
    """Retrieve identity and storage quota using authenticated OAuth credentials."""
    creds = oauth.get_credentials()
    if not creds:
        return StorageInfo(available=False, error="No valid authenticated credentials found.")
    return quota_svc.get_storage_info(credentials=creds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect account identity, audit quota, or switch Google accounts."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display currently authenticated identity and quota without changing anything.",
    )
    parser.add_argument(
        "--disconnect",
        action="store_true",
        help="Disconnect and purge credentials from OS keyring.",
    )
    parser.add_argument(
        "--switch",
        action="store_true",
        help="Disconnect current account and launch interactive browser OAuth flow to select a new account.",
    )
    parser.add_argument(
        "--archive-gb",
        type=float,
        default=45.0,
        help="Target archive size in GB to test against quota (default: 45.0 GB).",
    )
    args = parser.parse_args()

    credentials_path = Path(os.getenv("PHOTOPORT_CREDENTIALS", "credentials.json"))
    if not credentials_path.exists():
        logger.error("credentials.json not found at: %s", credentials_path)
        return 1

    from photoport.auth.google_oauth import GoogleOAuth

    oauth = GoogleOAuth(credentials_path=credentials_path)
    quota_svc = QuotaService()
    preflight_svc = StoragePreflightService(quota_service=quota_svc)
    target_bytes = int(args.archive_gb * (1024**3))

    if args.disconnect:
        logger.info("Disconnecting and purging credentials from OS keyring...")
        oauth.disconnect()
        logger.info("✅ Disconnected successfully. Stored tokens cleared.")
        return 0

    if args.switch:
        logger.info("=" * 70)
        logger.info("INITIATING SAFE ACCOUNT SWITCHING WORKFLOW")
        logger.info("=" * 70)
        info_before = get_account_and_quota_info(oauth, quota_svc)
        if info_before and info_before.user_email:
            logger.info("Currently active account: %s", info_before.user_email)
        logger.info("Purging current cached credentials and opening browser...")
        logger.info("Please select your intended Google account in the browser.")
        logger.info("NOTE: Ensure the intended account is listed under 'Test users' in Google Cloud Console.")
        oauth.switch_account()
        info_after = get_account_and_quota_info(oauth, quota_svc)
        preflight_res = preflight_svc.run_preflight(
            storage_info=info_after,
            total_scan_bytes=target_bytes,
        )
        display_preflight_audit(preflight_res, target_gb=args.archive_gb)
        return 0 if preflight_res.can_proceed else 1

    # Default action or --status: inspect and report
    info = get_account_and_quota_info(oauth, quota_svc)
    preflight_res = preflight_svc.run_preflight(
        storage_info=info,
        total_scan_bytes=target_bytes,
    )
    display_preflight_audit(preflight_res, target_gb=args.archive_gb)
    return 0 if preflight_res.can_proceed else 1


if __name__ == "__main__":
    sys.exit(main())
