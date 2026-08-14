# run_003_overnight.ps1
#
# Unattended launcher for run_003a / run_003b.
#
# Why this exists rather than a bare command line: `Experiment.save()` is called
# once, after the whole batch finishes (experiment.py). Nothing is written to
# disk incrementally, so a crash at record 174 of 175 loses the entire chunk.
# The batch is therefore split into two independent 175-record chunks writing
# separate result dirs; an outage costs at most one chunk, and each chunk is
# individually poolable with run_001 / run_002 because decoding is pinned (I3)
# and the slices are disjoint.
#
# Settings below are pinned to reproduce run_002's environment exactly, so the
# three runs pool cleanly:
#   model qwen3.5:4b, temp 0.0, top_p 1.0, decode seed 42 (GenerationConfig),
#   injection left at CLI defaults -- note that with balanced_categories=True
#   (ExperimentConfig default) corruption is a deterministic index round-robin,
#   so --seed / --injection-rate do not influence which records are corrupted.
#
# FinQA slices: run_001 = 0-199, run_002 = 200-549, run_003a = 550-724,
# run_003b = 725-899. Disjoint. test.json holds 1147 records.

# -PreflightOnly runs the Ollama readiness check and exits without touching the
# model or writing any results. Used to prove the recovery path works before
# the unattended run depends on it.
param([switch]$PreflightOnly)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- configuration
$Repo         = 'G:\deminh'
$Py           = 'C:\Users\moksh\AppData\Local\Programs\Python\Python313\python.exe'
$Runner       = Join-Path $Repo 'deminh\scripts\run_experiment.py'
$Data         = Join-Path $Repo 'FinQA\dataset\test.json'
$Results      = Join-Path $Repo 'deminh\results'
$Model        = 'qwen3.5:4b'
$OllamaUrl    = 'http://127.0.0.1:11434'
$OllamaExe    = 'C:\Users\moksh\AppData\Local\Programs\Ollama\ollama.exe'
$OllamaApp    = 'C:\Users\moksh\AppData\Local\Programs\Ollama\ollama app.exe'
$OllamaModels = 'G:\LLMs'
$MasterLog    = Join-Path $Results 'run_003_overnight.log'
$StatusFile   = Join-Path $Results 'run_003_status.json'

# Set to $false to make the script abort instead of starting an Ollama server
# itself when 11434 is not answering.
$AutoStartOllama = $true

# ---------------------------------------------------------------------- helpers
function Write-Log($Message) {
    # Write-Host, not Write-Output, deliberately. Write-Output puts the line on
    # the success stream, where it merges into the *return value* of whatever
    # function called Write-Log -- which silently turned Confirm-Ready's $false
    # into a non-empty array (truthy). Logging must not be able to change
    # control flow.
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $MasterLog -Value $line -Encoding utf8
}

function Get-OllamaTags {
    # Returns the list of model:tag names, or $null if the server is unreachable.
    try {
        $r = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 8 -ErrorAction Stop
        return @($r.models | ForEach-Object { $_.name })
    } catch {
        return $null
    }
}

function Wait-ForServer($TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $tags = Get-OllamaTags
        if ($null -ne $tags) { return $tags }
        Start-Sleep -Seconds 3
    }
    return $null
}

function Start-OllamaServer {
    # Replicates the packaged app's server environment. This matters: the model
    # store lives on G:\LLMs via OLLAMA_MODELS, which the tray app knows about
    # internally but which is NOT exported as a user/machine environment
    # variable. A bare `ollama serve` therefore comes up against an empty model
    # directory and 404s every call -- exactly the failure that cost run_002
    # ~50 wasted calls. Setting it explicitly is what prevents a repeat.
    $env:OLLAMA_MODELS            = $OllamaModels
    $env:OLLAMA_HOST              = $OllamaUrl
    $env:OLLAMA_CONTEXT_LENGTH    = '131072'
    $env:OLLAMA_FLASH_ATTENTION   = 'true'
    $env:OLLAMA_KV_CACHE_TYPE     = 'q8_0'
    $env:OLLAMA_VULKAN            = 'true'
    $env:OLLAMA_KEEP_ALIVE        = '5m0s'
    $env:OLLAMA_NUM_PARALLEL      = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '0'
    $env:OLLAMA_GPU_OVERHEAD      = '0'
    $env:OLLAMA_MAX_QUEUE         = '512'
    $env:OLLAMA_LOAD_TIMEOUT      = '5m0s'
    $env:OLLAMA_DEBUG             = 'INFO'

    $serveLog = Join-Path $Results 'run_003_ollama_serve.log'
    Write-Log "Starting '$OllamaExe serve' with OLLAMA_MODELS=$OllamaModels (log: $serveLog)"
    Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput $serveLog -RedirectStandardError "$serveLog.err"
}

function Restart-OllamaApp {
    Write-Log "Fallback: restarting the packaged 'ollama app.exe'."
    Get-Process -Name 'ollama app' -ErrorAction SilentlyContinue | ForEach-Object {
        try { Stop-Process -Id $_.Id -Force -Confirm:$false } catch {}
    }
    Start-Sleep -Seconds 3
    if (Test-Path $OllamaApp) {
        Start-Process -FilePath $OllamaApp -WindowStyle Hidden
    } else {
        Write-Log "FATAL: '$OllamaApp' not found."
    }
}

function Confirm-Ready {
    # $true only when the server answers AND the pinned model is actually
    # visible to it. The second half is the guard against the empty-model-store
    # failure mode: a server that answers but has no models will fail every
    # call immediately and burn the whole night.
    $tags = Get-OllamaTags

    if ($null -eq $tags) {
        Write-Log "Ollama not reachable at $OllamaUrl."
        if (-not $AutoStartOllama) {
            Write-Log "AutoStartOllama is disabled -- aborting."
            return $false
        }
        Start-OllamaServer
        $tags = Wait-ForServer 120
        if ($null -eq $tags) {
            Write-Log "Server did not come up within 120s after 'ollama serve'."
            Restart-OllamaApp
            $tags = Wait-ForServer 120
        }
    }

    if ($null -eq $tags) {
        Write-Log "FATAL: Ollama still unreachable. Cannot run."
        return $false
    }

    Write-Log ("Server up. Models visible: {0}" -f ($tags -join ', '))
    if ($tags -contains $Model) {
        return $true
    }

    Write-Log "FATAL: model '$Model' not visible to the server (model store likely wrong). Not running -- refusing to burn the night on 404s."
    return $false
}

function Invoke-Chunk($Name, $Offset, $Limit) {
    $out    = Join-Path $Results $Name
    $log    = Join-Path $Results "$Name.log"
    $stdout = Join-Path $Results "$Name.stdout.log"

    if (Test-Path (Join-Path $out 'summary.json')) {
        Write-Log "SKIP $Name -- $out\summary.json already exists (refusing to overwrite results)."
        return 'skipped-exists'
    }

    if (-not (Confirm-Ready)) {
        Write-Log "SKIP $Name -- Ollama preflight failed."
        return 'skipped-no-server'
    }

    $argList = @(
        $Runner,
        '--backend', 'ollama',
        '--model', $Model,
        '--host', $OllamaUrl,
        '--dataset', 'finqa',
        '--data-path', $Data,
        '--offset', $Offset,
        '--limit', $Limit,
        '--out', $out
    )

    Write-Log "START $Name  offset=$Offset limit=$Limit  -> $out"
    $started = Get-Date

    # Start-Process with explicit redirection rather than a pipeline: in Windows
    # PowerShell, `2>&1` on a native exe wraps every stderr line in an
    # ErrorRecord and corrupts the log. Python's logging goes to stderr, so the
    # stderr file is the progress log and mirrors run_002.log.
    $p = Start-Process -FilePath $Py -ArgumentList $argList -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $log
    $code = $p.ExitCode
    $mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)

    # Fold stdout (the printed summary) onto the end of the log, as run_002 had it.
    if (Test-Path $stdout) {
        Add-Content -Path $log -Value (Get-Content $stdout -Raw) -Encoding utf8
        Remove-Item $stdout -Force -ErrorAction SilentlyContinue
    }

    if ($code -eq 0 -and (Test-Path (Join-Path $out 'summary.json'))) {
        Write-Log "DONE  $Name  exit=$code  ${mins}min  summary.json written."
        return 'ok'
    }
    Write-Log "FAIL  $Name  exit=$code  ${mins}min  (no summary.json). See $log"
    return "failed-exit-$code"
}

# ------------------------------------------------------------------------- main
if (-not (Test-Path $Results)) { New-Item -ItemType Directory -Path $Results -Force | Out-Null }

if ($PreflightOnly) {
    Write-Log "---- preflight-only check (no model calls, no results written) ----"
    $ready = Confirm-Ready
    Write-Log "preflight result: $ready"
    if ($ready) { exit 0 } else { exit 1 }
}

Write-Log "================ run_003 overnight batch starting ================"
Write-Log "python=$Py"
Write-Log "model=$Model  data=$Data"

$resultA = Invoke-Chunk 'run_003a' 550 175

# run_003b is attempted regardless of run_003a's outcome: the chunks are
# independent slices, and a mid-night Ollama outage should not cost both.
$resultB = Invoke-Chunk 'run_003b' 725 175

$status = [ordered]@{
    finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    model       = $Model
    run_003a    = @{ offset = 550; limit = 175; result = $resultA }
    run_003b    = @{ offset = 725; limit = 175; result = $resultB }
}
$status | ConvertTo-Json -Depth 4 | Out-File -FilePath $StatusFile -Encoding utf8

Write-Log "run_003a=$resultA  run_003b=$resultB"
Write-Log "================ run_003 overnight batch finished ================"
