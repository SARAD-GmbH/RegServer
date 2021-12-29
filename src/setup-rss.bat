cd /D "%~dp0
.\regserver-service.exe install
sc.exe config SaradRegistrationServer start= delayed-auto type= own obj= "NT AUTHORITY\LocalService" password= "0123_Kennwort"
sc.exe failure SaradRegistrationServer reset= 60 actions= restart/5000
sc.exe failureflag SaradRegistrationServer 1
.\regserver-service.exe start
