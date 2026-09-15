cd /D "%~dp0
.\regserver-service.exe stop
:wait
sc query SaradRegistrationServer | find "STOPPED" >nul || (timeout /t 1 >nul & goto wait)
.\regserver-service.exe remove
taskkill /F /IM regserver-service.exe /T 2>nul
Powershell.exe -executionpolicy remotesigned -File "%~dp0rm-firewall-rule.ps1"
REG delete "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /F /V THESPIAN_BASE_IPADDR
:: cmd /k
