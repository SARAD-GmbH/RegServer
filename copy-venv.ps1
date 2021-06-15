$target = "Y:\Software\Sarad_dev\RadonVision"
$venvoutput = pipenv --venv
$target_bin = "$($target)\bin\"
$target_packages = "$($target)\site-packages\"
$source_packages1 = (Get-Item $venvoutput[0]).FullName + "\Lib\site-packages\*"
$source_packages2 = (Get-Item $venvoutput[0]).FullName + "\src\data-collector\sarad\"
$source_bin = ".\src\"
Get-ChildItem -Path $source_packages1 -Directory | Copy-Item -Destination $target_packages -Force -Recurse
Get-ChildItem -Path $source_packages1 -File | ? {$_.Name -notlike "*virtualenv*"} | Copy-Item -Destination $target_packages -Force
Copy-Item -Path $source_packages2 -Destination $target_packages -Force -Recurse
Get-ChildItem -Path $source_bin -File | Copy-Item -Destination $target_bin -Force
Get-ChildItem -Path $source_bin -Directory | Copy-Item -Destination $target_packages -Force -Recurse
Copy-Item -Path "$($target_packages)\pywin32_system32\pywintypes38.dll" -Destination "$($target_packages)\win32\"
