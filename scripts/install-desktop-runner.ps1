param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "desktop_runner.py"

& $PythonCommand -m pip install -r (Join-Path $PSScriptRoot "desktop-runner-requirements.txt")
& $PythonCommand -m playwright install chromium

$protocolKey = "HKCU:\Software\Classes\ai-job-agent"
New-Item -Path "$protocolKey\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $protocolKey -Name "(Default)" -Value "URL:AI Job Agent Protocol"
Set-ItemProperty -Path $protocolKey -Name "URL Protocol" -Value ""
Set-ItemProperty -Path "$protocolKey\shell\open\command" -Name "(Default)" -Value "`"$PythonCommand`" `"$runner`" `"%1`""

Write-Host "Desktop runner installed. Refresh the AI Job Agent dashboard and click 'Playwright ile Doldur'."
