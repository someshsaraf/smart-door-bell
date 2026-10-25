# Builds the doorbell firmware, and optionally flashes it and shows its log.
#
#   .\build.ps1                          build only
#   .\build.ps1 -Flash COM6              build, then flash over COM6
#   .\build.ps1 -Flash COM6 -Monitor     ... then show the doorbell's log (Ctrl+C to stop)
#   .\build.ps1 -Clean                   start from a clean build tree
#
# Uses the SDK in sdk/TuyaOpen (after .\setup.ps1), or, for a checkout that lives
# inside a TuyaOpen tree (examples/...), that TuyaOpen.
param([string]$Flash, [switch]$Monitor, [switch]$Clean)
$ErrorActionPreference = "Continue"  # the SDK tools print progress on stderr; exit codes are checked instead
$root = $PSScriptRoot

$sdk = Join-Path $root "sdk\TuyaOpen"
if (-not (Test-Path (Join-Path $sdk "export.ps1"))) {
    $sdk = $null
    for ($d = Split-Path $root -Parent; $d; $d = Split-Path $d -Parent) {
        if (Test-Path (Join-Path $d "export.ps1")) { $sdk = $d; break }
    }
    if (-not $sdk) { throw "No TuyaOpen SDK: run .\setup.ps1 first" }
}
Write-Host "SDK: $sdk" -ForegroundColor DarkGray
Push-Location $sdk
try { . .\export.ps1 *> $null } finally { Pop-Location }

$key = Join-Path $root "Outdoor\src\doorbell_secret.h"
if (-not (Test-Path $key)) {
    Write-Warning "No encryption key ($key): the firmware will use plain MQTT. Run Outdoor\tools\make_psk.py to create one."
}

Push-Location (Join-Path $root "Outdoor")
try {
    if ($Clean) { tos.py clean }
    tos.py build
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
    $bin = Get-ChildItem dist -Recurse -Filter "*_QIO_*.bin" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Write-Host "Firmware: $($bin.FullName)" -ForegroundColor Green
    if ($Flash) {
        tos.py flash -p $Flash
        if ($LASTEXITCODE -ne 0) { throw "Flash failed (is $Flash the board's port? a data cable?)" }
        if ($Monitor) { tos.py monitor -p $Flash }
    }
} finally { Pop-Location }
