$ErrorActionPreference = "Stop"

param(
  [Parameter(Mandatory = $true)]
  [string]$CommitMessage,

  [Parameter(Mandatory = $true)]
  [string[]]$Paths,

  [string]$Branch,

  [switch]$PushGitlab
)

function Fail($msg) {
  Write-Error $msg
  exit 1
}

function Run-Git($args) {
  & git @args
  if ($LASTEXITCODE -ne 0) {
    Fail ("git {0} failed" -f ($args -join " "))
  }
}

$today = Get-Date -Format "yyyy-MM-dd"
$memoryPath = "memory/$today.md"

if (-not $Branch) {
  $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $Branch) {
    Fail "failed to detect current branch"
  }
}

if (!(Test-Path $memoryPath)) {
  Fail "missing required daily memory file: $memoryPath"
}

# Stage declared work scope plus today's memory file.
$stageList = @($Paths + $memoryPath)
foreach ($p in $stageList) {
  if (!(Test-Path $p)) {
    Fail "path not found: $p"
  }
}
Run-Git @("add", "--") + $stageList

$staged = git diff --cached --name-only
if ($LASTEXITCODE -ne 0) {
  Fail "failed to read staged file list"
}

if (-not ($staged -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -eq $memoryPath })) {
  Fail "today memory file is not staged: $memoryPath"
}

if (-not ($staged.Trim())) {
  Fail "no staged changes; closeout aborted"
}

Run-Git @("commit", "-m", $CommitMessage)
Run-Git @("push", "origin", $Branch)

if ($PushGitlab) {
  Run-Git @("push", "gitlab", $Branch)
}

Write-Host "[closeout] success: commit + push completed"
exit 0
