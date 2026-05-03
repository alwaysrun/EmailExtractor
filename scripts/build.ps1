<#
.SYNOPSIS
    Build script for EmailExtractor using Nuitka.

.DESCRIPTION
    This script packages the EmailExtractor application into a standalone directory
    using Nuitka. Configuration files are kept external for easy modification.
    
    Build structure:
    - Temporary files: main.build/, main.dist/ (in project root, auto-cleaned)
    - Final output: dist/ (contains exe, _internal/, configures/)

.PARAMETER OutputDir
    Output directory for the built application. Default is "dist".

.PARAMETER KeepTemp
    Keep temporary build files for debugging.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -OutputDir "release"
    .\build.ps1 -KeepTemp
#>

param(
    [string]$OutputDir = "dist",
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ProjectDir = Split-Path $ScriptDir -Parent

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "EmailExtractor Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Project Directory: $ProjectDir"
Write-Host "Output Directory: $OutputDir"
Write-Host "Keep Temp Files: $KeepTemp"
Write-Host ""

$tempBuildDir = Join-Path $ProjectDir "main.build"
$tempDistDir = Join-Path $ProjectDir "main.dist"
$finalOutputDir = Join-Path $ProjectDir $OutputDir

if (Test-Path $finalOutputDir) {
    Write-Host "Removing existing output directory..." -ForegroundColor Yellow
    Remove-Item -Path $finalOutputDir -Recurse -Force
}

Push-Location $ProjectDir

try {
    Write-Host "Checking Nuitka installation..." -ForegroundColor Cyan
    $nuitkaCheck = python -m nuitka --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Nuitka not found. Installing..." -ForegroundColor Yellow
        pip install nuitka
    }
    else {
        Write-Host "Nuitka version: $nuitkaCheck"
    }

    Write-Host ""
    Write-Host "Starting Nuitka build..." -ForegroundColor Green
    Write-Host ""

    $nuitkaArgs = @(
        "-m", "nuitka",
        "--standalone",
        "--output-filename=EmailExtractor.exe",
        "--enable-plugin=tk-inter",
        "--include-package=src",
        "--windows-console-mode=force",
        "--assume-yes-for-downloads",
        "main.py"
    )

    Write-Host "Running: python $($nuitkaArgs -join ' ')" -ForegroundColor Gray
    Write-Host ""

    & python $nuitkaArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Moving build output to final directory..." -ForegroundColor Cyan

        if (Test-Path $tempDistDir) {
            Move-Item -Path $tempDistDir -Destination $finalOutputDir -Force
            Write-Host "Output moved to: $finalOutputDir" -ForegroundColor Green
        }
        else {
            Write-Host "Error: Build output directory not found: $tempDistDir" -ForegroundColor Red
            exit 1
        }

        Write-Host ""
        Write-Host "Copying configuration files..." -ForegroundColor Cyan

        $distConfigDir = Join-Path $finalOutputDir "configures"
        if (-not (Test-Path $distConfigDir)) {
            New-Item -ItemType Directory -Path $distConfigDir -Force | Out-Null
        }

        Copy-Item -Path "$ProjectDir\configures\config.toml" -Destination $distConfigDir -Force
        Copy-Item -Path "$ProjectDir\configures\analyze_prompt.md" -Destination $distConfigDir -Force
        Copy-Item -Path "$ProjectDir\configures\.env.example" -Destination $distConfigDir -Force

        $envFile = Join-Path $ProjectDir "configures\.env"
        if (Test-Path $envFile) {
            Copy-Item -Path $envFile -Destination $distConfigDir -Force
            Write-Host ".env file copied." -ForegroundColor Green
        }
        else {
            Write-Host "Warning: .env file not found, skipping." -ForegroundColor Yellow
        }

        Write-Host "Configuration files copied." -ForegroundColor Green

        if (-not $KeepTemp) {
            Write-Host ""
            Write-Host "Cleaning up temporary build files..." -ForegroundColor Yellow

            if (Test-Path $tempBuildDir) { 
                Remove-Item -Path $tempBuildDir -Recurse -Force 
            }

            Write-Host "Temporary files cleaned." -ForegroundColor Green
        }
        else {
            Write-Host ""
            Write-Host "Keeping temporary files (KeepTemp=$KeepTemp)" -ForegroundColor Yellow
            Write-Host "Temp build dir: $tempBuildDir" -ForegroundColor Gray
        }

        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "Build completed successfully!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Output location: $finalOutputDir\" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Distribution contents:" -ForegroundColor Cyan
        Write-Host "  - EmailExtractor.exe"
        Write-Host "  - _internal/          (runtime dependencies)"
        Write-Host "  - configures/"
        Write-Host "    - config.toml       (configure before running)"
        Write-Host "    - .env              (contains sensitive data)"
        Write-Host "    - .env.example      (template for .env)"
        Write-Host "    - analyze_prompt.md"
        Write-Host ""
        Write-Host "WARNING: Do not distribute dist/ folder to others!" -ForegroundColor Yellow
        Write-Host "         It contains your .env file with sensitive data." -ForegroundColor Yellow
        Write-Host ""
    }
    else {
        Write-Host ""
        Write-Host "Build failed with exit code: $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
}
finally {
    Pop-Location
}
