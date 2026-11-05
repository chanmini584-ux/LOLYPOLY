# LTE 시험용 임시 터널 (Cloudflare Quick Tunnel, 계정 불필요). **인쇄용 QR 에 쓰지 않는다.**
# 학교 PC 는 내부 주소(192.168.x)라 밖에서 직접 못 들어온다. 터널은 이 PC 가 Cloudflare 로 '나가는' 연결을 열고,
# 휴대폰은 https://<무작위>.trycloudflare.com 으로 들어온다. 주소는 실행할 때마다 바뀌고, 끝내면 사라진다.
# 사용: powershell -ExecutionPolicy Bypass -File deploy\windows\test_tunnel.ps1 -Start   (주소·시험 QR 출력)
#       powershell -ExecutionPolicy Bypass -File deploy\windows\test_tunnel.ps1 -Stop    (터널 종료 + 설정 원복)
param([switch]$Start, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envFile = Join-Path $app '.env'
$log = 'D:\lolypoly\logs\tunnel-test.log'
$qrPng = 'D:\lolypoly\logs\test-qr.png'
$testHost = '.trycloudflare.com'
$testOrigin = 'https://*.trycloudflare.com'
$utf8 = New-Object Text.UTF8Encoding($false)

function Set-TestHosts([bool]$on) {
    $lines = [IO.File]::ReadAllLines($envFile, $utf8)
    $out = foreach ($l in $lines) {
        if ($l -match '^(DJANGO_ALLOWED_HOSTS|DJANGO_CSRF_TRUSTED_ORIGINS)=(.*)$') {
            $key = $Matches[1]; $add = if ($key -eq 'DJANGO_ALLOWED_HOSTS') { $testHost } else { $testOrigin }
            $vals = @($Matches[2] -split ',' | Where-Object { $_ -and $_ -ne $add })
            if ($on) { $vals += $add }
            "$key=$($vals -join ',')"
        } else { $l }
    }
    [IO.File]::WriteAllLines($envFile, [string[]]$out, $utf8)
}
function Restart-Web {
    Stop-ScheduledTask Lolypoly-Web -ErrorAction SilentlyContinue; Start-Sleep 2
    Start-ScheduledTask Lolypoly-Web
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep 1
        $c = curl.exe -s -o NUL -w "%{http_code}" -m 3 -H "Host: lolypoly.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/
        if ($c -eq '200') { return }
    }
    throw "웹앱 재시작 후 200 응답 없음"
}

if ($Stop) {
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object CommandLine -like '*--url http://127.0.0.1:8000*' |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Set-TestHosts $false; Restart-Web
    Remove-Item $qrPng -ErrorAction SilentlyContinue
    "시험 터널 종료, 임시 주소 허용 제거, 웹앱 재시작 완료."
    exit 0
}
if (-not $Start) { "사용: -Start 또는 -Stop"; exit 1 }

$cf = 'D:\lolypoly\tools\cloudflared\cloudflared.exe'; if (-not (Test-Path $cf)) { $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
if (-not $cf) { $cf = Get-ChildItem "$env:ProgramFiles*\cloudflared\cloudflared.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName }
if (-not $cf) { throw "cloudflared 가 설치돼 있지 않음 (winget install Cloudflare.cloudflared)" }

Set-TestHosts $true; Restart-Web
Remove-Item $log -ErrorAction SilentlyContinue
# --http-host-header 없이: Django 가 trycloudflare 주소를 그대로 받아 리디렉션·CSRF 가 시험 주소 기준으로 동작
Start-Process $cf -ArgumentList 'tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8000', '--logfile', $log -WindowStyle Hidden
$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep 1
    $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
}
if (-not $url) { throw "60초 안에 시험 주소를 못 받음. 로그: $log" }
$qrPy = 'D:\lolypoly\tools\.venv\Scripts\python.exe'
if (Test-Path $qrPy) { & $qrPy -c "import qrcode,sys; qrcode.make(sys.argv[1], border=4).save(sys.argv[2])" $url $qrPng; "시험 QR: $qrPng" }
"시험 주소: $url"
"휴대폰 Wi-Fi 를 끄고 LTE/5G 로 위 주소를 연다. 끝나면 -Stop."
