# Lolypoly 상태 점검 (관리자 권한 불필요). 사용: powershell -ExecutionPolicy Bypass -File deploy\windows\check.ps1
$os = Get-CimInstance Win32_OperatingSystem
"지금: $(Get-Date -Format s) / 마지막 부팅: $($os.LastBootUpTime.ToString('s'))"
Get-ScheduledTask Lolypoly-* | Get-ScheduledTaskInfo |
    Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime | Format-Table -AutoSize
$code = curl.exe -s -o NUL -w "%{http_code}" -m 5 -H "Host: lolypoly.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/
"웹앱(127.0.0.1:8000): $code  (200 이면 정상)"
$web = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -like '*run_web.py*'
"웹앱 프로세스: " + ($(if ($web) { "실행 중 (PID $($web.ProcessId -join ','))" } else { "없음" }))
Get-ChildItem D:\lolypoly\data\backups -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 3 Name, LastWriteTime, Length | Format-Table -AutoSize
