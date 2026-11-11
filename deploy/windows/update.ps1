# Lolypoly 학교 PC 업데이트 (관리자 PowerShell 에서 실행)
#   powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\update.ps1 -Branch main
#   -DryRun  : 아무것도 바꾸지 않고 지금 상태와 가져올 변경만 보여 준다
# 처음 한 번은 이 파일이 아직 학교 PC 에 없으므로 docs/OPERATIONS.md 13-1 의 '처음 가져오기' 두 줄을 먼저 실행한다.
#
# 순서: ① 상태 확인(미커밋 변경이 있으면 멈춤) → ② 지금 코드로 DB 백업·검증 + 업데이트 전 사본
#       → ③ 코드 가져오기(fast-forward 만, 강제 pull/reset 없음) → ④ 패키지 설치 → ⑤ 점검·마이그레이션(추가만 함)
#       → ⑥ 정적 파일 → ⑦ 웹앱 재시작 → ⑧ 응답 점검 → 되돌리는 방법 안내
# .env, Cloudflare 자격 증명, 작업 스케줄러 등록, D:\lolypoly\data 의 DB·사진은 건드리지 않는다.
param([string]$Branch = 'main', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8; $env:PYTHONUTF8 = '1'; $env:TZ = 'Asia/Seoul'
# 이 파일이 app\deploy\windows 안에 있으면 그 app, 아니면(임시 폴더에 꺼내 실행) 기본 위치
$app = if ($PSScriptRoot -like '*\deploy\windows') { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) } else { 'D:\lolypoly\app' }
$py = Join-Path $app '.venv\Scripts\python.exe'
$logDir = 'D:\lolypoly\logs'; $backupDir = 'D:\lolypoly\data\backups'
$history = Join-Path $logDir 'update-history.log'
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Run([string[]]$a) { & $py @a; if ($LASTEXITCODE -ne 0) { throw "실패: python $($a -join ' ') (종료 코드 $LASTEXITCODE)" } }
# PowerShell 은 대소문자를 가리지 않아 함수 이름을 Git 으로 하면 git 호출이 자기 자신을 다시 불러 무한 반복된다(ERR-009). 이름을 다르게 하고 git.exe 를 직접 부른다.
function AppGit([string[]]$a) { & git.exe -C $app @a; if ($LASTEXITCODE -ne 0) { throw "실패: git $($a -join ' ')" } }
# 표별 행 수(읽기 전용, sqlite3 로 직접 센다 — 업데이트 전의 옛 코드에서도 똑같이 동작)
$countPy = Join-Path $env:TEMP 'lolypoly_row_counts.py'
@'
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0].startswith(("campus_", "accounts_", "community_"))]
print(" ".join("%s=%d" % (n, con.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0]) for n in sorted(names)))
'@ | Set-Content -Encoding UTF8 $countPy
function Counts { (& $py $countPy $dbPath | Select-Object -Last 1) }

Step '1. 지금 상태'
if (-not (Test-Path $py)) { throw "가상환경이 없습니다: $py" }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$old = (& git.exe -C $app rev-parse HEAD).Trim(); $oldBranch = (& git.exe -C $app rev-parse --abbrev-ref HEAD).Trim()
"코드 위치: $app`n브랜치: $oldBranch  커밋: $old"
$dirty = & git.exe -C $app status --porcelain
if ($dirty) { $dirty; throw '커밋하지 않은 변경이 있습니다. 덮어쓰지 않고 멈춥니다. 변경을 확인(보존)한 뒤 다시 실행하세요.' }
AppGit @('fetch', 'origin', $Branch)
$new = (& git.exe -C $app rev-parse "origin/$Branch").Trim()
"가져올 커밋: $new"
& git.exe -C $app merge-base --is-ancestor $old $new
if ($LASTEXITCODE -ne 0) { throw "지금 코드($old)가 origin/$Branch 의 조상이 아닙니다(갈라짐). 강제로 맞추지 않고 멈춥니다." }
if ($old -eq $new) { '이미 최신입니다.' } else { & git.exe -C $app log --oneline "$old..$new" | Select-Object -First 15 }
$dbPath = ((Get-Content (Join-Path $app '.env') | Where-Object { $_ -match '^\s*DJANGO_SQLITE_PATH=' }) -replace '^[^=]*=', '' | Select-Object -First 1)
if (-not $dbPath) { $dbPath = Join-Path $app 'db.sqlite3' }; $dbPath = $dbPath.Trim().Trim('"')
"DB: $dbPath"
$before = Counts; "업데이트 전 행 수: $before"
$envText = Get-Content (Join-Path $app '.env') -ErrorAction SilentlyContinue
foreach ($k in 'DJANGO_HTTPS=True', 'DJANGO_SQLITE_PATH=') { if (-not ($envText -match "^\s*$([regex]::Escape($k))")) { Write-Warning ".env 에 '$k' 줄이 보이지 않습니다. 로그인 쿠키 보호(HTTPS 전용)와 DB·사진 위치에 필요합니다. docs/OPERATIONS.md 13장 확인." } }
if ($DryRun) { "`n-DryRun: 여기까지 확인만 했습니다. 바뀐 것은 없습니다."; exit 0 }
if (-not $admin) { throw '웹앱 재시작에 관리자 권한이 필요합니다. 관리자 PowerShell 에서 다시 실행하세요. (확인만 하려면 -DryRun)' }

Step '2. 백업 (지금 코드 기준) + 검증'
Set-Location $app
Run @('manage.py', 'backup_db', '--dir', $backupDir, '--keep', '7')
$latest = Get-ChildItem $backupDir -Filter 'lolypoly-*.sqlite3.gz' | Sort-Object Name | Select-Object -Last 1
Run @('manage.py', 'backup_db', '--verify', $latest.FullName)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$keepCopy = Join-Path $backupDir "preupdate-$stamp-$($old.Substring(0,7)).sqlite3.gz"   # 자동 정리 대상이 아닌 이름
Copy-Item $latest.FullName $keepCopy
"업데이트 전 사본: $keepCopy"
"$(Get-Date -Format s) update start old=$old new=$new backup=$keepCopy" | Add-Content -Encoding UTF8 $history

Step '3. 코드 가져오기 (fast-forward 만)'
if ($oldBranch -ne $Branch) {
    & git.exe -C $app show-ref --verify --quiet "refs/heads/$Branch"
    if ($LASTEXITCODE -eq 0) { AppGit @('switch', $Branch) } else { AppGit @('switch', '-c', $Branch, '--track', "origin/$Branch") }
}
AppGit @('merge', '--ff-only', "origin/$Branch")

try {
    Step '4. 패키지 설치'
    Run @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements.txt')
    Step '5. 점검·마이그레이션 (표·칸 추가만, 기존 데이터 삭제 없음)'
    Run @('manage.py', 'check')
    Run @('manage.py', 'migrate', '--plan')
    Run @('manage.py', 'migrate', '--noinput')
    $after = Counts; "업데이트 후 행 수: $after"
    foreach ($pair in ($before -split ' ')) { $name, $n = $pair -split '='; $m = ($after -split ' ' | Where-Object { $_ -like "$name=*" }) -replace '.*=', ''
        if ($m -eq '' -or [int]$m -lt [int]$n) { throw "행 수가 줄었습니다: $name $n → $m. 재시작하지 않고 멈춥니다." } }
    '기존 표의 행 수가 그대로이거나 늘었습니다.'
    Step '6. 정적 파일'
    Run @('manage.py', 'collectstatic', '--noinput')
    New-Item -ItemType Directory -Force (Join-Path (Split-Path $backupDir -Parent) 'media') | Out-Null
} catch {
    "$(Get-Date -Format s) update FAILED before restart: $_" | Add-Content -Encoding UTF8 $history
    Write-Warning "실패했습니다. 웹앱은 재시작하지 않았으므로 이전 코드가 메모리에서 계속 돌고 있습니다. 코드는 새 버전 상태입니다."
    Write-Warning "되돌리기: powershell -ExecutionPolicy Bypass -File `"$app\deploy\windows\rollback.ps1`" -To $old"
    throw
}

Step '7. 웹앱 재시작'
Stop-ScheduledTask -TaskName 'Lolypoly-Web' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -like '*run_web.py*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
Start-ScheduledTask -TaskName 'Lolypoly-Web'

Step '8. 응답 점검'
$hostHeader = ((Get-Content (Join-Path $app '.env') | Where-Object { $_ -match '^\s*DJANGO_ALLOWED_HOSTS=' }) -replace '^[^=]*=', '' -split ',')[0].Trim()
$ok = $true
foreach ($t in @(@('/', '200'), @('/meals/', '200'), @('/sw.js', '200'), @('/community/', '302'), @('/community/rules/', '200'), @('/accounts/login/', '200'))) {
    $code = ''
    foreach ($i in 1..15) { $code = curl.exe -s -o NUL -w '%{http_code}' -m 5 -H "Host: $hostHeader" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:8000$($t[0])"; if ($code -eq $t[1]) { break }; Start-Sleep 1 }
    "{0,-22} {1} (기대 {2})" -f $t[0], $code, $t[1]
    if ($code -ne $t[1]) { $ok = $false }
}
"$(Get-Date -Format s) update done new=$new health=$ok" | Add-Content -Encoding UTF8 $history
if ($ok) { Write-Host "`n업데이트 완료. 공개 주소에서도 한 번 열어 확인하세요." -ForegroundColor Green }
else { Write-Warning "응답이 기대와 다릅니다. $logDir 의 로그를 확인하고, 필요하면 아래로 되돌리세요." }
"되돌리기(코드만, DB·사진은 그대로 둠): powershell -ExecutionPolicy Bypass -File `"$app\deploy\windows\rollback.ps1`" -To $old"
