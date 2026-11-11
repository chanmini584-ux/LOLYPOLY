# Lolypoly 코드 되돌리기 (관리자 PowerShell). update.ps1 이 끝에 알려 준 명령을 그대로 쓴다.
#   powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\rollback.ps1 -To <이전 커밋>
#
# 기본 원칙: 코드만 되돌리고 DB·사진은 그대로 둔다.
#   - 새 버전이 추가한 표·칸은 이전 코드가 무시하므로 그대로 두어도 이전 화면이 돈다(2026-11-10 시험).
#   - DB 를 업데이트 전 백업으로 덮어쓰면 그 뒤에 생긴 가입·글·댓글·의견·수집 데이터가 사라진다.
#     그래서 이 스크립트는 DB 를 복원하지 않는다. 정말 필요할 때만 docs/OPERATIONS.md 13-4 를 따라 직접 한다.
param([Parameter(Mandatory)][string]$To)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8; $env:PYTHONUTF8 = '1'
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $app '.venv\Scripts\python.exe'
if (& git.exe -C $app status --porcelain) { throw '커밋하지 않은 변경이 있습니다. 덮어쓰지 않고 멈춥니다.' }
$now = (& git.exe -C $app rev-parse HEAD).Trim()
"지금 $now → 되돌릴 커밋 $To (브랜치는 지우지 않고, 그 커밋을 임시로 꺼내 씁니다)"
& git.exe -C $app switch --detach $To; if ($LASTEXITCODE -ne 0) { throw 'git switch 실패' }
Set-Location $app
& $py -m pip install --disable-pip-version-check -r requirements.txt; if ($LASTEXITCODE -ne 0) { throw 'pip 실패' }
& $py manage.py check; if ($LASTEXITCODE -ne 0) { throw 'check 실패' }
& $py manage.py collectstatic --noinput | Select-Object -Last 1
Stop-ScheduledTask -TaskName 'Lolypoly-Web' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -like '*run_web.py*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2; Start-ScheduledTask -TaskName 'Lolypoly-Web'
"$(Get-Date -Format s) rollback from=$now to=$To" | Add-Content -Encoding UTF8 'D:\lolypoly\logs\update-history.log'
"되돌렸습니다. 확인: powershell -ExecutionPolicy Bypass -File `"$app\deploy\windows\check.ps1`""
"다시 새 버전으로: git -C `"$app`" switch <브랜치> 후 update.ps1"
