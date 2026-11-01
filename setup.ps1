#Requires -Version 5.1
<#
.SYNOPSIS
    Creates the project's .venv and installs requirements.txt.
.PARAMETER Recreate
    Delete and rebuild an existing .venv.
.PARAMETER SkipTests
    Skip running the unit tests after installation.
#>
[CmdletBinding()]
param(
    [switch]$Recreate,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Find-Python {
    foreach ($candidate in @(@('py', '-3'), @('python'), @('python3'))) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        & $exe @extra -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return , $candidate }
    }
    return $null
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit code $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if ($Recreate -and (Test-Path -LiteralPath $venv)) {
    Write-Host 'Removing existing .venv...'
    Remove-Item -LiteralPath $venv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = Find-Python
    if (-not $python) {
        throw 'Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/ and run this script again.'
    }
    Write-Host 'Creating virtual environment...'
    $extra = @($python | Select-Object -Skip 1)
    Invoke-Checked $python[0] ($extra + @('-m', 'venv', $venv))
}
else {
    Write-Host 'Using existing .venv.'
}

Write-Host 'Installing dependencies...'
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'requirements.txt'))

Write-Host 'Checking Tkinter support...'
& $venvPython -c 'import tkinter' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Tkinter is unavailable; the GUI will not run. Reinstall Python with tcl/tk support.'
}

if (-not $SkipTests) {
    Write-Host 'Running tests...'
    Invoke-Checked $venvPython @('-m', 'unittest', 'discover', '-s', 'tests')
}

Write-Host ''
Write-Host 'Setup complete. Launch the GUI with app_gui.bat or: .venv\Scripts\pythonw.exe app_gui.py'
