param([string]$At = '12:00')
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonExe = (Get-Command python -ErrorAction Stop).Source
$pythonWindowless = Join-Path (Split-Path $pythonExe -Parent) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonWindowless) { $pythonExe = $pythonWindowless }
$scriptPath = Join-Path $projectDirectory 'tools\scheduled_update.py'
$taskName = 'Swiss IPTV FR - Mise a jour GitHub'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -contains ('"' + $scriptPath + '"'))) {
    throw 'Une autre installation utilise déjà ce nom de tâche.'
}
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $scriptPath + '"') -WorkingDirectory $projectDirectory
$triggers = @((New-ScheduledTaskTrigger -Daily -At $At), (New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)))
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Contrôler les chaînes depuis Sunrise et publier les exports revus sur GitHub Pages.' -Force | Select-Object TaskName,State
