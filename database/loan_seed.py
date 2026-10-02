"""Idempotent seed data for the initial property financing records."""

import logging
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text


logger = logging.getLogger(__name__)


PROPERTY_LOAN_SEEDS = (
    {
        "address": "11076 Lozier Ave",
        "loan_number_last4": "5114",
        "servicer": "Selene Finance",
        "original_amount": "76000.00",
        "current_balance": "75647.66",
        "interest_rate": "7.375",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-03-01",
        "maturity_date": "2056-04-01",
        "monthly_payment": "848.28",
        "escrow_balance": "2321.63",
        "insurance_carrier": None,
        "insurance_payee": None,
        "insurance_policy_number": "GAC0443402",
        "insurance_expiration_date": "2027-04-30",
        "insurance_premium": "99.23",
        "insurance_premium_frequency": "monthly",
        "status": "active",
        "notes": "Verify whether borrower- or lender-placed.",
    },
    {
        "address": "8259 Timken Ave",
        "loan_number_last4": "3913",
        "servicer": "Selene Finance",
        "original_amount": "89304.00",
        "current_balance": "88960.04",
        "interest_rate": "7.375",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-03-01",
        "maturity_date": "2056-04-01",
        "monthly_payment": "1031.68",
        "escrow_balance": "2484.57",
        "insurance_carrier": None,
        "insurance_payee": None,
        "insurance_policy_number": "GAC0440313",
        "insurance_expiration_date": "2027-05-17",
        "insurance_premium": "150.00",
        "insurance_premium_frequency": "monthly",
        "status": "active",
        "notes": "Verify whether borrower- or lender-placed.",
    },
    {
        "address": "8412 Timken Ave",
        "loan_number_last4": "6505",
        "servicer": None,
        "original_amount": "92144.00",
        "current_balance": None,
        "interest_rate": None,
        "loan_type": None,
        "term_months": None,
        "start_date": None,
        "maturity_date": None,
        "monthly_payment": None,
        "escrow_balance": None,
        "insurance_carrier": None,
        "insurance_payee": None,
        "insurance_policy_number": None,
        "insurance_expiration_date": None,
        "insurance_premium": None,
        "insurance_premium_frequency": None,
        "status": "transferred",
        "notes": "Transferred—current servicer/details required.",
    },
    {
        "address": "29080 Michigan St",
        "loan_number_last4": "4364",
        "servicer": "Selene Finance",
        "original_amount": "117000.00",
        "current_balance": "116612.26",
        "interest_rate": "6.990",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-05-01",
        "maturity_date": "2056-06-01",
        "monthly_payment": "1024.51",
        "escrow_balance": "-790.36",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5024929094-01",
        "insurance_expiration_date": "2027-04-15",
        "insurance_premium": "1376.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "22532 Sharrow Ave",
        "loan_number_last4": "7554",
        "servicer": "Selene Finance",
        "original_amount": "105600.00",
        "current_balance": "105054.68",
        "interest_rate": "7.625",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-02-01",
        "maturity_date": "2056-03-01",
        "monthly_payment": "1161.23",
        "escrow_balance": "3901.82",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5023415200-01",
        "insurance_expiration_date": "2026-12-14",
        "insurance_premium": "1096.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "6826 Republic Ave",
        "loan_number_last4": "6713",
        "servicer": "Selene Finance",
        "original_amount": "148000.00",
        "current_balance": "147177.04",
        "interest_rate": "7.250",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-02-01",
        "maturity_date": "2056-03-01",
        "monthly_payment": "1236.79",
        "escrow_balance": "-161.28",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5022827851-01",
        "insurance_expiration_date": "2027-01-15",
        "insurance_premium": "1172.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "7251 Studebaker Ave",
        "loan_number_last4": "6785",
        "servicer": "Selene Finance",
        "original_amount": "96000.00",
        "current_balance": "95431.64",
        "interest_rate": "7.625",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-01-01",
        "maturity_date": "2056-02-01",
        "monthly_payment": "968.38",
        "escrow_balance": "1862.90",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5022728940-01",
        "insurance_expiration_date": "2026-12-14",
        "insurance_premium": "584.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "14584 Stephens Rd",
        "loan_number_last4": "4227",
        "servicer": "Selene Finance",
        "original_amount": "116000.00",
        "current_balance": "115448.82",
        "interest_rate": "7.250",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-02-01",
        "maturity_date": "2056-03-01",
        "monthly_payment": "953.88",
        "escrow_balance": "77.26",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5023415211-01",
        "insurance_expiration_date": "2026-12-14",
        "insurance_premium": "593.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "24591 Valley Ave",
        "loan_number_last4": "3611",
        "servicer": "Selene Finance",
        "original_amount": "96000.00",
        "current_balance": "95504.27",
        "interest_rate": "7.625",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-02-01",
        "maturity_date": "2056-03-01",
        "monthly_payment": "867.66",
        "escrow_balance": "-596.88",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5022828144-01",
        "insurance_expiration_date": "2027-01-15",
        "insurance_premium": "946.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
    {
        "address": "22025 Linwood Ave",
        "loan_number_last4": "4911",
        "servicer": "Selene Finance",
        "original_amount": "120000.00",
        "current_balance": "119380.34",
        "interest_rate": "7.625",
        "loan_type": "Commercial",
        "term_months": 360,
        "start_date": "2026-02-01",
        "maturity_date": "2056-03-01",
        "monthly_payment": "1409.16",
        "escrow_balance": "2405.88",
        "insurance_carrier": "Foremost Insurance",
        "insurance_payee": None,
        "insurance_policy_number": "381-5023779794-01",
        "insurance_expiration_date": "2027-01-15",
        "insurance_premium": "1339.00",
        "insurance_premium_frequency": "annual",
        "status": "active",
        "notes": None,
    },
)


def normalize_property_address(address: str) -> str:
    """Normalize an address for conservative, exact seed matching."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (address or "").lower()).split())


def find_unambiguous_property_id(properties, target_address):
    """Return a property id only when one normalized address matches."""
    target = normalize_property_address(target_address)
    matches = [row[0] for row in properties if normalize_property_address(row[1]) == target]
    return matches[0] if len(matches) == 1 else None


def _monthly_insurance(seed):
    premium = seed.get("insurance_premium")
    if premium is None:
        return None
    amount = Decimal(premium)
    if seed.get("insurance_premium_frequency") == "annual":
        amount = amount / Decimal("12")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def seed_property_loans(engine):
    """Insert the supplied loans only for unique, exact address matches."""
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT id, address FROM properties"))).all()

        for seed in PROPERTY_LOAN_SEEDS:
            property_id = find_unambiguous_property_id(rows, seed["address"])
            if property_id is None:
                match_count = sum(
                    normalize_property_address(row[1]) == normalize_property_address(seed["address"])
                    for row in rows
                )
                logger.warning(
                    "Skipped financing seed for %s: expected one address match, found %s",
                    seed["address"],
                    match_count,
                )
                continue

            values = {**seed, "property_id": property_id}
            for field in ("start_date", "maturity_date", "insurance_expiration_date"):
                if values.get(field):
                    values[field] = date.fromisoformat(values[field])
            result = await conn.execute(text("""
                INSERT INTO property_loans (
                    property_id, loan_number_last4, servicer, original_amount,
                    current_balance, interest_rate, loan_type, term_months,
                    start_date, maturity_date, monthly_payment, escrow_balance,
                    insurance_carrier, insurance_payee, insurance_policy_number,
                    insurance_expiration_date, insurance_premium,
                    insurance_premium_frequency, status, notes, is_current,
                    created_at, updated_at
                ) VALUES (
                    :property_id, :loan_number_last4, :servicer, :original_amount,
                    :current_balance, :interest_rate, :loan_type, :term_months,
                    :start_date, :maturity_date, :monthly_payment, :escrow_balance,
                    :insurance_carrier, :insurance_payee, :insurance_policy_number,
                    :insurance_expiration_date, :insurance_premium,
                    :insurance_premium_frequency, :status, :notes, true,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (property_id, loan_number_last4) DO NOTHING
            """), values)

            if result.rowcount:
                await conn.execute(text("""
                    UPDATE properties SET
                        loan_amount = :original_amount,
                        loan_balance = :current_balance,
                        interest_rate = :interest_rate,
                        loan_term_years = :term_years,
                        loan_start_date = :start_date,
                        monthly_insurance = :monthly_insurance,
                        monthly_piti = :monthly_payment,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :property_id
                """), {
                    "property_id": property_id,
                    "original_amount": seed.get("original_amount"),
                    "current_balance": seed.get("current_balance"),
                    "interest_rate": seed.get("interest_rate"),
                    "term_years": (seed.get("term_months") or 0) // 12 or None,
                    "start_date": values.get("start_date"),
                    "monthly_insurance": _monthly_insurance(seed),
                    "monthly_payment": seed.get("monthly_payment"),
                })
                logger.info("Seeded financing details for %s", seed["address"])
