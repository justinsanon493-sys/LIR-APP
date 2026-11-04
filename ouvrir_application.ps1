param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$Port
)

$url = "http://localhost:$Port/"
$fin = (Get-Date).AddSeconds(45)

while ((Get-Date) -lt $fin) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        if ($client.Connected) {
            Start-Process $url
            exit 0
        }
    }
    catch {
        # Le serveur n'a pas encore fini de démarrer.
    }
    finally {
        $client.Dispose()
    }
    Start-Sleep -Milliseconds 500
}

exit 1
