# Lolypoly Windows 작업 등록 (관리자 PowerShell 에서 실행). 여러 번 실행해도 안전(같은 이름은 덮어씀).
# 사용: powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 [-RunAs <계정>]
# 등록하는 것: 웹앱(부팅 시, 로그인 불필요) / 수집 3종 / 백업 / 절전 끄기.
# 되돌리기: Get-ScheduledTask Lolypoly-* | Unregister-ScheduledTask -Confirm:$false
param([string]$RunAs = "$env:USERDOMAIN\$env:USERNAME")
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $app '.venv\Scripts\python.exe'
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
foreach ($p in $py, (Join-Path $app '.env')) { if (-not (Test-Path $p)) { throw "없음: $p" } }
# S4U = 비밀번호 저장 없이 '로그인하지 않아도' 이 계정으로 실행. SYSTEM 은 쓰지 않는다.
$principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType S4U -RunLevel Limited

# 1) 웹앱: 부팅 시 시작, 죽으면 1분 뒤 재시작
$web = New-ScheduledTaskAction -Execute $py -Argument '"deploy\windows\run_web.py"' -WorkingDirectory $app
$webSet = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Lolypoly-Web' -Action $web -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal $principal -Settings $webSet -Force | Out-Null

# 2) 수집·백업 (D-040: 식단·일정 하루 1회, 공지 3회, 백업 매일 03:30). 놓친 실행은 켜진 뒤 실행.
$jobSet = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$jobs = @(
    @{ n = 'Collect-Meals';   j = 'meals';   t = @('06:10') },
    @{ n = 'Collect-Events';  j = 'events';  t = @('06:25') },
    @{ n = 'Collect-Notices'; j = 'notices'; t = @('06:40', '12:40', '17:40') },
    @{ n = 'Backup';          j = 'backup';  t = @('03:30') }
)
foreach ($x in $jobs) {
    $act = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $app `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$app\deploy\windows\run_job.ps1`" -Job $($x.j)"
    $trg = $x.t | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ -RandomDelay (New-TimeSpan -Minutes 5) }
    Register-ScheduledTask -TaskName "Lolypoly-$($x.n)" -Action $act -Trigger $trg -Principal $principal -Settings $jobSet -Force | Out-Null
}

# 3) 절전·최대 절전 끄기(서버용). 모니터는 꺼져도 됨.
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /hibernate off

Start-ScheduledTask -TaskName 'Lolypoly-Web'
Get-ScheduledTask -TaskName 'Lolypoly-*' | Select-Object TaskName, State | Format-Table -AutoSize
