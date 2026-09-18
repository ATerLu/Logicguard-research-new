[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ManifestPath = "",
    [switch]$AllowMissing
)

$ErrorActionPreference = "Stop"

$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $projectPath "EXTERNAL_ASSETS_SHA256.tsv"
}
$manifestFullPath = [System.IO.Path]::GetFullPath($ManifestPath)

if (-not (Test-Path -LiteralPath $manifestFullPath)) {
    throw "External asset manifest is missing: $manifestFullPath"
}

$rows = @(Import-Csv -LiteralPath $manifestFullPath -Delimiter "`t")
$missing = [System.Collections.Generic.List[string]]::new()
$mismatched = [System.Collections.Generic.List[string]]::new()
$verifiedBytes = [int64]0

foreach ($row in $rows) {
    $relativePath = [string]$row.source_relative_path
    if ([System.IO.Path]::IsPathRooted($relativePath) -or $relativePath.Split([char[]]"/\") -contains "..") {
        throw "Unsafe relative path in manifest: $relativePath"
    }

    $assetPath = [System.IO.Path]::GetFullPath((Join-Path $projectPath $relativePath))
    if (-not $assetPath.StartsWith($projectPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path resolves outside ProjectRoot: $relativePath"
    }

    if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
        $missing.Add($relativePath)
        continue
    }

    $file = Get-Item -LiteralPath $assetPath
    $actualHash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($file.Length -ne [int64]$row.bytes -or $actualHash -ne $row.sha256.ToLowerInvariant()) {
        $mismatched.Add($relativePath)
        continue
    }

    $verifiedBytes += $file.Length
}

Write-Host "Manifest entries: $($rows.Count)"
Write-Host "Verified entries: $($rows.Count - $missing.Count - $mismatched.Count)"
Write-Host "Verified bytes: $verifiedBytes"
Write-Host "Missing entries: $($missing.Count)"
Write-Host "Mismatched entries: $($mismatched.Count)"

if ($mismatched.Count -gt 0) {
    $mismatched | ForEach-Object { Write-Error "Hash or size mismatch: $_" }
    throw "External asset verification failed because one or more files differ from the frozen manifest."
}

if ($missing.Count -gt 0 -and -not $AllowMissing) {
    $missing | ForEach-Object { Write-Warning "Missing: $_" }
    throw "External assets are incomplete. Restore the listed files or rerun with -AllowMissing for inventory-only inspection."
}

if ($missing.Count -eq 0) {
    Write-Host "All external assets match the frozen manifest."
}
