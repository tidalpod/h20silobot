import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from scripts.cleanup_duplicate_imported_rent import next_month, parse_month, posted_applied_amount


class DuplicateRentCleanupTests(unittest.TestCase):
    def test_parse_month_and_next_month_cross_year_boundary(self):
        month = parse_month("2026-12")

        self.assertEqual(month, date(2026, 12, 1))
        self.assertEqual(next_month(month), date(2027, 1, 1))

    def test_posted_applied_amount_ignores_pending_and_accounts_for_reversals(self):
        charge = SimpleNamespace(
            ledger_entries=[
                SimpleNamespace(status="posted", entry_type="payment", amount=Decimal("500.00")),
                SimpleNamespace(status="posted", entry_type="credit", amount=Decimal("25.00")),
                SimpleNamespace(status="posted", entry_type="reversal", amount=Decimal("100.00")),
                SimpleNamespace(status="pending", entry_type="payment", amount=Decimal("300.00")),
            ]
        )

        self.assertEqual(posted_applied_amount(charge), Decimal("425.00"))


if __name__ == "__main__":
    unittest.main()
