$firewallRuleName1 = "SaradRegistrationServer1"
$firewallRuleName2 = "SaradRegistrationServer2"
$firewallRuleName3 = "SaradRegistrationServer3"

write-host "Checking for '$firewallRuleName1' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName1))
{
    write-host "Firewall rule for '$firewallRuleName1' found, removing it..."
    Remove-NetFirewallRule -DisplayName $firewallRuleName1
    write-host "Firewall rule for '$firewallRuleName1' removed successfully."
}
else
{
    write-host "Firewall rule for '$firewallRuleName1' does not exist, nothing to do."
}
write-host "Checking for '$firewallRuleName2' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName2))
{
    write-host "Firewall rule for '$firewallRuleName2' found, removing it..."
    Remove-NetFirewallRule -DisplayName $firewallRuleName2
    write-host "Firewall rule for '$firewallRuleName2' removed successfully."
}
else
{
    write-host "Firewall rule for '$firewallRuleName2' does not exist, nothing to do."
}
write-host "Checking for '$firewallRuleName3' firewall rule now...."
if ($(Get-NetFirewallRule -DisplayName $firewallRuleName3))
{
    write-host "Firewall rule for '$firewallRuleName3' found, removing it..."
    Remove-NetFirewallRule -DisplayName $firewallRuleName3
    write-host "Firewall rule for '$firewallRuleName3' removed successfully."
}
else
{
    write-host "Firewall rule for '$firewallRuleName3' does not exist, nothing to do."
}
