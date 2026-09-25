"""Parse and conservatively match TurboTenant CSV exports.

The import workflow is intentionally split into two phases.  This module only
builds a read-only reconciliation report; a later apply step can consume the
reviewed matches without guessing at ambiguous tenants or properties.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


MONEY = Decimal("0.01")


@dataclass(frozen=True)
class PropertyRecord:
    id: int
    address: str
    city: str = ""
    state: str = ""
    zip_code: str = ""


@dataclass(frozen=True)
class TenantRecord:
    id: int
    property_id: int
    name: str
    is_active: bool = True


@dataclass(frozen=True)
class ChargeRow:
    row_number: int
    due_date: date
    category: str
    description: str
    lease_title: str
    status: str
    amount: Decimal
    amount_due: Decimal
    source_key: str

    @property
    def paid_amount(self) -> Decimal:
        return max(self.amount - self.amount_due, Decimal("0.00"))


@dataclass(frozen=True)
class DepositRow:
    row_number: int
    payment_id: str
    amount: Decimal
    deposited_on: date
    tenant_name: str
    payment_method: str
    lease_address: str
    note: str
    paid_on: date
    bank_account: str
    lease_title: str


@dataclass(frozen=True)
class RentRollRow:
    row_number: int
    property_address: str
    unit: str
    tenant_names: str
    lease_start: date | None
    lease_end: date | None
    security_deposit: Decimal
    rent_amount: Decimal
    total_unpaid: Decimal
    total_past_due: Decimal


@dataclass(frozen=True)
class Match:
    property_id: int | None
    tenant_id: int | None
    status: str
    reason: str


@dataclass(frozen=True)
class MatchSummary:
    total: int
    matched: int
    ambiguous: int
    unmatched: int
    matched_amount: str
    total_amount: str


def parse_money(value: str | None) -> Decimal:
    cleaned = (value or "").strip().replace("$", "").replace(",", "")
    if not cleaned or cleaned == "-":
        return Decimal("0.00")
    try:
        return Decimal(cleaned).quantize(MONEY)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid currency value: {value!r}") from exc


def parse_date(value: str | None, *, required: bool = True) -> date | None:
    cleaned = (value or "").strip()
    if not cleaned or cleaned == "-":
        if required:
            raise ValueError("Missing required date")
        return None
    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError as exc:
        if not required:
            return None
        raise ValueError(f"Invalid date value: {value!r}") from exc


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def normalize_name(value: str) -> str:
    value = _ascii(value).lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = value.split()
    if tokens[-1:] and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        tokens.pop()
    return " ".join(tokens)


_ADDRESS_WORDS = {
    "avenue": "ave",
    "av": "ave",
    "street": "st",
    "road": "rd",
    "drive": "dr",
    "boulevard": "blvd",
    "court": "ct",
    "place": "pl",
    "lane": "ln",
    "parkway": "pkwy",
    "highway": "hwy",
    "terrace": "ter",
    "circle": "cir",
    "apartment": "apt",
    "unit": "apt",
    "suite": "apt",
}


def normalize_address(value: str) -> str:
    value = _ascii(value).lower().strip()
    value = re.sub(r",\s*#?\s*([a-z0-9-]+)\s*$", r" apt \1", value)
    value = value.replace("#", " apt ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = [_ADDRESS_WORDS.get(token, token) for token in value.split()]
    collapsed: list[str] = []
    for token in tokens:
        if token == "apt" and collapsed[-1:] == ["apt"]:
            continue
        collapsed.append(token)
    tokens = collapsed
    if len(tokens) >= 4 and tokens[-4] == "apt" and tokens[-2] == "apt" and tokens[-3] == tokens[-1]:
        tokens = tokens[:-2]
    if tokens and tokens[-1] == "apt":
        tokens.pop()
    return " ".join(tokens)


def _charge_identity(row: dict[str, str]) -> str:
    fields = (
        row.get("Due Date", "").strip(),
        row.get("Category", "").strip().upper(),
        row.get("Description", "").strip(),
        row.get("Lease Title", "").strip(),
        str(parse_money(row.get("Amount"))),
    )
    return "|".join(fields)


def read_charges(path: Path) -> list[ChargeRow]:
    rows: list[ChargeRow] = []
    occurrences: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Due Date", "Category", "Description", "Lease Title", "Status", "Amount", "Amount Due"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected charges columns in {path}")
        for row_number, row in enumerate(reader, start=2):
            identity = _charge_identity(row)
            occurrences[identity] += 1
            digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
            rows.append(
                ChargeRow(
                    row_number=row_number,
                    due_date=parse_date(row["Due Date"]),
                    category=row["Category"].strip().upper(),
                    description=row["Description"].strip(),
                    lease_title=row["Lease Title"].strip(),
                    status=row["Status"].strip().upper(),
                    amount=parse_money(row["Amount"]),
                    amount_due=parse_money(row["Amount Due"]),
                    source_key=f"turbotenant:charge:{digest}:{occurrences[identity]}",
                )
            )
    return rows


def read_deposits(path: Path) -> list[DepositRow]:
    rows: list[DepositRow] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "Payment ID", "Deposit Amount", "Date Deposited", "Tenant",
            "Payment Method", "Lease Address", "Payment note",
            "Payment Date Paid", "Bank Account", "Lease",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected deposits columns in {path}")
        for row_number, row in enumerate(reader, start=2):
            payment_id = row["Payment ID"].strip()
            if not payment_id:
                raise ValueError(f"Missing Payment ID at deposits row {row_number}")
            if payment_id in seen:
                raise ValueError(f"Duplicate Payment ID {payment_id} in deposits export")
            seen.add(payment_id)
            rows.append(
                DepositRow(
                    row_number=row_number,
                    payment_id=payment_id,
                    amount=parse_money(row["Deposit Amount"]),
                    deposited_on=parse_date(row["Date Deposited"]),
                    tenant_name=row["Tenant"].strip(),
                    payment_method=row["Payment Method"].strip().upper(),
                    lease_address=row["Lease Address"].strip(),
                    note=row["Payment note"].strip(),
                    paid_on=parse_date(row["Payment Date Paid"]),
                    bank_account=row["Bank Account"].strip(),
                    lease_title=row["Lease"].strip(),
                )
            )
    return rows


def read_rent_roll(path: Path) -> list[RentRollRow]:
    rows: list[RentRollRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline()
        if not first_line.lower().startswith("pulled on"):
            handle.seek(0)
        reader = csv.DictReader(handle)
        required = {
            "Property", "Unit", "Tenants", "Lease Start", "Lease End",
            "Security Deposit", "Rent Amount", "Total Unpaid", "Total Past Due",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected rent-roll columns in {path}")
        for row_number, row in enumerate(reader, start=3):
            rows.append(
                RentRollRow(
                    row_number=row_number,
                    property_address=row["Property"].strip(),
                    unit=row["Unit"].strip(),
                    tenant_names=row["Tenants"].strip(),
                    lease_start=parse_date(row["Lease Start"], required=False),
                    lease_end=parse_date(row["Lease End"], required=False),
                    security_deposit=parse_money(row["Security Deposit"]),
                    rent_amount=parse_money(row["Rent Amount"]),
                    total_unpaid=parse_money(row["Total Unpaid"]),
                    total_past_due=parse_money(row["Total Past Due"]),
                )
            )
    return rows


def _property_aliases(prop: PropertyRecord) -> set[str]:
    address = normalize_address(prop.address)
    aliases = {address}
    location = " ".join(part for part in (prop.city, prop.state, prop.zip_code) if part)
    if location:
        aliases.add(normalize_address(f"{prop.address} {location}"))
    return {alias for alias in aliases if alias}


def _street_signature(value: str) -> tuple[str, ...]:
    """Return house number + street name, ignoring a disputed suffix or unit."""
    tokens = normalize_address(value).split()
    if not tokens or not tokens[0].isdigit():
        return ()
    suffixes = {"ave", "st", "rd", "dr", "blvd", "ct", "pl", "ln", "pkwy", "hwy", "ter", "cir", "apt"}
    core = [tokens[0]]
    for token in tokens[1:]:
        if token in suffixes:
            break
        core.append(token)
    return tuple(core) if len(core) > 1 else ()


def _property_candidates(value: str, properties: Sequence[PropertyRecord]) -> list[PropertyRecord]:
    key = normalize_address(value)
    if not key:
        return []
    exact = [prop for prop in properties if key in _property_aliases(prop)]
    if exact:
        return exact

    # A TurboTenant export sometimes appends city/state to the street address.
    prefix = []
    for prop in properties:
        for alias in _property_aliases(prop):
            if key.startswith(f"{alias} "):
                remainder = key[len(alias):].strip().split()
                if remainder[:1] == ["apt"] and len(remainder) > 1:
                    continue
                prefix.append(prop)
                break
            if alias.startswith(f"{key} "):
                remainder = alias[len(key):].strip().split()
                if remainder[:1] == ["apt"] and len(remainder) > 1:
                    continue
                prefix.append(prop)
                break
    if prefix:
        return prefix

    signature = _street_signature(value)
    if not signature:
        return []
    return [prop for prop in properties if _street_signature(prop.address) == signature]


def _match_person_at_property(
    *,
    tenant_name: str,
    property_candidates: Sequence[PropertyRecord],
    tenants_by_property: dict[int, list[TenantRecord]],
) -> Match:
    if not property_candidates:
        return Match(None, None, "unmatched", "property_not_found")
    if len(property_candidates) > 1:
        return Match(None, None, "ambiguous", "multiple_properties")

    prop = property_candidates[0]
    name_key = normalize_name(tenant_name)
    people = [
        tenant for tenant in tenants_by_property.get(prop.id, [])
        if normalize_name(tenant.name) == name_key
    ]
    if len(people) == 1:
        return Match(prop.id, people[0].id, "matched", "address_and_tenant")
    if len(people) > 1:
        return Match(prop.id, None, "ambiguous", "duplicate_tenant_at_property")
    active_people = [tenant for tenant in tenants_by_property.get(prop.id, []) if tenant.is_active]
    if len(active_people) == 1:
        return Match(prop.id, active_people[0].id, "matched", "address_single_active_tenant")
    if len(active_people) > 1:
        return Match(prop.id, None, "ambiguous", "payer_not_found_multiple_active_tenants")
    return Match(prop.id, None, "unmatched", "tenant_not_found_at_property")


def match_deposits(
    deposits: Sequence[DepositRow],
    properties: Sequence[PropertyRecord],
    tenants: Sequence[TenantRecord],
) -> list[Match]:
    tenants_by_property: dict[int, list[TenantRecord]] = defaultdict(list)
    for tenant in tenants:
        tenants_by_property[tenant.property_id].append(tenant)
    return [
        _match_person_at_property(
            tenant_name=row.tenant_name,
            property_candidates=_property_candidates(row.lease_address, properties),
            tenants_by_property=tenants_by_property,
        )
        for row in deposits
    ]


def _lease_match_map(
    deposits: Sequence[DepositRow],
    matches: Sequence[Match],
) -> dict[str, set[tuple[int, int]]]:
    result: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row, match in zip(deposits, matches):
        if match.status == "matched" and match.property_id and match.tenant_id:
            result[normalize_name(row.lease_title)].add((match.property_id, match.tenant_id))
    return result


def _charge_title_property_candidates(
    title: str,
    properties: Sequence[PropertyRecord],
) -> list[PropertyRecord]:
    candidates = _property_candidates(title, properties)
    if candidates:
        return candidates
    first_segment = re.split(r"\s+-\s+", title, maxsplit=1)[0]
    return _property_candidates(first_segment, properties)


def match_charges(
    charges: Sequence[ChargeRow],
    deposits: Sequence[DepositRow],
    deposit_matches: Sequence[Match],
    properties: Sequence[PropertyRecord],
    tenants: Sequence[TenantRecord],
) -> list[Match]:
    lease_map = _lease_match_map(deposits, deposit_matches)
    tenants_by_property: dict[int, list[TenantRecord]] = defaultdict(list)
    tenants_by_name: dict[str, list[TenantRecord]] = defaultdict(list)
    for tenant in tenants:
        tenants_by_property[tenant.property_id].append(tenant)
        tenants_by_name[normalize_name(tenant.name)].append(tenant)

    matches: list[Match] = []
    for row in charges:
        lease_key = normalize_name(row.lease_title)
        linked = lease_map.get(lease_key, set())
        if len(linked) == 1:
            property_id, tenant_id = next(iter(linked))
            matches.append(Match(property_id, tenant_id, "matched", "deposit_lease_title"))
            continue
        if len(linked) > 1:
            matches.append(Match(None, None, "ambiguous", "lease_title_multiple_tenants"))
            continue

        exact_people = tenants_by_name.get(lease_key, [])
        if len(exact_people) == 1:
            tenant = exact_people[0]
            matches.append(Match(tenant.property_id, tenant.id, "matched", "lease_title_tenant"))
            continue
        if len(exact_people) > 1:
            matches.append(Match(None, None, "ambiguous", "lease_title_duplicate_tenant"))
            continue

        props = _charge_title_property_candidates(row.lease_title, properties)
        if len(props) != 1:
            status = "ambiguous" if len(props) > 1 else "unmatched"
            reason = "multiple_properties" if len(props) > 1 else "charge_property_not_found"
            matches.append(Match(None, None, status, reason))
            continue

        prop = props[0]
        people = tenants_by_property.get(prop.id, [])
        named = [tenant for tenant in people if normalize_name(tenant.name) in lease_key]
        if len(named) == 1:
            matches.append(Match(prop.id, named[0].id, "matched", "title_address_and_tenant"))
        elif len(named) > 1:
            matches.append(Match(prop.id, None, "ambiguous", "multiple_title_tenants"))
        elif len(people) == 1:
            matches.append(Match(prop.id, people[0].id, "matched", "address_single_tenant"))
        elif not people:
            matches.append(Match(prop.id, None, "unmatched", "property_has_no_tenant"))
        else:
            matches.append(Match(prop.id, None, "ambiguous", "property_has_multiple_tenants"))
    return matches


def _summarize(rows: Iterable, matches: Sequence[Match], amount_attr: str) -> MatchSummary:
    rows = list(rows)
    total_amount = sum((getattr(row, amount_attr) for row in rows), Decimal("0.00"))
    matched_amount = sum(
        (getattr(row, amount_attr) for row, match in zip(rows, matches) if match.status == "matched"),
        Decimal("0.00"),
    )
    counts = Counter(match.status for match in matches)
    return MatchSummary(
        total=len(rows),
        matched=counts["matched"],
        ambiguous=counts["ambiguous"],
        unmatched=counts["unmatched"],
        matched_amount=f"{matched_amount:.2f}",
        total_amount=f"{total_amount:.2f}",
    )


def build_report(
    *,
    charges: Sequence[ChargeRow],
    deposits: Sequence[DepositRow],
    rent_roll: Sequence[RentRollRow],
    properties: Sequence[PropertyRecord],
    tenants: Sequence[TenantRecord],
    existing_charge_keys: set[str] | None = None,
    existing_payment_ids: set[str] | None = None,
) -> dict:
    deposit_matches = match_deposits(deposits, properties, tenants)
    charge_matches = match_charges(charges, deposits, deposit_matches, properties, tenants)
    existing_charge_keys = existing_charge_keys or set()
    existing_payment_ids = existing_payment_ids or set()

    duplicate_charge_identities = Counter(
        (row.due_date.isoformat(), row.category, row.description, row.lease_title, str(row.amount))
        for row in charges
    )

    def issues(rows: Sequence, matches: Sequence[Match], label: str) -> list[dict]:
        output = []
        for row, match in zip(rows, matches):
            if match.status == "matched":
                continue
            item = {
                "row": row.row_number,
                "status": match.status,
                "reason": match.reason,
            }
            if label == "deposit":
                item.update({
                    "payment_id": row.payment_id,
                    "tenant": row.tenant_name,
                    "address": row.lease_address,
                    "amount": f"{row.amount:.2f}",
                })
            else:
                item.update({
                    "lease_title": row.lease_title,
                    "due_date": row.due_date.isoformat(),
                    "amount": f"{row.amount:.2f}",
                })
            output.append(item)
        return output

    rent_roll_property_matches = [
        _property_candidates(
            " ".join(part for part in (row.property_address, row.unit) if part),
            properties,
        )
        for row in rent_roll
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "dry_run",
        "source": {
            "charges": len(charges),
            "deposits": len(deposits),
            "rent_roll_rows": len(rent_roll),
            "charge_total": f"{sum((row.amount for row in charges), Decimal('0.00')):.2f}",
            "charge_amount_due": f"{sum((row.amount_due for row in charges), Decimal('0.00')):.2f}",
            "charge_paid_amount": f"{sum((row.paid_amount for row in charges), Decimal('0.00')):.2f}",
            "deposit_total": f"{sum((row.amount for row in deposits), Decimal('0.00')):.2f}",
            "deposit_methods": dict(sorted(Counter(row.payment_method for row in deposits).items())),
            "charge_statuses": dict(sorted(Counter(row.status for row in charges).items())),
            "charge_categories": dict(sorted(Counter(row.category for row in charges).items())),
        },
        "database": {
            "properties": len(properties),
            "tenants": len(tenants),
            "active_tenants": sum(1 for tenant in tenants if tenant.is_active),
        },
        "matches": {
            "deposits": asdict(_summarize(deposits, deposit_matches, "amount")),
            "charges": asdict(_summarize(charges, charge_matches, "amount")),
            "rent_roll_properties": {
                "total": len(rent_roll_property_matches),
                "matched": sum(len(items) == 1 for items in rent_roll_property_matches),
                "ambiguous": sum(len(items) > 1 for items in rent_roll_property_matches),
                "unmatched": sum(not items for items in rent_roll_property_matches),
            },
        },
        "already_imported": {
            "charges": sum(row.source_key in existing_charge_keys for row in charges),
            "payments": sum(row.payment_id in existing_payment_ids for row in deposits),
        },
        "source_duplicate_charge_groups": [
            {
                "due_date": key[0],
                "category": key[1],
                "description": key[2],
                "lease_title": key[3],
                "amount": key[4],
                "count": count,
            }
            for key, count in duplicate_charge_identities.items()
            if count > 1
        ],
        "issues": {
            "deposits": issues(deposits, deposit_matches, "deposit"),
            "charges": issues(charges, charge_matches, "charge"),
        },
    }
