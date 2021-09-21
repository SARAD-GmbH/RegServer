cd /D "%~dp0
.\regserver-service.exe stop
:loop
	timeout /T 10 /nobreak
	for /f %%a in ('.\regserver-service.exe status') do set REPLY=%%a
        echo %REPLY%
	if %REPLY% neq S goto loop
.\regserver-service.exe remove
