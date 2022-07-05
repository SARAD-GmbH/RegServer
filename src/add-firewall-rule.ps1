$firewallRuleName = "SaradRegistrationServer"

write-host "Checking for '$firewallRuleName' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName))
{
    write-host "Firewall rule for '$firewallRuleName' already exists, not creating new rule"
}
else
{
    write-host "Firewall rule for '$firewallRuleName' does not exist, creating new rule now..."
    New-NetFirewallRule -DisplayName $firewallRuleName -Action Allow -Description "Allow connections to SARAD Registration Server Service" -Direction Inbound -LocalPort 50000-50500,8008 -Protocol TCP -RemoteAddress LocalSubnet -Service SaradRegistrationServer
    write-host "Firewall rule for '$firewallRuleName' created successfully"
}