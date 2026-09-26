import unittest
from datetime import date
from decimal import Decimal

from webapp.services import payment_service


class LateFeePolicyTests(unittest.TestCase):
    def test_custom_initial_and_daily_fee_with_day_limit(self):
        fee = payment_service.calculate_late_fee(
            date(2026, 9, 8),
            due_date=date(2026, 9, 1),
            initial_enabled=True,
            initial_amount=Decimal("25.00"),
            daily_enabled=True,
            daily_amount=Decimal("50.00"),
            grace_days=5,
            limit_type="days",
            max_days=2,
        )

        self.assertEqual(fee, Decimal("125.00"))

    def test_amount_limit_caps_combined_late_fees(self):
        fee = payment_service.calculate_late_fee(
            date(2026, 9, 10),
            due_date=date(2026, 9, 1),
            initial_enabled=True,
            initial_amount=Decimal("30.00"),
            daily_enabled=True,
            daily_amount=Decimal("20.00"),
            grace_days=5,
            limit_type="amount",
            max_amount=Decimal("75.00"),
        )

        self.assertEqual(fee, Decimal("75.00"))

    def test_fee_is_zero_during_grace_period(self):
        fee = payment_service.calculate_late_fee(
            date(2026, 9, 5),
            due_date=date(2026, 9, 1),
            daily_enabled=True,
            daily_amount=Decimal("50.00"),
            grace_days=5,
        )

        self.assertEqual(fee, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
