$firewallRuleName = "SaradRegistrationServer"

write-host "Checking for '$firewallRuleName' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName))
{
    write-host "Firewall rule for '$firewallRuleName' found, removing it..."
    Remove-NetFirewallRule -DisplayName $firewallRuleName
    write-host "Firewall rule for '$firewallRuleName' removed successfully."
}
else
{
    write-host "Firewall rule for '$firewallRuleName' does not exist, nothing to do."
}