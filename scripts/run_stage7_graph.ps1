[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

function Invoke-UvStep([string]$Name, [string[]]$ArgsList) {
    Write-Output "===== START $Name $(Get-Date -Format o) ====="
    & uv @ArgsList
    if ($LASTEXITCODE -ne 0) {
        Write-Output "===== FAILED $Name exit=$LASTEXITCODE $(Get-Date -Format o) ====="
        exit $LASTEXITCODE
    }
    Write-Output "===== DONE $Name $(Get-Date -Format o) ====="
}

Invoke-UvStep "answer-graph-2wiki" @(
    "run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval",
    "--config", "configs/logicpoison_answer_stage7_graph_2wiki.yaml"
)
Invoke-UvStep "judge-graph-2wiki" @(
    "run", "python", "-m", "logicguard.llm.run_answer_judge",
    "--config", "configs/logicpoison_answer_judge_stage7_graph_2wiki.yaml"
)
Invoke-UvStep "answer-graph-hotpotqa" @(
    "run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval",
    "--config", "configs/logicpoison_answer_stage7_graph_hotpotqa.yaml"
)
Invoke-UvStep "judge-graph-hotpotqa" @(
    "run", "python", "-m", "logicguard.llm.run_answer_judge",
    "--config", "configs/logicpoison_answer_judge_stage7_graph_hotpotqa.yaml"
)
Invoke-UvStep "answer-graph-musique" @(
    "run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval",
    "--config", "configs/logicpoison_answer_stage7_graph_musique.yaml"
)
Invoke-UvStep "judge-graph-musique" @(
    "run", "python", "-m", "logicguard.llm.run_answer_judge",
    "--config", "configs/logicpoison_answer_judge_stage7_graph_musique.yaml"
)

Write-Output "===== STAGE7 GRAPH ALL DONE $(Get-Date -Format o) ====="
