# PhotoPort

<p align="center">
  <strong>Production Desktop Application for Migrating Large Google Photos Takeout Archives</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform Support" />
  <img src="https://img.shields.io/badge/UI-PySide6%20%2F%20Qt-green.svg" alt="PySide6 GUI" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
</p>

---

## 📖 Overview

**PhotoPort** is an industrial-strength desktop application specifically engineered to migrate personal photo and video libraries from **Google Takeout ZIP archives** (including multi-part archives ranging from a few gigabytes to 50+ GB) directly into a destination personal Google Photos account.

Takeout exports from school or work Google Workspace accounts often contain tens of thousands of media files split across dozens of large archive files. PhotoPort automates the extraction, metadata consolidation, duplicate detection, and resumption of uploads with maximum reliability.

### Key Capabilities

- **Streaming / Chunked Archive Ingestion**: Reads Takeout ZIP archives sequentially and streams items on-demand, avoiding exhausting local disk space with complete uncompressed extractions.
- **Sidecar JSON Matching**: Automatically matches Takeout JSON metadata files (`image.jpg.json` or `image(1).json`) with their corresponding media, restoring capture timestamps, descriptions, and GPS locations.
- **Robust Duplicate Detection**: Maintains a persistent SQLite tracking database with content-addressable SHA-256 hashes, preventing duplicate uploads across archives and repeated runs.
- **Crash Recovery & Resume**: Every upload stage is tracked with explicit states (`PENDING`, `EXTRACTED`, `UPLOADING`, `COMPLETED`, `FAILED`). Crashes or network disconnects can be resumed instantly with zero data loss.
- **Original Quality Preservation**: Uploads media byte-for-byte at full fidelity via the Google Photos upload endpoint.
- **Resilient Retry & Backoff**: Exponential backoff with jitter handles network drops, rate limits (HTTP 429), and server errors (HTTP 5xx).
- **Modern PySide6 Dark-Themed GUI**: Clean desktop interface featuring migration dashboards, real-time progress bars, throughput gauges, and log viewers.
- **Multi-Part Takeout Consolidation**: Seamlessly stitches split archives (`takeout-*.zip`) into a unified collection.

---

## 🏗️ Architecture

```
                                  PhotoPort Architecture
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                               PySide6 Desktop UI                                  │
  │  [Dashboard]      [Archive Scanner]      [Migration Queue]      [Logs & Stats]   │
  └────────────────────────┬───────────────────────────────────────┬─────────────────┘
                           │                                       │
                           ▼                                       ▼
  ┌────────────────────────────────────────────────┐     ┌───────────────────────────┐
  │              Migration Manager                 │     │     OAuth2 & Keyring      │
  │  - Orchestration & Session Control             │     │  - InstalledAppFlow       │
  │  - Worker Thread Pools (QThreadPool)           │     │  - Secure Token Storage   │
  └───────┬───────────────────────────────┬────────┘     └─────────────┬─────────────┘
          │                               │                            │
          ▼                               ▼                            ▼
  ┌───────────────────────┐   ┌────────────────────────┐   ┌─────────────────────────┐
  │  Takeout Archives     │   │   SQLite Database      │   │   Google Photos API     │
  │  - Streaming Reader   │   │  - Media Items & State │   │  - Resumable Byte Upload│
  │  - Zip-Slip Safe Extr │   │  - SHA-256 Hashing     │   │  - batchCreate Items    │
  │  - Sidecar Matching   │   │  - Album Mappings      │   │  - Drive Quota Check    │
  └───────────────────────┘   └────────────────────────┘   └─────────────────────────┘
```

---

## 🔐 Google Photos API Compatibility & Scopes

As documented in [docs/API_FEASIBILITY.md](docs/API_FEASIBILITY.md), Google modified Photos API scopes in March 2025. PhotoPort uses the approved and supported scopes:

- `https://www.googleapis.com/auth/photoslibrary.appendonly`: Allows creating albums and uploading media to the user's library.
- `https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata`: Allows reading and verifying media and albums created by PhotoPort.
- `https://www.googleapis.com/auth/drive.readonly`: Preflight check of available storage quota on destination account.

---

## 💻 Prerequisites & Setup

### Requirements

- **Operating System**: Windows 10/11 (64-bit), macOS 12+, or modern Linux
- **Python**: Version 3.11 or newer

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/your-username/photoport.git
cd photoport

# Create virtual environment
python -m venv .venv

# Activate on Windows:
.venv\Scripts\activate

# Activate on macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"
```

### 2. Configure Google Cloud OAuth Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `PhotoPort Migration`).
3. Enable **Google Photos Library API** and **Google Drive API**.
4. Configure the **OAuth Consent Screen**:
   - User Type: **External**
   - Add Test Users: Add your personal destination Google account email.
5. Create OAuth 2.0 Credentials:
   - Application Type: **Desktop App**
   - Download the client secrets JSON.
6. Rename the file to `client_secret.json` and place it in the `Photoport/` root or set `PHOTOPORT_CLIENT_SECRETS_FILE` in your `.env` file:

```bash
cp .env.example .env
```

---

## 🚀 Running the Application

To launch the desktop GUI application:

```bash
# Using the entry point script
python app.py

# Or via package command
python -m photoport.app
```

---

## 🧪 Running Tests

PhotoPort comes with a comprehensive test suite covering archive validation, zip-slip security, metadata parsing, duplicate detection, retry policies, and crash recovery:

```bash
# Run all tests
pytest tests/ -v

# Run with test coverage
pytest tests/ --cov=photoport --cov-report=term-missing
```

### Test Suite Breakdown:
- `test_archive_scanner.py`: Validates detection of single and multi-part ZIP archives.
- `test_archive_security.py`: Tests path traversal (`../`) prevention, malicious payload handling, and temp-directory cleanup.
- `test_metadata_parser.py`: Tests parsing of Takeout sidecar JSON files, date formats, and Unicode filenames.
- `test_duplicate_detector.py`: Tests SHA-256 deduplication and database idempotency.
- `test_migration_state.py`: Tests state machine transitions (`PENDING` -> `EXTRACTED` -> `COMPLETED`).
- `test_retry_policy.py`: Simulates transient network errors (HTTP 429, 503) and exponential backoff.
- `test_recovery.py`: Verifies database recovery from unexpected crashes or aborted sessions.
- `test_storage_preflight.py`: Verifies Google Drive storage quota detection.

---

## 📦 Packaging for Windows (PyInstaller)

PhotoPort includes preconfigured build scripts and a PyInstaller `.spec` file to build a standalone Windows `.exe`:

### Option A: Using the Windows Batch Script
Double click or run from Command Prompt:
```cmd
build_windows.bat
```

### Option B: Using PowerShell
```powershell
.\build_windows.ps1
```

### Option C: Manual PyInstaller Command
```cmd
pyinstaller --clean --noconfirm PhotoPort.spec
```

The resulting distribution folder will be generated at:
```
dist\PhotoPort\
    PhotoPort.exe
    ... (runtime DLLs, Qt binaries, dependencies)
```

Distribute the `PhotoPort` directory or package it with an installer such as Inno Setup or WiX Toolset.

---

## 🛡️ Security and Privacy

- **Local Processing**: Archives are read, hashed, and processed entirely on your local machine. No third-party servers are involved.
- **Local Credentials**: OAuth tokens are saved locally in the user application data directory (`%LOCALAPPDATA%\PhotoPort` on Windows) and can be disconnected or revoked at any time.
- **Zip-Slip Defense**: Archive decompression strictly validates destination paths to prevent directory traversal vulnerabilities.
- **Clean Temp Management**: Extracted temporary media files are automatically cleaned up immediately after upload.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
