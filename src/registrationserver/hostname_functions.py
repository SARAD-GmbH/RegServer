"""Little helper functions to handle hostnames and FQDNs

Created
    2023-04-15

Authors
    Michael Strey <strey@sarad.de>
"""
import re


def is_fqdn(hostname: str) -> bool:
    """
    Check whether a given string is a FQDN.
    https://en.m.wikipedia.org/wiki/Fully_qualified_domain_name
    """
    if not 1 < len(hostname) < 253:
        return False

    # Remove trailing dot
    if hostname[-1] == ".":
        hostname = hostname[0:-1]

    #  Split hostname into list of DNS labels
    labels = hostname.split(".")

    #  Define pattern of DNS label
    #  Can begin and end with a number or letter only
    #  Can contain hyphens, a-z, A-Z, 0-9
    #  1 - 63 chars allowed
    fqdn = re.compile(r"^[a-z0-9]([a-z-0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)

    # Check that all labels match that pattern.
    return bool(all(fqdn.match(label) for label in labels) and (len(labels) > 1))


def sanitize_hn(hostname: str) -> str:
    """Remove domain and switch to lower case."""
    return hostname.split(".")[0].casefold()


def compare_hostnames(hn1: str, hn2: str) -> bool:
    """Compare two hostnames independent from their case and whether they are FQDNs or hostnames."""
    if is_fqdn(hn1) and is_fqdn(hn2):
        return bool(hn1.casefold() == hn2.casefold())
    return bool(sanitize_hn(hn1) == sanitize_hn(hn2))
