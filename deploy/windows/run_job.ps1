# 수집·백업 작업 실행기 (Windows 작업 스케줄러가 호출). 한 번에 하나만 실행(이름 있는 Mutex).
# 사용: powershell -File run_job.ps1 -Job meals|events|notices|backup
param([Parameter(Mandatory)][ValidateSet('meals','events','notices','backup')][string]$Job)
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = 'D:\lolypoly\logs'
$log = Join-Path $logDir "job-$Job.log"
if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.old" -Force }
[Console]::OutputEncoding = [Text.Encoding]::UTF8; $env:TZ = 'Asia/Seoul'; $env:PYTHONUTF8 = '1'
$mutex = New-Object System.Threading.Mutex($false, 'Global\LolypolyJob')
if (-not $mutex.WaitOne([TimeSpan]::FromMinutes(20))) { "$(Get-Date -Format s) ${Job}: 다른 작업이 20분 넘게 실행 중이라 포기" | Add-Content -Encoding UTF8 $log; exit 2 }
try {
    Set-Location $app
    $py = Join-Path $app '.venv\Scripts\python.exe'
    if ($Job -eq 'backup') { $args = @('manage.py', 'backup_db', '--keep', '7') }
    else { $args = @('manage.py', 'collect_all', '--only', $Job) }
    "$(Get-Date -Format s) $Job 시작" | Add-Content -Encoding UTF8 $log
    & $py @args 2>&1 | Out-String -Stream | Add-Content -Encoding UTF8 $log
    $code = $LASTEXITCODE
    if ($Job -eq 'backup') {
        # 백업 뒤: 보관 기간이 지난 커뮤니티 내용·주인 없는 사진·끝난 세션 정리 (실패해도 백업 결과 코드는 그대로)
        & $py manage.py purge_community 2>&1 | Out-String -Stream | Add-Content -Encoding UTF8 $log
    }
    "$(Get-Date -Format s) $Job 종료 코드 $code" | Add-Content -Encoding UTF8 $log
    exit $code
} finally { $mutex.ReleaseMutex() }
