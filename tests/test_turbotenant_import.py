import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from webapp.services.turbotenant_import import (
    ChargeRow,
    DepositRow,
    PropertyRecord,
    TenantRecord,
    match_charges,
    match_deposits,
    map_charge_type,
    map_payment_method,
    normalize_address,
    normalize_name,
    read_rent_roll,
)


class TurboTenantImportTests(unittest.TestCase):
    def test_maps_source_categories_and_methods(self):
        self.assertEqual(map_charge_type("RENT"), "rent")
        self.assertEqual(map_charge_type("UTILITY_CHARGE"), "utility")
        self.assertEqual(map_charge_type("unknown"), "other")
        self.assertEqual(map_payment_method("BANK_ACCOUNT"), "ach")
        self.assertEqual(map_payment_method("DEBIT_CARD"), "card")
        self.assertEqual(map_payment_method("PREPAID"), "card")

    def test_normalizes_names_and_addresses(self):
        self.assertEqual(normalize_name("Toney  Baker"), "toney baker")
        self.assertEqual(normalize_name("James Ingram Jr."), "james ingram")
        self.assertEqual(
            normalize_address("11035 Republic Avenue, #2"),
            normalize_address("11035 Republic Ave. Apt. 2"),
        )
        self.assertEqual(
            normalize_address("11268 Dodge Avenue, #"),
            normalize_address("11268 Dodge Ave"),
        )
        self.assertEqual(
            normalize_address("3616 Wasmund Ave, #apt 2"),
            normalize_address("3616 Wasmund Ave Apt 2"),
        )
        self.assertEqual(
            normalize_address("11035 Republic Ave Apt. 1, #1"),
            normalize_address("11035 Republic Ave Apt 1"),
        )

    def test_duplicate_tenant_at_property_is_ambiguous(self):
        props = [PropertyRecord(1, "11268 Dodge Ave")]
        tenants = [
            TenantRecord(10, 1, "Toney Baker"),
            TenantRecord(11, 1, "Toney Baker"),
        ]
        row = DepositRow(
            2, "123", Decimal("100.00"), date(2026, 1, 2), "Toney Baker",
            "BANK_ACCOUNT", "11268 Dodge Avenue, #", "", date(2026, 1, 1),
            "Checking", "June 1st Lease",
        )
        match = match_deposits([row], props, tenants)[0]
        self.assertEqual(match.status, "ambiguous")
        self.assertEqual(match.reason, "duplicate_tenant_at_property")

    def test_unique_active_resident_can_receive_payment_from_another_payer(self):
        props = [PropertyRecord(1, "6300 Canyon St, Warren, MI 48091")]
        tenants = [TenantRecord(10, 1, "James Ingram", True)]
        row = DepositRow(
            2, "456", Decimal("750.00"), date(2026, 1, 2), "Tyrese Smith Jr.",
            "BANK_ACCOUNT", "6300 Canyon St", "", date(2026, 1, 1),
            "Checking", "6300 Canyon Ave - James Ingram",
        )
        match = match_deposits([row], props, tenants)[0]
        self.assertEqual(match.status, "matched")
        self.assertEqual(match.tenant_id, 10)
        self.assertEqual(match.reason, "address_single_active_tenant")

    def test_out_of_scope_property_is_excluded(self):
        row = DepositRow(
            2, "789", Decimal("2000.00"), date(2026, 1, 2), "Outside Tenant",
            "BANK_ACCOUNT", "3700 SW 16th Street, #", "", date(2026, 1, 1),
            "Checking", "Outside Lease",
        )
        match = match_deposits(
            [row],
            [],
            [],
            [PropertyRecord(-1, "3700 SW 16th St")],
        )[0]
        self.assertEqual(match.status, "excluded")
        self.assertEqual(match.reason, "property_out_of_scope")

    def test_exact_out_of_scope_lease_is_excluded(self):
        charge = ChargeRow(
            2, date(2026, 1, 1), "OTHER", "", "Blank Lease", "PAST DUE",
            Decimal("500.00"), Decimal("500.00"), "source-key",
        )
        match = match_charges(
            [charge], [], [], [], [], excluded_lease_titles=["Blank Lease"]
        )[0]
        self.assertEqual(match.status, "excluded")
        self.assertEqual(match.reason, "property_out_of_scope")

    def test_reads_rent_roll_metadata_line(self):
        content = (
            "Pulled on 09/25/2026\n"
            "Property,Unit,Tenants,Lease Start,Lease End,Security Deposit,Rent Amount,Total Unpaid,Total Past Due\n"
            "11268 Dodge Ave,,Toney Baker,-,Month-to-month,$1000,$1500,$0,$0\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rent_roll.csv"
            path.write_text(content, encoding="utf-8")
            rows = read_rent_roll(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tenant_names, "Toney Baker")
        self.assertIsNone(rows[0].lease_start)
        self.assertIsNone(rows[0].lease_end)


if __name__ == "__main__":
    unittest.main()
