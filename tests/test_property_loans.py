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
    _asset_sort_value,
    _build_asset_rows,
    _compute_property_metrics,
    _effective_monthly_rent,
    _effective_asset_value,
    _filter_asset_rows,
    _sync_property_loan_snapshot,
    _validated_asset_loan_payload,
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


def test_assets_quick_edit_validates_loan_fields_without_touching_insurance():
    payload = _validated_asset_loan_payload({
        "loan_number_last4": "4492",
        "loan_servicer": "Shellpoint Mortgage Servicing",
        "loan_original_amount": "96000.00",
        "loan_current_balance": "94458.18",
        "loan_interest_rate": "7.875",
        "loan_type": "Conventional",
        "loan_term_years": "30",
        "loan_start_date": "2025-01-01",
        "loan_maturity_date": "2055-02-01",
        "loan_monthly_payment": "2250.88",
        "loan_escrow_balance": "3214.78",
        "loan_status": "active",
        "loan_notes": "Verified in servicing portal.",
    })

    assert payload["current_balance"] == Decimal("94458.18")
    assert payload["monthly_payment"] == Decimal("2250.88")
    assert payload["term_months"] == 360
    assert payload["is_current"] is True
    assert "insurance_policy_number" not in payload


def test_assets_quick_edit_rejects_negative_piti():
    with pytest.raises(ValueError, match="invalid_monthly_payment"):
        _validated_asset_loan_payload({"loan_monthly_payment": "-1"})


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


def test_assets_infer_value_and_equity_from_twenty_percent_down():
    prop = Property(
        address="Implied Value Property",
        bsa_account_number="implied-value",
    )
    prop.tenants = []
    prop.loans = [
        PropertyLoan(
            original_amount=Decimal("80000.00"),
            current_balance=Decimal("70000.00"),
            is_current=True,
        )
    ]

    metrics = _compute_property_metrics(prop)

    assert metrics["appraised_value"] == Decimal("100000.00")
    assert metrics["valuation_source"] == "implied_80_ltv"
    assert metrics["equity"] == 30000
    assert metrics["ltv"] == 70.0


def test_assets_use_original_balance_when_current_principal_is_missing():
    prop = Property(
        address="Origination Balance Property",
        bsa_account_number="origination-balance",
    )
    prop.tenants = []
    prop.loans = [
        PropertyLoan(
            original_amount=Decimal("80000.00"),
            current_balance=None,
            is_current=True,
        )
    ]

    metrics = _compute_property_metrics(prop)

    assert metrics["appraised_value"] == Decimal("100000.00")
    assert metrics["debt_value"] == Decimal("80000.00")
    assert metrics["debt_source"] == "original_balance_fallback"
    assert metrics["equity"] == 20000
    assert metrics["ltv"] == 80.0


def test_recorded_appraisal_wins_over_implied_value():
    value, source = _effective_asset_value(
        Decimal("135000.00"),
        Decimal("95000.00"),
        Decimal("15000.00"),
        Decimal("80000.00"),
        Decimal("70000.00"),
    )

    assert value == Decimal("135000.00")
    assert source == "appraisal"


def test_twenty_percent_down_estimate_wins_over_purchase_fallback_for_financed_asset():
    value, source = _effective_asset_value(
        None,
        Decimal("95000.00"),
        None,
        Decimal("80000.00"),
        Decimal("70000.00"),
    )

    assert value == Decimal("100000.00")
    assert source == "implied_80_ltv"


def test_current_balance_reconstructs_twenty_percent_down_value_when_original_is_missing():
    value, source = _effective_asset_value(
        None,
        Decimal("95000.00"),
        None,
        None,
        Decimal("80000.00"),
    )

    assert value == Decimal("100000.00")
    assert source == "implied_current_balance_80_ltv"


def test_rehab_cost_is_added_to_purchase_price_fallback():
    value, source = _effective_asset_value(
        None,
        Decimal("95000.00"),
        Decimal("15000.00"),
        None,
        None,
    )

    assert value == Decimal("110000.00")
    assert source == "purchase_plus_rehab"


def test_debt_free_asset_uses_purchase_price_as_value_and_equity():
    prop = Property(
        address="Debt Free Value Property",
        bsa_account_number="debt-free-value",
        purchase_price=Decimal("90000.00"),
    )
    prop.tenants = []
    prop.loans = []

    metrics = _compute_property_metrics(prop)

    assert metrics["appraised_value"] == Decimal("90000.00")
    assert metrics["valuation_source"] == "purchase_price"
    assert metrics["equity"] == 90000


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


def test_assets_use_gross_rent_as_cash_flow_when_there_is_no_mortgage():
    prop = Property(
        address="Debt Free Property",
        bsa_account_number="debt-free",
        monthly_rent=Decimal("1650.00"),
        hoa_monthly=Decimal("125.00"),
    )
    prop.tenants = []
    prop.loans = []

    metrics = _compute_property_metrics(prop)

    assert metrics["monthly_payment"] is None
    assert metrics["cash_flow"] == Decimal("1650.00")


def test_assets_sort_values_use_current_loan_and_effective_rent():
    prop = Property(
        address="11100 Maxwell Ave",
        bsa_account_number="sort-11100",
        monthly_rent=Decimal("1400.00"),
        loan_balance=Decimal("999999.00"),
    )
    loan = PropertyLoan(
        servicer="Select Portfolio Servicing",
        current_balance=Decimal("102159.12"),
        monthly_payment=Decimal("1106.91"),
        interest_rate=Decimal("7.750"),
        is_current=True,
    )
    prop.loans = [loan]
    row = _compute_property_metrics(prop)

    assert _asset_sort_value(row, "property") == "11100 maxwell ave"
    assert _asset_sort_value(row, "servicer") == "select portfolio servicing"
    assert _asset_sort_value(row, "loan_balance") == Decimal("102159.12")
    assert _asset_sort_value(row, "rent") == Decimal("1400.00")


@pytest.mark.parametrize(
    "base_address,display_address",
    [
        ("11035 Republic Ave", "11035 Republic Ave"),
        ("3616 Wasmund Ave", "3616 Wasmund Ave"),
    ],
)
def test_assets_consolidate_configured_duplex_units(base_address, display_address):
    unit_one = Property(
        id=101,
        address=f"{base_address}, Apt. 1",
        city="Warren",
        state="MI",
        zip_code="48089",
        bsa_account_number=f"{base_address}-1",
        entity="Casa Sicura LLC",
        purchase_price=Decimal("100000.00"),
        appraised_value=Decimal("150000.00"),
    )
    unit_one.tenants = [
        Tenant(name="Unit one", is_active=True, is_primary=True, current_rent=Decimal("950.00"))
    ]
    unit_one.loans = [
        PropertyLoan(
            servicer="Test Servicer",
            current_balance=Decimal("80000.00"),
            interest_rate=Decimal("7.500"),
            monthly_payment=Decimal("900.00"),
            is_current=True,
        )
    ]
    unit_two = Property(
        id=102,
        address=f"{base_address}, Apt. 2",
        city="Warren",
        state="MI",
        zip_code="48089",
        bsa_account_number=f"{base_address}-2",
        entity="Casa Sicura LLC",
    )
    unit_two.tenants = [
        Tenant(name="Unit two", is_active=True, is_primary=True, current_rent=Decimal("1000.00"))
    ]
    unit_two.loans = []

    rows = _build_asset_rows([unit_two, unit_one])

    assert len(rows) == 1
    row = rows[0]
    assert row["property"] is unit_one
    assert row["display_address"] == display_address
    assert row["unit_count"] == 2
    assert row["monthly_rent"] == Decimal("1950.00")
    assert row["loan_balance"] == Decimal("80000.00")
    assert row["monthly_payment"] == Decimal("900.00")
    assert row["cash_flow"] == pytest.approx(1050.00)


def test_assets_do_not_merge_other_republic_properties():
    duplex_one = Property(id=201, address="11035 Republic Ave Apt. 1", bsa_account_number="duplex-1")
    duplex_two = Property(id=202, address="11035 Republic Ave Apt. 2", bsa_account_number="duplex-2")
    other_republic = Property(id=203, address="6750 Republic Ave.", bsa_account_number="other-republic")
    for prop in (duplex_one, duplex_two, other_republic):
        prop.tenants = []
        prop.loans = []

    rows = _build_asset_rows([duplex_one, duplex_two, other_republic])

    assert len(rows) == 2
    assert sorted(row["unit_count"] for row in rows) == [1, 2]


def test_assets_filter_rows_by_entity_without_changing_all_portfolios_view():
    casa = Property(
        id=301,
        address="Casa Property",
        bsa_account_number="casa-property",
        entity="Casa Sicura LLC",
    )
    silo = Property(
        id=302,
        address="Silo Property",
        bsa_account_number="silo-property",
        entity="Silo Capital LLC",
    )
    for prop in (casa, silo):
        prop.tenants = []
        prop.loans = []
    rows = _build_asset_rows([casa, silo])

    assert _filter_asset_rows(rows, []) == rows
    selected = _filter_asset_rows(rows, ["Silo Capital LLC"])
    assert len(selected) == 1
    assert selected[0]["property"] is silo


def test_assets_filter_rows_by_multiple_entities():
    properties = [
        Property(id=311, address="Casa Property", bsa_account_number="casa", entity="Casa Sicura LLC"),
        Property(id=312, address="Silo Property", bsa_account_number="silo", entity="Silo Capital LLC"),
        Property(id=313, address="Partner Property", bsa_account_number="partner", entity="Silo Partners LLC"),
    ]
    for prop in properties:
        prop.tenants = []
        prop.loans = []

    rows = _build_asset_rows(properties)
    selected = _filter_asset_rows(rows, ["Casa Sicura LLC", "Silo Partners LLC"])

    assert {row["property"].entity for row in selected} == {"Casa Sicura LLC", "Silo Partners LLC"}
