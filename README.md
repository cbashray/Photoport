# PhotoPort

### Google Photos Takeout Migration Tool for Windows

**PhotoPort** is a Windows desktop application designed to simplify the migration of Google Photos libraries from Google Takeout archives to a personal Google Photos account.

Instead of manually extracting archives and uploading individual photos and videos, PhotoPort aims to automate archive processing, metadata handling, media uploads, migration tracking, and recovery from interrupted operations.

> **Project status:** In development. Google Photos API capabilities, account authorization, upload limits, and metadata preservation must be validated before a complete migration can be considered operational.

## ✨ Features

- **Large Archive Support** — Designed to handle Google Takeout ZIP archives totaling at least 60 GB.
- **Automated Archive Processing** — Discover and process media files directly from Takeout archives without requiring full manual extraction.
- **Original-Quality Preservation** — Avoid intentional image compression, resizing, and video transcoding.
- **Google Account Authorization** — Secure destination account authorization through supported Google OAuth workflows.
- **Photo and Video Migration** — Upload supported media using currently available Google Photos API capabilities.
- **Metadata Processing** — Parse Takeout JSON sidecars and preserve supported metadata where possible.
- **Album Organization** — Reconstruct supported album structures when the destination API permits it.
- **Migration Dashboard** — Track progress, completed uploads, pending files, failures, and skipped items.
- **Pause and Resume** — Persist migration state to support recovery after interruptions.
- **Retry Management** — Handle transient network failures and API rate limits with controlled retries.
- **Duplicate Detection** — Use file hashes and migration records to reduce unnecessary duplicate uploads.
- **Storage Preflight** — Check available destination capacity where supported and warn about insufficient storage.
- **Migration Reports** — Export results and unresolved issues to CSV and JSON.
- **Local Processing** — Process archive files on the user's Windows computer instead of uploading entire Takeout archives to a separate application server.

## 🖥️ Target Platform

- Operating system: Windows 10/11, subject to dependency compatibility
- Interface: Python and PySide6
- Archive format: Google Takeout ZIP archives
- Destination: Google Photos account with the required supported API permissions

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python |
| Desktop interface | PySide6 |
| Archive processing | Python `zipfile` |
| Authentication | Google OAuth 2.0 |
| API integration | Supported Google Photos APIs |
| Local database | SQLite |
| HTTP communication | Requests or an equivalent maintained client |
| Testing | Pytest |
| Windows packaging | PyInstaller |

## 🏗️ Architecture

PhotoPort separates archive processing, authentication, migration management, and the desktop interface into independent modules.

```text
PhotoPort
├── Desktop Interface
│   ├── Dashboard
│   ├── Archive Import
│   ├── Account Authorization
│   └── Migration Reports
│
├── Archive Processing
│   ├── ZIP Scanner
│   ├── Media Discovery
│   ├── Metadata Parser
│   └── Archive Validation
│
├── Migration Engine
│   ├── Upload Queue
│   ├── Retry Manager
│   ├── Duplicate Detection
│   ├── Progress Tracking
│   └── Recovery Manager
│
├── Google Photos Integration
│   ├── OAuth Client
│   ├── Upload Service
│   ├── Storage Checks
│   └── Album Operations
│
└── Local Persistence
    ├── SQLite Database
    ├── Migration State
    └── Logs and Reports
```

## 🚀 Getting Started

### Prerequisites

- Windows 10 or Windows 11
- A supported Python version
- A Google account for the destination library
- Google Cloud project configuration for the supported OAuth and API workflow
- Sufficient destination storage for the intended migration

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/PhotoPort.git
cd PhotoPort
```

Replace `YOUR_USERNAME` with your GitHub username.

### 2. Create a virtual environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Google API access

Create a Google Cloud project and configure the OAuth consent screen and required API access according to the current official Google documentation.

Use only currently supported authorization scopes and upload operations. Do not copy obsolete OAuth scopes or endpoints from older tutorials.

Never commit credentials, access tokens, refresh tokens, or personal archive data to GitHub.

### 5. Launch the application

Once the implementation is complete:

```powershell
python app.py
```

Follow the application's instructions to select Takeout archives, authorize the destination account, review the migration plan, and start the transfer.

## 📦 Large Archive Handling

PhotoPort is designed for Takeout archives totaling at least 60 GB, including the initial 45 GB migration use case.

The implementation aims to:

- Process archives incrementally.
- Keep memory usage bounded.
- Minimize temporary disk usage.
- Validate archive entries before processing.
- Save progress persistently.
- Resume interrupted migration jobs.
- Preserve the source archives until the migration is verified.

Temporary disk space may still be required for individual files or upload operations. Actual requirements depend on the archive structure, media sizes, and supported API workflow.

## 🛡️ Data Integrity and Security

PhotoPort is designed around the following principles:

- Never intentionally recompress, resize, or transcode original media.
- Never delete source archives automatically.
- Never store Google passwords.
- Protect OAuth credentials and tokens.
- Avoid logging sensitive information.
- Report unsupported formats and failed uploads explicitly.
- Verify migration outcomes wherever the API permits.
- Require confirmation before starting a large migration.

Original-quality preservation applies to the media bytes available in the Takeout archive. It cannot restore original camera files that were already backed up in reduced quality.

## ⚠️ Google Photos API Limitations

Google Photos API capabilities and authorization rules can change. In particular, access to existing libraries, uploading media, managing albums, preserving metadata, and verifying uploaded content may have different restrictions.

PhotoPort must validate these capabilities before attempting a full migration.

A successful local archive scan does not guarantee that every file can be uploaded. Features that are unsupported by the current API must be clearly identified rather than simulated.

Refer to the official documentation:

- [Google Photos APIs](https://developers.google.com/photos)
- [Google Photos API upload guide](https://developers.google.com/photos/library/guides/upload-media)
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
- [Google Takeout](https://takeout.google.com/)

## 🧪 Testing

The project should include automated tests for:

- ZIP validation and archive security
- Large-file processing
- JSON sidecar parsing
- Duplicate detection
- OAuth error handling
- Upload retries
- Insufficient storage
- Interrupted migration recovery
- Migration reports
- Original media hash verification

Run the test suite with:

```powershell
pytest
```

Use a small test archive and a test Google account before migrating a complete photo library.

## 🗺️ Roadmap

- [ ] Validate the current Google Photos upload API workflow.
- [ ] Implement large Takeout archive scanning.
- [ ] Implement JSON metadata parsing.
- [ ] Build secure Google OAuth authorization.
- [ ] Implement supported media uploads.
- [ ] Add SQLite-backed migration tracking.
- [ ] Implement pause, resume, and retry functionality.
- [ ] Add destination storage safeguards.
- [ ] Implement migration reports.
- [ ] Test recovery after application restarts.
- [ ] Package the application as a Windows executable.
- [ ] Validate a complete migration with a representative test library.

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome.

Before submitting changes, run the test suite and ensure that no credentials, private photos, personal metadata, or archive files are included in commits.

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## ⚖️ Disclaimer

PhotoPort is an independent project and is not affiliated with, endorsed by, or officially supported by Google.

Use of Google Photos APIs is subject to Google's current terms, API policies, and account restrictions.

---

**PhotoPort — Simplifying Google Photos migration, one archive at a time.**
