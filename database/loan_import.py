"""Helpers for conservative one-time property-loan imports.

The production financing records intentionally live outside source control in
``private_imports/``.  These helpers remain public so an operator can match a
private import only when an address has one exact normalized match.
"""

import re


def normalize_property_address(address: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (address or "").lower()).split())


def find_unambiguous_property_id(properties, target_address):
    target = normalize_property_address(target_address)
    matches = [row[0] for row in properties if normalize_property_address(row[1]) == target]
    return matches[0] if len(matches) == 1 else None
