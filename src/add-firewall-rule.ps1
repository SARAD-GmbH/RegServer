$firewallRuleName1 = "SaradRegistrationServer1"
$firewallRuleName2 = "SaradRegistrationServer2"
$firewallRuleName3 = "SaradRegistrationServer3"

write-host "Checking for '$firewallRuleName1' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName1))
{
    write-host "Firewall rule for '$firewallRuleName1' already exists, not creating new rule"
}
else
{
    write-host "Firewall rule for '$firewallRuleName1' does not exist, creating new rule now..."
    New-NetFirewallRule -DisplayName $firewallRuleName1 -Action Allow -Description "Allow connections to SARAD Registration Server Service" -Direction Inbound -LocalPort 50000-50500 -Protocol TCP -RemoteAddress LocalSubnet -Service SaradRegistrationServer -Program %ProgramFiles%\SARAD\RegServer-Service\regserver-service.exe
    write-host "Firewall rule for '$firewallRuleName1' created successfully"
}
write-host "Checking for '$firewallRuleName2' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName2))
{
    write-host "Firewall rule for '$firewallRuleName2' already exists, not creating new rule"
}
else
{
    write-host "Firewall rule for '$firewallRuleName2' does not exist, creating new rule now..."
    New-NetFirewallRule -DisplayName $firewallRuleName2 -Action Allow -Description "Allow connections to SARAD Registration Server Service" -Direction Inbound -LocalPort 8008 -Protocol TCP -RemoteAddress LocalSubnet
    write-host "Firewall rule for '$firewallRuleName2' created successfully"
}
write-host "Checking for '$firewallRuleName3' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName3))
{
    write-host "Firewall rule for '$firewallRuleName3' already exists, not creating new rule"
}
else
{
    write-host "Firewall rule for '$firewallRuleName3' does not exist, creating new rule now..."
    New-NetFirewallRule -DisplayName $firewallRuleName3 -Action Allow -Description "Allow connections to SARAD Registration Server Service" -Direction Inbound -LocalPort 5353 -Protocol UDP -RemoteAddress LocalSubnet
    write-host "Firewall rule for '$firewallRuleName3' created successfully"
}
