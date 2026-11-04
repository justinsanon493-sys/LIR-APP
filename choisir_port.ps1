param(
    [Parameter(Mandatory = $true)][string]$AppScript,
    [string]$WSGIScript = "",
    [int]$StartPort = 5001,
    [int]$EndPort = 5100
)

$fullAppPaths = @($AppScript, $WSGIScript) | Where-Object { $_ } | ForEach-Object { [System.IO.Path]::GetFullPath($_).Replace('/', '\').ToLowerInvariant() }
$allListeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
$usedPorts = @($allListeners | Select-Object -ExpandProperty LocalPort -Unique)

# Reuse an instance of this exact app if it already listens in our managed range.
for ($port = $StartPort; $port -le $EndPort; $port++) {
    if ($usedPorts -contains $port) {
        foreach ($listener in @($allListeners | Where-Object { $_.LocalPort -eq $port })) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
            if ($process -and $process.CommandLine) {
                $commandLine = $process.CommandLine.Replace('/', '\').ToLowerInvariant()
                $matchesApplication = $false
                foreach ($candidatePath in $fullAppPaths) {
                    if ($commandLine.Contains($candidatePath)) {
                        $matchesApplication = $true
                        break
                    }
                }
                if ($matchesApplication) {
                    Write-Output ("RUNNING|{0}|{1}" -f $port, $listener.OwningProcess)
                    exit 0
                }
            }
        }
    }
}

# Skip ports owned by other programs and return the first free one.
for ($port = $StartPort; $port -le $EndPort; $port++) {
    if ($usedPorts -notcontains $port) {
        Write-Output ("FREE|{0}" -f $port)
        exit 0
    }
}

Write-Output "NONE|0"
exit 1
