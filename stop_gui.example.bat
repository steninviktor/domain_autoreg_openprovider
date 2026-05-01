@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -like 'python*' -or $_.Name -like 'py.exe') -and $_.CommandLine -like '*domain_autoreg.cli*' -and $_.CommandLine -like '* gui*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
