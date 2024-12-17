cd /D "%~dp0
.\regserver-service.exe stop
.\regserver-service.exe remove
Powershell.exe -executionpolicy remotesigned -File "%~dp0rm-firewall-rule.ps1"
REG delete "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /F /V THESPIAN_BASE_IPADDR
:: cmd /k
