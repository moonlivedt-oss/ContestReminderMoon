<#
.SYNOPSIS
  Отправить текст о конкурсе в запущенный ContestReminder из PowerShell.

.DESCRIPTION
  Берёт ключ и порт из %APPDATA%\ContestReminder\settings.json и шлёт текст в
  локальный мост программы (только 127.0.0.1). Дальше всё как при копировании
  поста: карточка «Сохранить?» в углу экрана.

.EXAMPLE
  .\cr.ps1 "Конкурс артов до 30 ноября https://example.com/art"

.EXAMPLE
  Get-Clipboard | .\cr.ps1

.EXAMPLE
  .\cr.ps1 -Ping      # проверить, запущена ли программа
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromPipeline = $true)]
    [string[]] $Text,
    [string] $Url = "",
    [switch] $Ping
)

begin {
    $ErrorActionPreference = "Stop"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $settingsPath = Join-Path $env:APPDATA "ContestReminder\settings.json"
    if (-not (Test-Path $settingsPath)) {
        Write-Error "Не найден $settingsPath - запустите ContestReminder хотя бы раз."
    }
    $settings = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $port = if ($settings.bridge_port) { [int]$settings.bridge_port } else { 47615 }
    $token = [string]$settings.bridge_token
    $base = "http://127.0.0.1:$port"
    $lines = New-Object System.Collections.Generic.List[string]
}

process {
    foreach ($t in $Text) { if ($t) { $lines.Add($t) } }
}

end {
    if ($Ping) {
        try {
            $r = Invoke-RestMethod -Uri "$base/ping" -TimeoutSec 3
            Write-Host "ContestReminder запущен ($($r.app), порт $port)."
        } catch {
            Write-Host "ContestReminder не отвечает на порту $port." -ForegroundColor Yellow
            exit 1
        }
        return
    }
    $body = ($lines -join "`n").Trim()
    if (-not $body -and -not $Url) {
        Write-Error "Нечего отправлять: передайте текст аргументом или через конвейер."
    }
    $json = @{ token = $token; text = $body; url = $Url } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        Invoke-RestMethod -Uri "$base/add" -Method Post -Body $bytes `
            -ContentType "application/json; charset=utf-8" -TimeoutSec 5 | Out-Null
        Write-Host "Отправлено - проверьте карточку в углу экрана."
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 403) {
            Write-Host "Ключ не подошёл: settings.json и программа разошлись, перезапустите её." -ForegroundColor Yellow
        } else {
            Write-Host "ContestReminder не отвечает на порту $port. Он запущен?" -ForegroundColor Yellow
        }
        exit 1
    }
}
