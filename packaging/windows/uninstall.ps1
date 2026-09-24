[CmdletBinding()]
param(
    [string]$InstallRoot = $PSScriptRoot,
    [switch]$NoShortcuts,
    [switch]$NoRegistry,
    [switch]$Immediate
)

$ErrorActionPreference = "Stop"

try {
    $running = Get-Process -Name "MarkdownEditor" -ErrorAction SilentlyContinue
    if ($running) {
        throw "MarkdownEditor가 실행 중입니다. 프로그램을 종료한 뒤 다시 제거하세요."
    }

    if (-not $NoShortcuts) {
        $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "MarkdownEditor.lnk"
        Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
        $startMenuFolder = Join-Path $env:APPDATA (
            "Microsoft\Windows\Start Menu\Programs\MarkdownEditor"
        )
        Remove-Item -LiteralPath $startMenuFolder -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $NoRegistry) {
        Remove-Item -Path (
            "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MarkdownEditor"
        ) -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -Path (
            "HKCU:\Software\Classes\Applications\MarkdownEditor.exe"
        ) -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($Immediate) {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    }
    else {
        $escapedRoot = $InstallRoot.Replace("'", "''")
        $cleanup = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$escapedRoot' -Recurse -Force"
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cleanup
        ) | Out-Null
    }
    Write-Host "MarkdownEditor 제거를 완료했습니다."
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
