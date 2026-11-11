# 隧道守护循环：ssh 断了自动重连，永不退出
# 由「启动全套服务.ps1」以脱离进程树的方式启动

$key    = 'D:\dshworks\qqbot\ssh\id_ed25519'
$known  = 'D:/dshworks/qqbot/ssh/known_hosts'
$server = 'admin@116.62.149.191'
$log    = 'D:\dshworks\voice\tunnel-loop.log'
$sshOpt = @('-i', $key, '-o', 'StrictHostKeyChecking=accept-new', "-o", "UserKnownHostsFile=$known",
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3')

function Log($m) {
    Add-Content -Path $log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $m" -Encoding UTF8
}

# 动态找 DSH 端口：只要「监听端口 + 进程是 DeepSeek Harness」就算，再退回候选端口探测
function Find-DshPort {
    try {
        $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
        $harnessPids = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'DeepSeek Harness.exe' -or $_.Name -like '*Harness*' } |
            Select-Object -ExpandProperty ProcessId)
        if ($harnessPids.Count -gt 0) {
            $ports = @($listeners | Where-Object { $harnessPids -contains $_.OwningProcess } |
                Select-Object -ExpandProperty LocalPort -Unique)
            foreach ($p in $ports) {
                try {
                    Invoke-WebRequest -Uri "http://127.0.0.1:$p/" -TimeoutSec 3 -ErrorAction Stop | Out-Null
                    return $p
                } catch {
                    if ($_.Exception.Response) { return $p }
                }
            }
        }
    } catch {}

    # 退回：探测历史见过的端口（DSH 每次重启会换端口）
    foreach ($p in 2016, 1809, 14960, 13280, 12682, 1176, 5942, 2185, 7453, 2875, 4598, 19387) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$p/" -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $p }
        } catch {
            # 401/403 也说明服务活着
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -in 401, 403) { return $p }
        }
    }
    return $null
}

Log '=== 隧道守护启动（v2：端口探测更稳）==='
while ($true) {
    $dsh = Find-DshPort
    $remoteClean = 'for port in 4598 9900 9902 9906; do for p in $(sudo ss -lntp 2>/dev/null | grep ":$port" | grep -oE "pid=[0-9]+" | cut -d= -f2 | sort -u); do sudo kill -9 $p 2>/dev/null; done; done'

    # 9903（网页渲染）已于 2026-10-29 迁到服务器本地，不再需要转发
    $fwd = @('-R', '9900:127.0.0.1:9900', '-R', '9902:127.0.0.1:9902', '-R', '9906:127.0.0.1:9906')
    if ($dsh) {
        $fwd += @('-R', "4598:127.0.0.1:$dsh")
    } else {
        Log '⚠ 没探测到 DSH 端口，只转发 9900/9902'
    }

    try { & ssh.exe @sshOpt $server $remoteClean 2>$null | Out-Null } catch {}

    Log "连接中… DSH=$dsh"
    $sshArgs = $sshOpt + @('-o', 'ExitOnForwardFailure=yes', '-N') + $fwd + @($server)

    # 用 Start-Process 起 ssh，最多跑 30 分钟就主动重连一次。
    # 原因：DSH 每次重启都会换端口（1809→2016…），而 ssh 一旦连上就不会重新探测，
    # 于是 4598 会一直指向旧端口，机器人就 fetch failed（2026-11-05 事故）。
    $proc = Start-Process -FilePath 'ssh.exe' -ArgumentList $sshArgs -NoNewWindow -PassThru -RedirectStandardError "$log.err" -RedirectStandardOutput "$log.out"
    $deadline = (Get-Date).AddMinutes(30)
    while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 20
        # 期间如果探测到的 DSH 端口变了，立刻重连
        $nowDsh = Find-DshPort
        if ($nowDsh -and $dsh -and ($nowDsh -ne $dsh)) {
            Log "⚠ DSH 端口变了（$dsh → $nowDsh），重启隧道"
            break
        }
        if (-not $nowDsh -and $dsh) { Log "⚠ DSH 端口探测不到了，重启隧道"; break }
    }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    if (Test-Path "$log.err") {
        $err = Get-Content "$log.err" -Tail 3 -ErrorAction SilentlyContinue
        if ($err) { Log ("ssh: " + ($err -join ' / ')) }
    }
    Log "ssh 退出，5 秒后重连"
    Start-Sleep -Seconds 5
}
