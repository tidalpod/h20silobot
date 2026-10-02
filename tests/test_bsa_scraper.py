import unittest
from decimal import Decimal
from types import SimpleNamespace

from scraper.bsa_scraper import BSAScraper
from webapp.routes.api import _apply_scraped_bill_amount


class BSABalanceParsingTests(unittest.TestCase):
    def test_explicit_zero_balance_is_a_successful_parse(self):
        html = """
        <html><body>
            <div>Account: 123456</div>
            <div>Balance</div>
            <div>$0.00</div>
            <div>PREVIOUS BILL</div>
            <div>$712.07</div>
        </body></html>
        """

        bill_data = BSAScraper._parse_detail_html(html, "11268 Dodge Ave")

        self.assertIsNotNone(bill_data)
        self.assertEqual(bill_data.amount_due, Decimal("0.00"))
        self.assertTrue(bill_data.amount_parsed)

    def test_missing_balance_label_is_not_treated_as_paid(self):
        html = "<html><body><div>Payment history</div><div>$712.07</div></body></html>"

        bill_data = BSAScraper._parse_detail_html(html, "11268 Dodge Ave")

        self.assertIsNotNone(bill_data)
        self.assertEqual(bill_data.amount_due, Decimal("0"))
        self.assertFalse(bill_data.amount_parsed)

    def test_confident_zero_clears_existing_balance(self):
        existing_bill = SimpleNamespace(
            amount_due=Decimal("712.07"),
            previous_balance=None,
            current_charges=None,
            late_fees=None,
            payments_received=None,
        )
        scraped = SimpleNamespace(
            amount_parsed=True,
            amount_due=Decimal("0.00"),
            previous_balance=Decimal("0.00"),
            current_charges=Decimal("0.00"),
            late_fees=Decimal("0.00"),
            payments_received=Decimal("712.07"),
        )

        applied = _apply_scraped_bill_amount(existing_bill, scraped)

        self.assertTrue(applied)
        self.assertEqual(existing_bill.amount_due, Decimal("0.00"))

    def test_unparsed_zero_preserves_existing_balance(self):
        existing_bill = SimpleNamespace(
            amount_due=Decimal("712.07"),
            previous_balance=None,
            current_charges=None,
            late_fees=None,
            payments_received=None,
        )
        scraped = SimpleNamespace(
            amount_parsed=False,
            amount_due=Decimal("0.00"),
            previous_balance=None,
            current_charges=None,
            late_fees=None,
            payments_received=None,
        )

        applied = _apply_scraped_bill_amount(existing_bill, scraped)

        self.assertFalse(applied)
        self.assertEqual(existing_bill.amount_due, Decimal("712.07"))


if __name__ == "__main__":
    unittest.main()
