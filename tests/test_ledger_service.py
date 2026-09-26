import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from webapp.services import ledger_service


def make_charge(
    *,
    due_date: date,
    charge_type: str = "rent",
    amount: str = "632.00",
    is_void: bool = False,
    ledger_entries=None,
):
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
        is_void=is_void,
        void_reason="Entered in error" if is_void else None,
        is_recurring=charge_type == "rent",
        recurrence_group="rent:10" if charge_type == "rent" else None,
        created_at=None,
        ledger_entries=ledger_entries or [],
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


class MonthlyChargeSummaryTests(unittest.TestCase):
    def test_recurring_instances_collapse_into_one_monthly_schedule(self):
        tenant = SimpleNamespace(
            id=10,
            is_section8=False,
            current_rent=Decimal("632.00"),
            tenant_portion=None,
            lease_start_date=date(2026, 1, 1),
            lease_end_date=date(2026, 12, 31),
        )
        charges = [
            ledger_service.charge_snapshot(
                make_charge(due_date=date(2026, 9, 1)),
                as_of=date(2026, 9, 25),
            ),
            ledger_service.charge_snapshot(
                make_charge(due_date=date(2026, 10, 1)),
                as_of=date(2026, 9, 25),
            ),
        ]

        summaries = ledger_service.monthly_charge_summaries(
            charges,
            tenant,
            as_of=date(2026, 9, 25),
        )

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["description"], "Rent")
        self.assertEqual(summaries[0]["due_label"], "1st")
        self.assertEqual(summaries[0]["charge_count"], 2)
        self.assertEqual(summaries[0]["end_date"], date(2026, 12, 31))

    def test_lease_rent_configuration_is_shown_without_recurring_instances(self):
        tenant = SimpleNamespace(
            id=10,
            is_section8=True,
            current_rent=Decimal("1500.00"),
            tenant_portion=Decimal("283.00"),
            lease_start_date=date(2026, 1, 1),
            lease_end_date=date(2026, 12, 31),
        )

        summaries = ledger_service.monthly_charge_summaries([], tenant)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["amount"], Decimal("283.00"))
        self.assertEqual(summaries[0]["source"], "Blue Deer rent schedule")

    def test_tenant_schedule_overrides_projected_rent_amount_and_due_day(self):
        tenant = SimpleNamespace(
            id=10,
            is_section8=False,
            current_rent=Decimal("1300.00"),
            tenant_portion=None,
            rent_schedule_active=True,
            rent_due_day=5,
            rent_schedule_start_date=date(2026, 9, 1),
            rent_schedule_end_date=None,
            lease_start_date=date(2026, 1, 1),
            lease_end_date=None,
        )
        charges = [
            ledger_service.charge_snapshot(
                make_charge(due_date=date(2026, 10, 1), amount="1250.00"),
                as_of=date(2026, 9, 25),
            )
        ]

        summary = ledger_service.monthly_charge_summaries(charges, tenant, as_of=date(2026, 9, 25))[0]

        self.assertEqual(summary["amount"], Decimal("1300.00"))
        self.assertEqual(summary["due_day"], 5)
        self.assertEqual(summary["due_label"], "5th")

    def test_inactive_rent_schedule_is_not_shown(self):
        tenant = SimpleNamespace(
            id=10,
            is_section8=False,
            current_rent=Decimal("1300.00"),
            tenant_portion=None,
            rent_schedule_active=False,
            lease_start_date=None,
            lease_end_date=None,
        )
        charges = [
            ledger_service.charge_snapshot(
                make_charge(due_date=date(2026, 10, 1)),
                as_of=date(2026, 9, 25),
            )
        ]

        self.assertEqual(ledger_service.monthly_charge_summaries(charges, tenant), [])

    def test_due_day_is_clamped_to_month_end(self):
        tenant = SimpleNamespace(rent_due_day=31)

        self.assertEqual(
            ledger_service.scheduled_rent_due_date(tenant, date(2027, 2, 1)),
            date(2027, 2, 28),
        )


class ChargeVoidTests(unittest.TestCase):
    def test_void_check_does_not_require_display_relationships(self):
        charge = SimpleNamespace(is_void=False, ledger_entries=[])

        self.assertTrue(ledger_service.can_void_charge(charge))

    def test_unapplied_charge_can_be_voided(self):
        charge = make_charge(due_date=date(2026, 9, 1))

        self.assertTrue(ledger_service.can_void_charge(charge))

    def test_charge_with_posted_payment_cannot_be_voided(self):
        payment = SimpleNamespace(
            amount=Decimal("100.00"),
            status="posted",
            entry_type="payment",
            created_at=None,
        )
        charge = make_charge(due_date=date(2026, 9, 1), ledger_entries=[payment])

        self.assertFalse(ledger_service.can_void_charge(charge))

    def test_void_charge_is_removed_from_totals(self):
        snapshot = ledger_service.charge_snapshot(
            make_charge(due_date=date(2026, 9, 1), is_void=True),
            as_of=date(2026, 9, 25),
        )

        self.assertEqual(snapshot["status"], "void")
        self.assertEqual(snapshot["void_reason"], "Entered in error")
        self.assertEqual(ledger_service.totals([snapshot])["outstanding"], Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
