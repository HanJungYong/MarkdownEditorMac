[CmdletBinding()]
param(
    [string]$InstallRoot = $(
        if ($env:MARKDOWNEDITOR_INSTALL_ROOT) {
            $env:MARKDOWNEDITOR_INSTALL_ROOT
        }
        else {
            Join-Path $env:LOCALAPPDATA "Programs\MarkdownEditor"
        }
    ),
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut,
    [switch]$NoRegistry
)

$ErrorActionPreference = "Stop"
$ProductName = "MarkdownEditor"
$ProductVersion = "0.1.0"
$TemporaryPayload = $null
if ($env:MARKDOWNEDITOR_TEST_MODE -eq "1") {
    $NoDesktopShortcut = $true
    $NoStartMenuShortcut = $true
    $NoRegistry = $true
}

function Get-PayloadRoot {
    $directExecutable = Join-Path $PSScriptRoot "app\MarkdownEditor.exe"
    if (Test-Path -LiteralPath $directExecutable -PathType Leaf) {
        return $PSScriptRoot
    }

    $payloadArchive = Join-Path $PSScriptRoot "payload.zip"
    if (-not (Test-Path -LiteralPath $payloadArchive -PathType Leaf)) {
        throw "설치 파일에서 app\MarkdownEditor.exe 또는 payload.zip을 찾을 수 없습니다."
    }

    $script:TemporaryPayload = Join-Path ([IO.Path]::GetTempPath()) (
        "MarkdownEditor_Setup_" + [guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $script:TemporaryPayload | Out-Null
    Expand-Archive -LiteralPath $payloadArchive -DestinationPath $script:TemporaryPayload -Force
    $candidate = Get-ChildItem -LiteralPath $script:TemporaryPayload -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "app\MarkdownEditor.exe") } |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "payload.zip에서 MarkdownEditor 실행 파일을 찾을 수 없습니다."
    }
    return $candidate.FullName
}

function New-ApplicationShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$ExecutablePath
    )
    $parent = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $ExecutablePath
    $shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $shortcut.IconLocation = "$ExecutablePath,0"
    $shortcut.Description = "Markdown 문서 편집기"
    $shortcut.Save()
}

try {
    $running = Get-Process -Name "MarkdownEditor" -ErrorAction SilentlyContinue
    if ($running) {
        throw "MarkdownEditor가 실행 중입니다. 프로그램을 종료한 뒤 다시 설치하세요."
    }

    $payloadRoot = Get-PayloadRoot
    $sourceApp = Join-Path $payloadRoot "app"
    $parent = Split-Path -Parent $InstallRoot
    $leaf = Split-Path -Leaf $InstallRoot
    New-Item -ItemType Directory -Path $parent -Force | Out-Null

    $staging = Join-Path $parent ("$leaf.installing." + [guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent ("$leaf.previous." + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $staging | Out-Null
    Copy-Item -LiteralPath $sourceApp -Destination (Join-Path $staging "app") -Recurse
    Copy-Item -LiteralPath (Join-Path $payloadRoot "uninstall.ps1") -Destination $staging
    Copy-Item -LiteralPath (Join-Path $payloadRoot "uninstall.cmd") -Destination $staging
    foreach ($document in @("설치_안내.txt", "THIRD_PARTY_NOTICES.md")) {
        $sourceDocument = Join-Path $payloadRoot $document
        if (Test-Path -LiteralPath $sourceDocument) {
            Copy-Item -LiteralPath $sourceDocument -Destination $staging
        }
    }

    if (Test-Path -LiteralPath $InstallRoot) {
        Move-Item -LiteralPath $InstallRoot -Destination $backup
    }
    try {
        Move-Item -LiteralPath $staging -Destination $InstallRoot
    }
    catch {
        if (Test-Path -LiteralPath $backup) {
            Move-Item -LiteralPath $backup -Destination $InstallRoot
        }
        throw
    }
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }

    $installedExecutable = Join-Path $InstallRoot "app\MarkdownEditor.exe"
    if (-not $NoStartMenuShortcut) {
        $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
        New-ApplicationShortcut -ShortcutPath (
            Join-Path $startMenu "MarkdownEditor\MarkdownEditor.lnk"
        ) -ExecutablePath $installedExecutable
        New-ApplicationShortcut -ShortcutPath (
            Join-Path $startMenu "MarkdownEditor\MarkdownEditor 제거.lnk"
        ) -ExecutablePath (Join-Path $InstallRoot "uninstall.cmd")
    }
    if (-not $NoDesktopShortcut) {
        $desktop = [Environment]::GetFolderPath("Desktop")
        New-ApplicationShortcut -ShortcutPath (
            Join-Path $desktop "MarkdownEditor.lnk"
        ) -ExecutablePath $installedExecutable
    }

    if (-not $NoRegistry) {
        $uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MarkdownEditor"
        New-Item -Path $uninstallKey -Force | Out-Null
        New-ItemProperty -Path $uninstallKey -Name "DisplayName" -Value $ProductName -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "DisplayVersion" -Value $ProductVersion -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "Publisher" -Value "MarkdownEditor contributors" -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "InstallLocation" -Value $InstallRoot -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "DisplayIcon" -Value $installedExecutable -Force |
            Out-Null
        $uninstallCommand = '"' + (Join-Path $InstallRoot "uninstall.cmd") + '"'
        New-ItemProperty -Path $uninstallKey -Name "UninstallString" -Value $uninstallCommand -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "NoModify" -Value 1 -PropertyType DWord -Force |
            Out-Null
        New-ItemProperty -Path $uninstallKey -Name "NoRepair" -Value 1 -PropertyType DWord -Force |
            Out-Null

        $applicationKey = "HKCU:\Software\Classes\Applications\MarkdownEditor.exe"
        New-Item -Path "$applicationKey\shell\open\command" -Force | Out-Null
        Set-Item -Path "$applicationKey\shell\open\command" -Value (
            '"' + $installedExecutable + '" "%1"'
        )
        New-Item -Path "$applicationKey\SupportedTypes" -Force | Out-Null
        New-ItemProperty -Path "$applicationKey\SupportedTypes" -Name ".md" -Value "" -Force |
            Out-Null
        New-ItemProperty -Path "$applicationKey\SupportedTypes" -Name ".markdown" -Value "" -Force |
            Out-Null
    }

    Write-Host "MarkdownEditor $ProductVersion 설치를 완료했습니다."
    Write-Host "설치 위치: $InstallRoot"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if ($TemporaryPayload -and (Test-Path -LiteralPath $TemporaryPayload)) {
        Remove-Item -LiteralPath $TemporaryPayload -Recurse -Force -ErrorAction SilentlyContinue
    }
}
