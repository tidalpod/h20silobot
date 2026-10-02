from datetime import date
from decimal import Decimal

import pytest

from database.loan_seed import (
    PROPERTY_LOAN_SEEDS,
    find_unambiguous_property_id,
    normalize_property_address,
)
from database.models import Property, PropertyLoan, Tenant
from webapp.routes.assets import (
    _compute_property_metrics,
    _effective_monthly_rent,
    _sync_property_loan_snapshot,
    _validated_loan_payload,
)


def valid_form(**overrides):
    values = {
        "loan_number_last4": "5114",
        "servicer": "Selene Finance",
        "original_amount": "76000.00",
        "current_balance": "75647.66",
        "interest_rate": "7.375",
        "loan_type": "Commercial",
        "term_years": "30",
        "start_date": "2026-03-01",
        "maturity_date": "2056-04-01",
        "monthly_payment": "848.28",
        "escrow_balance": "-25.50",
        "insurance_carrier": "",
        "insurance_payee": "",
        "insurance_policy_number": "GAC0443402",
        "insurance_expiration_date": "2027-04-30",
        "insurance_premium": "99.23",
        "insurance_premium_frequency": "monthly",
        "status": "active",
        "notes": "Verify placement.",
        "is_current": "1",
    }
    values.update(overrides)
    return values


def test_property_loan_masks_identifiers_and_formats_term():
    loan = PropertyLoan(
        loan_number_last4="5114",
        insurance_policy_number="381-5024929094-01",
        term_months=360,
    )

    assert loan.masked_loan_number == "•••• 5114"
    assert loan.masked_policy_number == "•••• 9401"
    assert loan.term_years == 30
    assert "5114" not in repr(loan)


def test_financing_form_validation_normalizes_expected_values():
    payload = _validated_loan_payload(valid_form())

    assert payload["loan_number_last4"] == "5114"
    assert payload["current_balance"] == Decimal("75647.66")
    assert payload["escrow_balance"] == Decimal("-25.50")
    assert payload["term_months"] == 360
    assert payload["start_date"] == date(2026, 3, 1)
    assert payload["maturity_date"] == date(2056, 4, 1)
    assert payload["is_current"] is True


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"loan_number_last4": "12345"}, "invalid_loan_number"),
        ({"current_balance": "-1"}, "invalid_current_balance"),
        ({"interest_rate": "101"}, "invalid_interest_rate"),
        ({"term_years": "zero"}, "invalid_term"),
        ({"start_date": "2056-01-01", "maturity_date": "2026-01-01"}, "invalid_date_range"),
    ],
)
def test_financing_form_rejects_invalid_values(overrides, error):
    with pytest.raises(ValueError, match=error):
        _validated_loan_payload(valid_form(**overrides))


def test_address_matching_is_exact_normalized_and_unambiguous():
    properties = [
        (11, "22532 Sharrow Ave."),
        (12, "22532 Sharrow Ave., Apt 2"),
    ]

    assert normalize_property_address("22532 Sharrow Ave.") == "22532 sharrow ave"
    assert find_unambiguous_property_id(properties, "22532 Sharrow Ave") == 11
    assert find_unambiguous_property_id(properties + [(13, "22532 Sharrow Ave")], "22532 Sharrow Ave") is None
    assert len(PROPERTY_LOAN_SEEDS) == 10


def test_current_related_loan_drives_assets_metrics_and_legacy_snapshot():
    prop = Property(
        address="11076 Lozier Ave",
        bsa_account_number="test-11076",
        appraised_value=Decimal("100000"),
        monthly_rent=Decimal("1500"),
        hoa_monthly=Decimal("0"),
    )
    loan = PropertyLoan(
        original_amount=Decimal("76000"),
        current_balance=Decimal("75000"),
        interest_rate=Decimal("7.375"),
        term_months=360,
        start_date=date(2026, 3, 1),
        monthly_payment=Decimal("848.28"),
        insurance_premium=Decimal("1200"),
        insurance_premium_frequency="annual",
        is_current=True,
        status="active",
    )
    prop.loans = [loan]

    metrics = _compute_property_metrics(prop)
    _sync_property_loan_snapshot(prop, loan)

    assert metrics["loan"] is loan
    assert metrics["equity"] == 25000
    assert metrics["cash_flow"] == pytest.approx(651.72)
    assert prop.loan_balance == Decimal("75000")
    assert prop.monthly_piti == Decimal("848.28")
    assert prop.monthly_insurance == Decimal("100.00")


def test_assets_use_active_tenant_rent_before_listed_property_rent():
    prop = Property(
        address="11100 Maxwell Ave",
        bsa_account_number="test-11100",
        monthly_rent=Decimal("900.00"),
    )
    prop.tenants = [
        Tenant(name="Former tenant", is_active=False, is_primary=True, current_rent=Decimal("800.00")),
        Tenant(name="Current tenant", is_active=True, is_primary=True, current_rent=Decimal("1250.00")),
    ]

    metrics = _compute_property_metrics(prop)

    assert _effective_monthly_rent(prop) == Decimal("1250.00")
    assert metrics["monthly_rent"] == Decimal("1250.00")


def test_assets_combine_section8_voucher_and_tenant_portion():
    prop = Property(address="11294 Essex Ave", bsa_account_number="test-11294")
    prop.tenants = [
        Tenant(
            name="Current tenant",
            is_active=True,
            is_primary=True,
            is_section8=True,
            voucher_amount=Decimal("925.00"),
            tenant_portion=Decimal("275.00"),
        )
    ]

    assert _effective_monthly_rent(prop) == Decimal("1200.00")
