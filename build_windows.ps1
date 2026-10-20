# ==============================================================================
# PhotoPort - Windows Build and Packaging Script (PowerShell)
# Builds a standalone Windows executable distribution using PyInstaller
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Building PhotoPort Windows Desktop Distribution       " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# Step 1: Check Python installation
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[INFO] Detected Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Error "[ERROR] Python is not installed or not in PATH. Please install Python 3.11+."
    exit 1
}

# Step 2: Virtual Environment Setup
$venvPath = ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[INFO] Creating virtual environment at $venvPath..." -ForegroundColor Yellow
    python -m venv $venvPath
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
$venvPip = Join-Path $venvPath "Scripts\pip.exe"

# Step 3: Dependencies
Write-Host "[INFO] Installing / verifying dependencies..." -ForegroundColor Yellow
& $venvPip install --upgrade pip
& $venvPip install -r requirements.txt
& $venvPip install pyinstaller>=6.4.0 pytest>=8.0.0

# Step 4: Optional Tests
if (-not $SkipTests) {
    Write-Host "[INFO] Running test suite..." -ForegroundColor Yellow
    & $venvPython -m pytest tests
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[ERROR] Tests failed! Aborting build."
        exit 1
    }
    Write-Host "[INFO] All tests passed!" -ForegroundColor Green
}

# Step 5: Clean prior builds
if ($Clean) {
    Write-Host "[INFO] Cleaning build and dist folders..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
}

# Step 6: PyInstaller Packaging
Write-Host "[INFO] Packaging application with PyInstaller..." -ForegroundColor Yellow
& $venvPython -m PyInstaller --clean --noconfirm PhotoPort.spec

if ($LASTEXITCODE -eq 0) {
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host " [SUCCESS] PhotoPort built successfully!" -ForegroundColor Green
    Write-Host " Output: dist\PhotoPort\PhotoPort.exe" -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
} else {
    Write-Error "[ERROR] PyInstaller packaging encountered an error."
    exit 1
}
