[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$MirrorRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $MirrorRoot '..\logicguard')).Path

if ($MirrorRoot -eq $SourceRoot) {
    throw 'Mirror and source roots must be different directories.'
}

function Assert-MirrorPath {
    param([string]$Path)

    $Resolved = [System.IO.Path]::GetFullPath($Path)
    $MirrorPrefix = $MirrorRoot.TrimEnd('\') + '\'
    if (-not $Resolved.StartsWith($MirrorPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside mirror root: $Resolved"
    }
}

function Sync-Directory {
    param(
        [string]$RelativePath,
        [string]$DestinationRelativePath = $RelativePath
    )

    $Source = Join-Path $SourceRoot $RelativePath
    $Destination = Join-Path $MirrorRoot $DestinationRelativePath
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Required source directory is missing: $Source"
    }
    Assert-MirrorPath $Destination
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Arguments = @(
        $Source,
        $Destination,
        '/MIR',
        '/XD', '__pycache__', '.pytest_cache', '.ruff_cache', '.venv', 'tmp',
        '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
    )
    if ($DryRun) {
        $Arguments += '/L'
    }
    & robocopy @Arguments
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed for $RelativePath with exit code $LASTEXITCODE"
    }
}

function Copy-RootFile {
    param([string]$Name)

    $Source = Join-Path $SourceRoot $Name
    $Destination = Join-Path $MirrorRoot $Name
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required source file is missing: $Source"
    }
    Assert-MirrorPath $Destination
    if (-not $DryRun) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
    Write-Host "root file: $Name"
}

foreach ($Directory in @('src', 'configs', 'tests', 'docs', 'scripts', 'tools', 'lib')) {
    Sync-Directory $Directory
}

foreach ($File in @('README.md', 'handoff.md', 'pyproject.toml', 'uv.lock', '.python-version')) {
    Copy-RootFile $File
}

Sync-Directory 'outputs\reports' 'artifacts\reports'

$ResultSource = Join-Path $SourceRoot 'outputs\ms_graphrag_query'
$ResultDestination = Join-Path $MirrorRoot 'artifacts\results'
Assert-MirrorPath $ResultDestination
New-Item -ItemType Directory -Path $ResultDestination -Force | Out-Null
$ResultFiles = Get-ChildItem -LiteralPath $ResultSource -File | Where-Object {
    $_.Name -match '^stage40_.*(summary\.csv|examples\.jsonl)$' -or
    $_.Name -match '^stage46_.*(summary\.csv|examples\.jsonl)$' -or
    $_.Name -match '^stage47_.*(summary\.csv|examples\.jsonl)$'
}
foreach ($ResultFile in $ResultFiles) {
    $Destination = Join-Path $ResultDestination $ResultFile.Name
    Assert-MirrorPath $Destination
    if (-not $DryRun) {
        Copy-Item -LiteralPath $ResultFile.FullName -Destination $Destination -Force
    }
    Write-Host "result artifact: $($ResultFile.Name)"
}

$AttackSource = Join-Path $SourceRoot 'outputs\adaptive_attacks'
$AttackDestination = Join-Path $MirrorRoot 'artifacts\attacks'
Assert-MirrorPath $AttackDestination
New-Item -ItemType Directory -Path $AttackDestination -Force | Out-Null
$AttackFiles = Get-ChildItem -LiteralPath $AttackSource -File | Where-Object {
    $_.Name -match '^stage47_.*_(attack_records|attack_integrity)\.jsonl$'
}
foreach ($AttackFile in $AttackFiles) {
    $Destination = Join-Path $AttackDestination $AttackFile.Name
    Assert-MirrorPath $Destination
    if (-not $DryRun) {
        Copy-Item -LiteralPath $AttackFile.FullName -Destination $Destination -Force
    }
    Write-Host "attack artifact: $($AttackFile.Name)"
}

$StatusPath = Join-Path $MirrorRoot 'MIRROR_STATUS.md'
Assert-MirrorPath $StatusPath
if (-not $DryRun) {
    $Status = @(
        '# Mirror Status',
        '',
        '- Source worktree: ../logicguard',
        "- Synced at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')",
        "- Curated result files: $($ResultFiles.Count)",
        "- Curated attack files: $($AttackFiles.Count)",
        '- Direction: source worktree to Git mirror only.'
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $StatusPath -Value $Status -Encoding utf8
}

Write-Host 'Mirror synchronization completed. Review git diff before committing.'
