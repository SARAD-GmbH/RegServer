chcp 1252
xcopy /Y ..\dist\setup-regserver_service.exe Z:\GERÄTESOFTWARE\RegServer_Service\
"C:\Program Files (x86)\MSI Wrapper\MsiWrapperBatch.exe" config="Z:\GERÄTESOFTWARE\RegServer_Service\msi_config.xml"
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.18362.0\x64\signtool.exe" sign /sha1 85810a6da374be452b5c766a8e439385280bb42a /fd SHA256 /t http://timestamp.sectigo.com Z:\GERÄTESOFTWARE\RegServer_Service\setup-regserver_service.msi"
