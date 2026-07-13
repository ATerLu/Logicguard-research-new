param(
    [string]$LogPath = "outputs/logs/stage8_answer_run_stdout.log",
    [string]$ErrPath = "outputs/logs/stage8_answer_run_stderr.log"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $ErrPath) | Out-Null

function Invoke-UvStep {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    $start = Get-Date -Format o
    "===== START $Name $start =====" | Tee-Object -FilePath $LogPath -Append
    & uv @Arguments 2>> $ErrPath | Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Step $Name failed with exit code $LASTEXITCODE"
    }
    $end = Get-Date -Format o
    "===== DONE $Name $end =====" | Tee-Object -FilePath $LogPath -Append
}

Invoke-UvStep "answer-stage8-2wiki" @("run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval", "--config", "configs/logicpoison_answer_stage8_non_oracle_2wiki.yaml")
Invoke-UvStep "judge-stage8-2wiki" @("run", "python", "-m", "logicguard.llm.run_answer_judge", "--config", "configs/logicpoison_answer_judge_stage8_non_oracle_2wiki.yaml")
Invoke-UvStep "answer-stage8-hotpotqa" @("run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval", "--config", "configs/logicpoison_answer_stage8_non_oracle_hotpotqa.yaml")
Invoke-UvStep "judge-stage8-hotpotqa" @("run", "python", "-m", "logicguard.llm.run_answer_judge", "--config", "configs/logicpoison_answer_judge_stage8_non_oracle_hotpotqa.yaml")
Invoke-UvStep "answer-stage8-musique" @("run", "python", "-m", "logicguard.llm.run_logicpoison_answer_eval", "--config", "configs/logicpoison_answer_stage8_non_oracle_musique.yaml")
Invoke-UvStep "judge-stage8-musique" @("run", "python", "-m", "logicguard.llm.run_answer_judge", "--config", "configs/logicpoison_answer_judge_stage8_non_oracle_musique.yaml")
Invoke-UvStep "merge-stage8-answer" @("run", "python", "-m", "logicguard.llm.merge_stage8_recovery", "--config", "configs/logicpoison_stage8_answer_merge.yaml")

"===== STAGE8 ANSWER ALL DONE $(Get-Date -Format o) =====" | Tee-Object -FilePath $LogPath -Append
