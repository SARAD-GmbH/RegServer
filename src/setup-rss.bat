setx THESPIAN_BASE_IPADDR 127.0.0.1 /M
cd /D "%~dp0
.\regserver-service.exe install
sc.exe config SaradRegistrationServer start= delayed-auto type= own obj= "NT AUTHORITY\LocalService" password= "0123_Kennwort"
sc.exe failure SaradRegistrationServer reset= 600 actions= restart/60000/restart/60000/restart/60000
sc.exe failureflag SaradRegistrationServer 1
.\regserver-service.exe start
:: cmd /k
