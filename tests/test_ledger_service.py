import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from webapp.services import ledger_service


def make_charge(*, due_date: date, charge_type: str = "rent", amount: str = "632.00"):
    return SimpleNamespace(
        id=1,
        tenant_id=10,
        property_id=20,
        tenant_ref=SimpleNamespace(name="Cierra Trotter"),
        property_ref=SimpleNamespace(address="7251 Studebaker Ave."),
        charge_type=charge_type,
        description="Monthly Rent" if charge_type == "rent" else "Utility Charge",
        amount=Decimal(amount),
        due_date=due_date,
        service_start=None,
        service_end=None,
        is_void=False,
        is_recurring=charge_type == "rent",
        ledger_entries=[],
    )


class LedgerDueDateTests(unittest.TestCase):
    def test_future_rent_is_upcoming_and_excluded_from_due_totals(self):
        snapshot = ledger_service.charge_snapshot(
            make_charge(due_date=date(2026, 10, 1)),
            as_of=date(2026, 9, 25),
        )

        self.assertEqual(snapshot["status"], "upcoming")
        self.assertTrue(snapshot["is_future_rent"])
        self.assertEqual(snapshot["outstanding"], Decimal("632.00"))
        self.assertEqual(
            ledger_service.totals([snapshot]),
            {
                "charged": Decimal("0.00"),
                "paid_or_credited": Decimal("0.00"),
                "outstanding": Decimal("0.00"),
                "overdue": Decimal("0.00"),
            },
        )

    def test_rent_becomes_due_on_its_due_date(self):
        snapshot = ledger_service.charge_snapshot(
            make_charge(due_date=date(2026, 10, 1)),
            as_of=date(2026, 10, 1),
        )

        self.assertEqual(snapshot["status"], "open")
        self.assertFalse(snapshot["is_future_rent"])
        self.assertEqual(ledger_service.totals([snapshot])["outstanding"], Decimal("632.00"))

    def test_future_non_rent_charge_keeps_existing_open_behavior(self):
        snapshot = ledger_service.charge_snapshot(
            make_charge(due_date=date(2026, 10, 1), charge_type="utility"),
            as_of=date(2026, 9, 25),
        )

        self.assertEqual(snapshot["status"], "open")
        self.assertFalse(snapshot["is_future_rent"])


if __name__ == "__main__":
    unittest.main()
