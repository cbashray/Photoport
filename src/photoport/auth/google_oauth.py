"""Google OAuth 2.0 authentication for desktop applications."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from photoport.config import OAUTH_SCOPES

logger = logging.getLogger("photoport.auth.google_oauth")


class GoogleOAuth:
    """Manage Google OAuth 2.0 authentication for the installed application flow.

    Uses the system browser for the authorization page and a local loopback
    server to receive the authorization code. Tokens are stored securely
    in the OS credential store (Windows Credential Manager, macOS Keychain,
    or SecretService on Linux) via `keyring`. Plaintext token files are
    migrated and purged.
    """

    KEYRING_SERVICE: Final[str] = "PhotoPort"
    KEYRING_USERNAME: Final[str] = "google_oauth_token"

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes or list(OAUTH_SCOPES)
        self._creds: Credentials | None = None
        self._cached_email: str = ""

    @property
    def is_authenticated(self) -> bool:
        """Check if valid credentials exist."""
        creds = self._load_cached_credentials()
        return creds is not None and creds.valid

    @property
    def access_token(self) -> str | None:
        """Return the current access token, refreshing if needed."""
        creds = self.get_credentials()
        return creds.token if creds else None

    @property
    def user_email(self) -> str:
        """Return the email of the authenticated user, if available."""
        if hasattr(self, "_cached_email") and self._cached_email:
            return self._cached_email

        creds = self._load_cached_credentials()
        if creds and hasattr(creds, "token") and creds.token:
            if hasattr(creds, "_id_token") and creds._id_token:
                info = creds._id_token
                if isinstance(info, dict) and info.get("email"):
                    self._cached_email = info["email"]
                    return self._cached_email

            try:
                import requests

                from photoport.config import GOOGLE_DRIVE_ABOUT_URL

                resp = requests.get(
                    GOOGLE_DRIVE_ABOUT_URL,
                    headers={"Authorization": f"Bearer {creds.token}"},
                    params={"fields": "user(emailAddress)"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    email = resp.json().get("user", {}).get("emailAddress", "")
                    if email:
                        self._cached_email = email
                        return email
            except Exception:
                pass
        return ""

    def get_credentials(self) -> Credentials | None:
        """Get valid credentials, refreshing if expired.

        Does NOT trigger interactive login. Call `authenticate()` first.
        """
        creds = self._load_cached_credentials()
        if creds is None:
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_credentials(creds)
                logger.info("OAuth tokens refreshed successfully.")
            except Exception as exc:
                logger.error("Failed to refresh OAuth tokens: %s", exc)
                return None

        self._creds = creds
        return creds

    def authenticate(
        self, port: int = 0, prompt: str = "select_account consent"
    ) -> Credentials:
        """Run the interactive OAuth flow.

        Opens the system browser for Google sign-in and captures the
        authorization code via a local loopback server.

        Args:
            port: Port for the local server. 0 = auto-select.
            prompt: OAuth prompt mode ('select_account consent' forces account chooser).

        Returns:
            Valid Google credentials.

        Raises:
            FileNotFoundError: If credentials.json is missing.
            ValueError: If the OAuth flow fails.
        """
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"OAuth credentials file not found: {self.credentials_path}\n"
                "Download it from Google Cloud Console → APIs & Services → Credentials.\n"
                "Select 'Desktop Application' as the application type."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_path), self.scopes
        )

        creds = flow.run_local_server(
            port=port,
            prompt=prompt,
            success_message=(
                "Authentication successful! You can close this window and "
                "return to PhotoPort."
            ),
        )

        self._save_credentials(creds)
        self._creds = creds
        self._cached_email = ""
        _ = self.user_email
        logger.info("OAuth authentication completed successfully.")
        return creds

    def switch_account(self, port: int = 0) -> Credentials:
        """Disconnect the current account and trigger a fresh OAuth flow with account selection.

        Forces Google's account selection prompt so the user can choose their intended Google account.
        """
        logger.info("Switching Google account: clearing existing credentials...")
        self.disconnect()
        return self.authenticate(port=port, prompt="select_account consent")

    def revoke(self) -> bool:
        """Revoke the current credentials and delete stored tokens."""
        creds = self._load_cached_credentials()
        revoked = False

        if creds and creds.token:
            try:
                import requests
                resp = requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    headers={"Content-type": "application/x-www-form-urlencoded"},
                    timeout=10,
                )
                revoked = resp.status_code == 200
                if revoked:
                    logger.info("OAuth token revoked successfully.")
                else:
                    logger.warning("Token revocation returned status %d", resp.status_code)
            except Exception as exc:
                logger.warning("Failed to revoke token: %s", exc)

        self._delete_credentials()
        self._creds = None
        self._cached_email = ""
        return revoked

    def disconnect(self) -> None:
        """Remove local credentials without revoking remotely."""
        self._delete_credentials()
        self._creds = None
        self._cached_email = ""
        logger.info("Local credentials removed from secure storage.")

    def _load_cached_credentials(self) -> Credentials | None:
        """Load credentials from keyring, migrating from legacy token file if needed."""
        if self._creds is not None and self._creds.valid:
            return self._creds

        # 1. Try loading from keyring
        try:
            raw = keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
            if raw:
                data = json.loads(raw)
                creds = Credentials.from_authorized_user_info(data, self.scopes)
                self._creds = creds
                return creds
        except Exception as exc:
            logger.warning("Failed to load credentials from keyring: %s", exc)

        # 2. Legacy fallback: check token file and migrate
        if self.token_path and self.token_path.exists():
            try:
                logger.info("Found legacy plaintext token file; migrating to keyring...")
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path), self.scopes
                )
                self._save_credentials(creds)
                self._creds = creds
                return creds
            except Exception as exc:
                logger.warning("Failed to migrate legacy token file: %s", exc)

        return None

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to keyring securely and remove legacy plaintext file."""
        try:
            keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, creds.to_json())
            logger.debug("Credentials securely saved to keyring.")
        except Exception as exc:
            logger.error("Failed to save credentials to secure keyring: %s", exc)
            raise

        # Remove legacy token file if it exists (migration complete)
        if self.token_path and self.token_path.exists():
            try:
                self.token_path.unlink()
                logger.info("Removed legacy plaintext token file after migration to keyring.")
            except Exception as exc:
                logger.warning("Could not remove legacy token file %s: %s", self.token_path, exc)

    def _delete_credentials(self) -> None:
        """Delete credentials from keyring and remove legacy token file."""
        try:
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
            logger.debug("Credentials deleted from keyring service '%s'", self.KEYRING_SERVICE)
        except Exception as exc:
            logger.debug("Keyring delete skipped or failed: %s", exc)

        try:
            if self.token_path and self.token_path.exists():
                self.token_path.unlink()
                logger.debug("Legacy token file deleted: %s", self.token_path)
        except Exception as exc:
            logger.warning("Failed to delete legacy token file: %s", exc)
