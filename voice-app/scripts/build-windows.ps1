<#
Builds the Voice App into one folder you can run from anywhere:

    <Out>\Voice App.exe            the window (Tauri)
    <Out>\engine\voiceapp-engine.exe + _internal\   the voice engine (Python + GPU torch)
    <Out>\engine\rvc\models\        shared base models, so the first run works offline

Your voices and settings live in %APPDATA%\VoiceApp (models\ and settings.json).

Usage (from the voice-app folder):

    powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1 `
        -Python "E:\Voice stuff\env\python.exe" `
        -BaseModels "E:\Voice stuff" `
        -Voices "E:\Voice stuff\logs" `
        -Out "$env:USERPROFILE\Desktop\Voice App (new)"

-Python      a Python with voiceapp\requirements.txt installed (GPU torch).
-BaseModels  a folder that has rvc\models\embedders and rvc\models\predictors. Optional:
             without it the app downloads them (about 550 MB) on first run.
-Voices      a folder to copy .pth/.index voices from into %APPDATA%\VoiceApp\models. Optional.
-ShellExe    a prebuilt voice-app.exe (e.g. from the GitHub Actions artifact), which skips
             the Rust build, so Rust and Node aren't needed on this PC.
#>
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [string]$BaseModels = "",
    [string]$Voices = "",
    [string]$Out = "$env:USERPROFILE\Desktop\Voice App (new)",
    [string]$ShellExe = "",
    [switch]$SkipEngine
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $PSScriptRoot      # voice-app\
$Build = Join-Path $Here "build"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# 1. Engine -----------------------------------------------------------------
$EngineDist = Join-Path $Build "engine-dist\voiceapp-engine"
if (-not $SkipEngine) {
    Step "Building the voice engine with PyInstaller"
    & $Python -m PyInstaller --version *> $null
    if ($LASTEXITCODE -ne 0) { & $Python -m pip install pyinstaller; if ($LASTEXITCODE) { throw "pip install pyinstaller failed" } }
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $Build "engine-dist") --workpath (Join-Path $Build "engine-work") `
        (Join-Path $Here "engine\voiceapp-engine.spec")
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
}
if (-not (Test-Path (Join-Path $EngineDist "voiceapp-engine.exe"))) { throw "No engine build at $EngineDist" }

# 2. Window -----------------------------------------------------------------
if ($ShellExe) {
    $Shell = (Resolve-Path $ShellExe).Path
} else {
    Step "Building the window with Tauri"
    Push-Location $Here
    try {
        npm install
        if ($LASTEXITCODE) { throw "npm install failed" }
        npx tauri build --no-bundle
        if ($LASTEXITCODE) { throw "tauri build failed" }
    } finally { Pop-Location }
    $Shell = Join-Path $Here "src-tauri\target\release\voice-app.exe"
}

# 3. Assemble ---------------------------------------------------------------
Step "Putting it together in $Out"
New-Item -ItemType Directory -Force $Out | Out-Null
Copy-Item $Shell (Join-Path $Out "Voice App.exe") -Force
$EngineOut = Join-Path $Out "engine"
# /MIR keeps the folder an exact copy of the build, except the base models we add below.
robocopy $EngineDist $EngineOut /MIR /XD (Join-Path $EngineOut "rvc") /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the engine failed" }

if ($BaseModels) {
    foreach ($sub in "embedders\contentvec", "predictors") {
        $src = Join-Path $BaseModels "rvc\models\$sub"
        if (Test-Path $src) {
            robocopy $src (Join-Path $Out "engine\rvc\models\$sub") /E /NFL /NDL /NJH /NJS /NP | Out-Null
        } else {
            Write-Warning "$src not found; the app will download base models on first run"
        }
    }
}

if ($Voices) {
    $dest = Join-Path $env:APPDATA "VoiceApp\models"
    New-Item -ItemType Directory -Force $dest | Out-Null
    Get-ChildItem $Voices -Recurse -Include *.pth, *.index -File |
        Where-Object { $_.Name -notmatch '^(G|D)_\d+\.pth$' -and $_.Name -notmatch '^(f0)?(G|D)\d+k\.pth$' } |
        ForEach-Object {
            $target = Join-Path $dest $_.Name
            if (-not (Test-Path $target)) { Copy-Item $_.FullName $target; Write-Host "  voice: $($_.Name)" }
        }
}

$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("`nDone: {0}\Voice App.exe ({1:N1} GB folder)" -f $Out, $size) -ForegroundColor Green
