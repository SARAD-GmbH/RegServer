$venvoutput = pipenv --venv
$sites = (Get-Item $venvoutput[0]).FullName + "\Lib\site-packages"
$src =  (Get-Item $venvoutput[0]).FullName + "\src" 
Copy-Item $sites .\temp\bin -Force
Copy-Item $src\* .\temp\src -Force
