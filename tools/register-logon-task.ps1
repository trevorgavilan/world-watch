<#
Registers the Windows Scheduled Task "World Watch (logon)": at Trevor's logon it runs
`pythonw -m worldwatch logon` — fetch, build Morning Recon, open it in the browser, then keep
collecting on each source's interval until logoff. One copy at a time (the task setting and an
OS file lock in the code). Restarts up to 3 times if it crashes.

    powershell -ExecutionPolicy Bypass -File tools\register-logon-task.ps1           # register
    powershell -ExecutionPolicy Bypass -File tools\register-logon-task.ps1 -WhatIf   # show only
    Unregister-ScheduledTask -TaskName "World Watch (logon)" -Confirm:$false         # remove
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Python = "C:\Python313\pythonw.exe"
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $Python)) { throw "pythonw not found at $Python" }
if (-not (Test-Path (Join-Path $repo "worldwatch\__main__.py"))) { throw "worldwatch package not found under $repo" }

$taskName = "World Watch (logon)"
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $Python -Argument "-m worldwatch logon" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($taskName, "Register scheduled task (runs $Python -m worldwatch logon in $repo)")) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "World Watch: build Morning Recon at logon and keep collecting public feeds." -Force | Out-Null
    Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
}
