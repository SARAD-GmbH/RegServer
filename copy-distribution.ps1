# Copy the distribution into a network share to prepare the installation with InnoSetup
# To be used with pre-compile.bat in the installation of Radon Vision, dVision and Rooms.
#
# Author: Michael Strey <strey@sarad.de>
# 2021-09-21
Push-Location $(Split-Path $Script:MyInvocation.MyCommand.Path)
$target = "Y:\Software\Sarad_dev\"
$source = ".\src\dist\regserver-service\"
Copy-Item -Path $source -Destination $target -Force -Recurse
Pop-Location
