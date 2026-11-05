# 고정 도메인을 Cloudflare Named Tunnel 로 이 PC(127.0.0.1:8000)에 연결한다. (OPERATIONS 10절)
# 전제: 도메인이 Cloudflare 계정에 추가돼 '활성'이고, 그 Chrome/브라우저에서 Cloudflare 에 로그인돼 있다.
# 사용(일반 PowerShell): powershell -ExecutionPolicy Bypass -File deploy\windows\connect_domain.ps1 -Domain lolypoly.site
#   1) 브라우저가 열리면 도메인을 골라 Authorize (cloudflared 로그인, 인증서는 이 PC 사용자 폴더에만 저장)
#   2) 터널 'lolypoly' 생성(이미 있으면 재사용) → 설정 파일 → DNS(루트, www) 를 터널로 연결
#      - 같은 이름의 기존 DNS 레코드가 있으면 덮어쓰지 않고 멈춘다(-OverwriteDns 를 줘야 덮어씀)
#   3) 부팅 시 자동 실행 작업 'Lolypoly-Tunnel' 등록(관리자 승인 창 1번) — 끊기면 cloudflared 가 스스로 재연결
#   4) .env 허용 주소에 도메인 추가 → 웹앱 재시작 → https://도메인/ 확인
# 비밀값(인증서·터널 자격 증명)은 D:\lolypoly\tunnel 과 사용자 폴더에만 두고 Git 에 넣지 않는다.
# 되돌리기: Unregister-ScheduledTask Lolypoly-Tunnel; cloudflared tunnel route dns 로 만든 CNAME 은 Cloudflare DNS 화면에서 삭제.
param([Parameter(Mandatory)][string]$Domain, [switch]$NoWww, [switch]$OverwriteDns)
$ErrorActionPreference = 'Stop'
$cf = 'D:\lolypoly\tools\cloudflared\cloudflared.exe'
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dir = 'D:\lolypoly\tunnel'
$name = 'lolypoly'
New-Item -ItemType Directory -Force $dir | Out-Null
icacls $dir /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null

# 1) 로그인 (cert.pem 이 이미 있으면 건너뜀)
$cert = Join-Path $env:USERPROFILE '.cloudflared\cert.pem'
if (-not (Test-Path $cert)) { & $cf tunnel login; if (-not (Test-Path $cert)) { throw "Cloudflare 로그인(Authorize)이 끝나지 않았어요." } }

# 2) 터널 생성/재사용
$list = & $cf tunnel list --output json | ConvertFrom-Json
$t = $list | Where-Object name -eq $name | Select-Object -First 1
if (-not $t) {
    & $cf tunnel create --credentials-file "$dir\$name.json" $name | Out-Null
    $t = (& $cf tunnel list --output json | ConvertFrom-Json) | Where-Object name -eq $name | Select-Object -First 1
}
if (-not (Test-Path "$dir\$name.json")) { throw "터널 자격 증명 파일이 없어요: $dir\$name.json (다른 PC에서 만든 터널이면 그 파일을 옮겨 오세요)" }
$hosts = @($Domain); if (-not $NoWww) { $hosts += "www.$Domain" }
$ingress = ($hosts | ForEach-Object { "  - hostname: $_`n    service: http://127.0.0.1:8000" }) -join "`n"
@"
tunnel: $($t.id)
credentials-file: $dir\$name.json
no-autoupdate: true
loglevel: info
logfile: D:\lolypoly\logs\tunnel.log
ingress:
$ingress
  - service: http_status:404
"@ | Set-Content -Encoding ascii "$dir\config.yml"
& $cf tunnel --config "$dir\config.yml" ingress validate
foreach ($h in $hosts) {
    $rargs = @('tunnel', 'route', 'dns'); if ($OverwriteDns) { $rargs += '--overwrite-dns' }
    & $cf @rargs $name $h
    if ($LASTEXITCODE -ne 0) { throw "DNS 연결 실패: $h (기존 레코드가 있으면 Cloudflare DNS 화면에서 확인 후 -OverwriteDns)" }
}

# 3) 부팅 시 자동 실행 (관리자 승인 창 1번). 웹앱과 같은 방식: S4U 일반 계정, 실패 시 1분 뒤 재시작
$reg = @"
`$a = New-ScheduledTaskAction -Execute '$cf' -Argument 'tunnel --config "$dir\config.yml" run $name'
`$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
`$p = New-ScheduledTaskPrincipal -UserId '$env:USERDOMAIN\$env:USERNAME' -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName 'Lolypoly-Tunnel' -Action `$a -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal `$p -Settings `$s -Force | Out-Null
Start-ScheduledTask -TaskName 'Lolypoly-Tunnel'
"@
$tmp = Join-Path $dir 'register-task.ps1'
[IO.File]::WriteAllText($tmp, $reg, (New-Object Text.UTF8Encoding($true)))
Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tmp
Remove-Item $tmp
if (-not (Get-ScheduledTask -TaskName 'Lolypoly-Tunnel' -ErrorAction SilentlyContinue)) { throw "자동 실행 작업 등록이 취소됐어요(관리자 승인 창에서 '예')." }

# 4) Django 허용 주소 추가 → 웹앱 재시작
$envFile = Join-Path $app '.env'
$utf8 = New-Object Text.UTF8Encoding($false)
$lines = [IO.File]::ReadAllLines($envFile, $utf8) | ForEach-Object {
    if ($_ -match '^DJANGO_ALLOWED_HOSTS=(.*)$') { $v = @($Matches[1] -split ',' | Where-Object { $_ }); $v += $hosts; "DJANGO_ALLOWED_HOSTS=$(($v | Select-Object -Unique) -join ',')" }
    elseif ($_ -match '^DJANGO_CSRF_TRUSTED_ORIGINS=(.*)$') { $v = @($Matches[1] -split ',' | Where-Object { $_ }); $v += ($hosts | ForEach-Object { "https://$_" }); "DJANGO_CSRF_TRUSTED_ORIGINS=$(($v | Select-Object -Unique) -join ',')" }
    else { $_ }
}
[IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
Stop-ScheduledTask Lolypoly-Web -ErrorAction SilentlyContinue; Start-Sleep 2; Start-ScheduledTask Lolypoly-Web

# 5) 확인 (DNS 전파에 몇 분 걸릴 수 있음)
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 10
    $code = curl.exe -s -o NUL -w "%{http_code}" -m 15 "https://$Domain/"
    if ($code -eq '200') { break }
}
"https://$Domain/ → $code"
if ($code -ne '200') { "아직 200 이 아니에요. 몇 분 뒤 다시: curl -I https://$Domain/  (로그: D:\lolypoly\logs\tunnel.log)"; exit 1 }
"연결 완료. 다음: D:\lolypoly\tools\.venv\Scripts\python.exe scripts\make_distribution.py https://$Domain/"
