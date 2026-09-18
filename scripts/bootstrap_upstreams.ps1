[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
$upstreamPath = [System.IO.Path]::GetFullPath((Join-Path $projectPath "vendor\upstream"))
if (-not $upstreamPath.StartsWith($projectPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved upstream path is outside ProjectRoot: $upstreamPath"
}

$repositories = @(
    @{
        Name = "PoisonedRAG"
        Url = "https://github.com/sleeepeer/PoisonedRAG.git"
        Commit = "f660d72174f06b13fae5163ce656e7b235db858f"
    },
    @{
        Name = "LogicPoison"
        Url = "https://github.com/Jord8061/logicPoison.git"
        Commit = "6699736681aa275e33a1d0cc32ef9b47ee17e632"
    },
    @{
        Name = "GraphRAG_Under_Fire"
        Url = "https://github.com/JACKPURCELL/GraphRAG_Under_Fire.git"
        Commit = "316422f315748a903ae8f2e94e2bedbc66f84343"
    },
    @{
        Name = "RAGDefender"
        Url = "https://github.com/SecAI-Lab/RAGDefender.git"
        Commit = "ba2a17efba165d45409114df2d70b030ade1e1b8"
    },
    @{
        Name = "HoG-GRAG"
        Url = "https://github.com/CyberScienceLab/HoG-GRAG.git"
        Commit = "b3197f5cb03b161ce4d29365ab73f1b3ed3adb02"
    },
    @{
        Name = "LightRAG"
        Url = "https://github.com/HKUDS/LightRAG.git"
        Commit = "28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c"
    }
)

function Invoke-Git {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed with exit code ${LASTEXITCODE}: git $($Arguments -join ' ')"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not available on PATH."
}

if (-not (Test-Path -LiteralPath $upstreamPath)) {
    if ($VerifyOnly) {
        throw "Upstream directory is missing: $upstreamPath"
    }
    New-Item -ItemType Directory -Path $upstreamPath -Force | Out-Null
}

foreach ($repository in $repositories) {
    $targetPath = [System.IO.Path]::GetFullPath((Join-Path $upstreamPath $repository.Name))
    if (-not $targetPath.StartsWith($upstreamPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved repository path is outside vendor/upstream: $targetPath"
    }

    $gitPath = Join-Path $targetPath ".git"
    if (Test-Path -LiteralPath $targetPath) {
        if (-not (Test-Path -LiteralPath $gitPath)) {
            throw "Refusing to overwrite non-Git path: $targetPath"
        }
    }
    elseif ($VerifyOnly) {
        throw "Missing upstream repository: $targetPath"
    }
    else {
        New-Item -ItemType Directory -Path $targetPath | Out-Null
        Invoke-Git -Arguments @("-C", $targetPath, "init")
        Invoke-Git -Arguments @("-C", $targetPath, "remote", "add", "origin", $repository.Url)
        Invoke-Git -Arguments @("-C", $targetPath, "fetch", "--depth", "1", "origin", $repository.Commit)
        Invoke-Git -Arguments @("-C", $targetPath, "checkout", "--detach", $repository.Commit)
    }

    $actualCommit = (& git -C $targetPath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $repository.Commit) {
        throw "Version mismatch for $($repository.Name): expected $($repository.Commit), got $actualCommit. Reconcile it manually; this script will not overwrite an existing checkout."
    }

    $actualRemote = (& git -C $targetPath remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualRemote -ne $repository.Url) {
        throw "Origin mismatch for $($repository.Name): expected $($repository.Url), got $actualRemote."
    }

    Write-Host "Verified $($repository.Name) at $actualCommit"
}

Write-Host "All pinned upstream repositories are ready."
