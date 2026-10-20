"""Tests for secure OAuth token storage using keyring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from google.oauth2.credentials import Credentials

from photoport.auth.google_oauth import GoogleOAuth


def _create_fake_credentials() -> Credentials:
    """Create a mock Google OAuth Credentials object with valid fields."""
    return Credentials(
        token="mock_access_token_xyz",
        refresh_token="mock_refresh_token_abc",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="mock_client_id_123.apps.googleusercontent.com",
        client_secret="mock_client_secret_secret",
        scopes=["https://www.googleapis.com/auth/photoslibrary.appendonly"],
    )


class MockKeyring:
    """In-memory keyring backend for isolated testing."""

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) in self.passwords:
            del self.passwords[(service, username)]


def test_credentials_saved_to_keyring_not_file(tmp_path: Path):
    """Test that credentials are saved to keyring and NOT written to token_path."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {"client_id": "c1", "client_secret": "s1"}}')
    token_path = tmp_path / "token.json"

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password):

        oauth = GoogleOAuth(credentials_path=creds_path, token_path=token_path)
        fake_creds = _create_fake_credentials()

        oauth._save_credentials(fake_creds)

        # Token must be stored in keyring
        stored_raw = mock_kr.get_password(GoogleOAuth.KEYRING_SERVICE, GoogleOAuth.KEYRING_USERNAME)
        assert stored_raw is not None
        data = json.loads(stored_raw)
        assert data["token"] == "mock_access_token_xyz"
        assert data["refresh_token"] == "mock_refresh_token_abc"

        # Token file must NOT exist on disk
        assert not token_path.exists()


def test_legacy_plaintext_token_file_migrated_and_purged(tmp_path: Path):
    """Test that pre-existing plaintext token file is migrated to keyring and deleted from disk."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {"client_id": "c1", "client_secret": "s1"}}')
    token_path = tmp_path / "legacy_token.json"

    fake_creds = _create_fake_credentials()
    token_path.write_text(fake_creds.to_json())
    assert token_path.exists()

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password):

        oauth = GoogleOAuth(credentials_path=creds_path, token_path=token_path)

        # Loading cached credentials should find legacy file, migrate it, and purge the file
        loaded_creds = oauth._load_cached_credentials()
        assert loaded_creds is not None
        assert loaded_creds.token == "mock_access_token_xyz"

        # Keyring now has the password
        assert mock_kr.get_password(GoogleOAuth.KEYRING_SERVICE, GoogleOAuth.KEYRING_USERNAME) is not None

        # Legacy file must have been purged
        assert not token_path.exists()


def test_disconnect_clears_keyring(tmp_path: Path):
    """Test that disconnect deletes credentials from keyring and resets state."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password):

        oauth = GoogleOAuth(credentials_path=creds_path, token_path=token_path)
        fake_creds = _create_fake_credentials()
        oauth._save_credentials(fake_creds)

        assert mock_kr.get_password(GoogleOAuth.KEYRING_SERVICE, GoogleOAuth.KEYRING_USERNAME) is not None

        oauth.disconnect()

        assert mock_kr.get_password(GoogleOAuth.KEYRING_SERVICE, GoogleOAuth.KEYRING_USERNAME) is None
        assert oauth._creds is None


def test_no_secrets_in_logs(tmp_path: Path, caplog):
    """Ensure sensitive tokens or client secrets are never logged."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {"client_id": "c1", "client_secret": "s1"}}')
    token_path = tmp_path / "token.json"

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password):

        oauth = GoogleOAuth(credentials_path=creds_path, token_path=token_path)
        fake_creds = _create_fake_credentials()
        oauth._save_credentials(fake_creds)
        oauth.disconnect()

        log_text = caplog.text
        assert "mock_access_token_xyz" not in log_text
        assert "mock_refresh_token_abc" not in log_text
        assert "mock_client_secret_secret" not in log_text


def test_switch_account_clears_keyring_before_auth(tmp_path: Path):
    """Test that switch_account safely clears stored credentials and triggers fresh auth."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {"client_id": "c1", "client_secret": "s1"}}')

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password), \
         patch.object(GoogleOAuth, "authenticate") as mock_auth:

        oauth = GoogleOAuth(credentials_path=creds_path)
        fake_creds = _create_fake_credentials()
        oauth._save_credentials(fake_creds)
        oauth._cached_email = "old_user@gmail.com"

        assert mock_kr.get_password(GoogleOAuth.KEYRING_SERVICE, GoogleOAuth.KEYRING_USERNAME) is not None

        mock_auth.return_value = fake_creds
        oauth.switch_account()

        # Disconnect was called (cached email wiped and keyring cleared before authenticate)
        assert oauth._cached_email == ""
        mock_auth.assert_called_once_with(port=0, prompt="select_account consent")


def test_user_email_resolution_and_caching(tmp_path: Path):
    """Test that user_email queries Drive about endpoint when id_token is absent and caches result."""
    mock_kr = MockKeyring()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {"client_id": "c1", "client_secret": "s1"}}')

    with patch("keyring.get_password", side_effect=mock_kr.get_password), \
         patch("keyring.set_password", side_effect=mock_kr.set_password), \
         patch("keyring.delete_password", side_effect=mock_kr.delete_password), \
         patch("requests.get") as mock_get:

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"user": {"emailAddress": "user@gmail.com"}}

        oauth = GoogleOAuth(credentials_path=creds_path)
        fake_creds = _create_fake_credentials()
        oauth._save_credentials(fake_creds)

        email = oauth.user_email
        assert email == "user@gmail.com"
        assert oauth._cached_email == "user@gmail.com"

        # Subsequent call should use cache without HTTP request
        mock_get.reset_mock()
        email_second = oauth.user_email
        assert email_second == "user@gmail.com"
        mock_get.assert_not_called()
