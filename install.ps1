# journal-dl installer for Windows. No admin rights needed.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/onetrickpony1/journal-dl/main/install.ps1 | iex"
#
# What it does:
#   1. installs uv (https://docs.astral.sh/uv/) if missing: it manages Python for journal-dl
#   2. installs journal-dl in its own isolated environment, with its own Python if needed
#   3. puts journal-dl, ovid-dl, wiley-dl and tandf-dl on your PATH
#   4. checks for a browser (Microsoft Edge comes with Windows; Chrome is used if installed)
#   5. offers a "Journal Downloader" desktop icon
# Run it again to update. Uninstall: uv tool uninstall journal-dl

# "Continue": Windows PowerShell turns harmless messages from programs into errors under "Stop";
# every step checks $LASTEXITCODE instead
$ErrorActionPreference = "Continue"
$Source = if ($env:JOURNAL_DL_SOURCE) { $env:JOURNAL_DL_SOURCE } else { "journal-dl @ https://github.com/onetrickpony1/journal-dl/archive/refs/heads/main.zip" }
$Python = if ($env:JOURNAL_DL_PYTHON) { $env:JOURNAL_DL_PYTHON } else { "3.12" }

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
# throw, not exit: when run with "irm ... | iex", exit would close the user's PowerShell window
function Fail($msg) { Write-Host "`njournal-dl installer: $msg" -ForegroundColor Red; throw "journal-dl was not installed" }

Say "Installing journal-dl"

# 1. uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) { $UV = $uv.Source }
else {
    $cand = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path $cand)) {
        Say "Installing uv (Python manager, from astral.sh)"
        try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
        catch { Fail "could not download uv: $($_.Exception.Message)" }
    }
    if (Test-Path $cand) { $UV = $cand } else { Fail "uv was installed but can't be found; open a new window and run this again" }
}

# 2. journal-dl (+ Python if needed)
Say "Installing journal-dl and its packages (Python $Python is downloaded if needed)"
& $UV tool install --force --python $Python $Source
if ($LASTEXITCODE -ne 0) { Fail "installing journal-dl failed (see above)" }

# 3. PATH
try { & $UV tool update-shell 2>&1 | Out-Null } catch { }
$Bin = (& $UV tool dir --bin).Trim()
$JDL = Join-Path $Bin "journal-dl.exe"
if (-not (Test-Path $JDL)) { Fail "journal-dl was installed but $JDL is missing" }

# 4. browser
Say "Checking for a browser"
& $JDL --install-browser
if ($LASTEXITCODE -ne 0) { Write-Host "Could not set up a browser automatically; install Google Chrome, then run: journal-dl --doctor" }

# 5. desktop icon
$answer = ""
if ([Environment]::UserInteractive -and -not $env:CI) {
    try { $answer = Read-Host "Add a 'Journal Downloader' icon to the desktop? [Y/n]" } catch { $answer = "" }
}
if ($answer -eq "" -or $answer -match "^[Yy]") {
    if (-not $env:CI) { & $JDL --install-launcher }
}

Say ("Done: " + (& $JDL --version))
if (-not (($env:Path -split ";") -contains $Bin)) {
    Write-Host "Open a NEW terminal window so the commands are found (they are in $Bin)."
}
Write-Host ""
Write-Host "Start with:   journal-dl --easy        (step-by-step guide; asks for your library details first)"
Write-Host "Check setup:  journal-dl --doctor"
Write-Host "Read first:   https://github.com/onetrickpony1/journal-dl/blob/main/LEGAL.md"
