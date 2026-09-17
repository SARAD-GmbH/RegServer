cd /D "%~dp0
.\regserver-service.exe stop
set /a counter = 30
:wait
if %counter% LSS 0 goto done
set /a counter -= 1
sc query SaradRegistrationServer | find ": 1" >nul || (timeout /t 1 >nul & goto wait)
:done
.\regserver-service.exe remove
taskkill /F /IM regserver-service.exe /T 2>nul
Powershell.exe -executionpolicy remotesigned -File "%~dp0rm-firewall-rule.ps1"
REG delete "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /F /V THESPIAN_BASE_IPADDR
:: cmd /k
