# One-time setup of a Windows PC to build and flash the doorbell (Outdoor unit).
#
#   git clone https://github.com/someshsaraf/smart-door-bell.git
#   cd smart-door-bell
#   .\setup.cmd          (then:  .\build.cmd -Flash COM6)
#
# Fetches the TuyaOpen SDK at the version this repo is tested with (the sdk/TuyaOpen
# submodule), lets the SDK install its own tools (Python environment, CMake, Ninja,
# GNU Make; the T5 compiler and platform come with the first build), and creates the
# doorbell <-> indoor broker encryption key if there is none yet.
# Needs Git and an internet connection; nothing is installed system-wide.
$ErrorActionPreference = "Continue"  # the SDK tools print progress on stderr; exit codes are checked instead
$root = $PSScriptRoot
Set-Location $root

Write-Host "== TuyaOpen SDK (sdk/TuyaOpen, pinned version)" -ForegroundColor Cyan
git config core.longpaths true                     # the T5 platform has very long paths
git -c core.longpaths=true submodule update --init --recursive
if ($LASTEXITCODE -ne 0) { throw "Fetching the SDK failed" }
$sdk = Join-Path $root "sdk\TuyaOpen"
git -C $sdk config core.longpaths true

Write-Host "== SDK tools (first time: a few minutes)" -ForegroundColor Cyan
Push-Location $sdk
try { . .\export.ps1 } finally { Pop-Location }
# no interactive "update the platform?" question during builds
New-Item -ItemType Directory -Force (Join-Path $sdk ".cache") | Out-Null
New-Item -ItemType File -Force (Join-Path $sdk ".cache\.dont_prompt_update_platform") | Out-Null

Write-Host "== Encryption key for the doorbell link" -ForegroundColor Cyan
$py = if ($env:OPEN_SDK_PYTHON) { $env:OPEN_SDK_PYTHON } else { "python" }
& $py (Join-Path $root "Outdoor\tools\make_psk.py")   # keeps an existing key

Write-Host ""
Write-Host "Done. Next:" -ForegroundColor Green
Write-Host "  .\build.cmd                    build the doorbell firmware"
Write-Host "  .\build.cmd -Flash COM6        build and flash (port: Device Manager > Ports)"
Write-Host "  .\build.cmd -Flash COM6 -Monitor"
Write-Host "  Copy Indoor\mqtt_psk.txt to ~/Indoor/ on the Pi and run Indoor/setup_pi.sh there (see README)."
