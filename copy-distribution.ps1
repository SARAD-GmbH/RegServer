# Copy the distribution into a network share to prepare the installation with InnoSetup
# To be used with pre-compile.bat in the installation of Radon Vision, dVision and Rooms.
#
# Author: Michael Strey <strey@sarad.de>
# 2021-09-21
Push-Location $(Split-Path $Script:MyInvocation.MyCommand.Path)
$target = "Y:\Software\Sarad_dev\"
$source = ".\src\dist\regserver-service\"
$signfile = $target + "regserver-service\regserver-service.exe"
Copy-Item -Path $source -Destination $target -Force -Recurse
$cmd = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.18362.0\x64\signtool.exe'
$arg = @('sign', '/tr', 'http://timestamp.comodoca.com', '/td', 'sha256', '/du', 'https://www.sarad.de')
& $cmd $arg $signfile
Pop-Location
