cd /D "%~dp0
.\regserver-service.exe stop
.\regserver-service.exe remove
Powershell.exe -executionpolicy remotesigned -File .\rm-firewall-rule.ps1