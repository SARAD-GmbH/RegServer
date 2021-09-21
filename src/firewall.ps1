$firewallRuleName = "SaradRegistrationServer"

write-host "Checking for '$firewallRuleName' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName))
{
    write-host "Firewall rule for '$firewallRuleName' already exists, not creating new rule"
}
else
{
    write-host "Firewall rule for '$firewallRuleName' does not exist, creating new rule now..."
    New-NetFirewallRule -DisplayName $firewallRuleName -Direction Inbound -Action Allow -Protocol TCP -Program "$%programfiles\SARAD\RegServer-Service\regserver-service.exe" -RemoteAddress LocalSubnet
    New-NetFirewallRule -DisplayName $firewallRuleName -Direction Inbound -Action Allow -Protocol UDP -Program "$%programfiles\SARAD\RegServer-Service\regserver-service.exe" -RemoteAddress LocalSubnet
    write-host "Firewall rule for '$firewallRuleName' created successfully"
}