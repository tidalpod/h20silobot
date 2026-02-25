"""Michigan Residential Rental Agreement — boilerplate legal text.

All Section 2 (Special Provisions) and Section 3 (General Provisions)
text extracted from Michigan residential lease standards.
Referenced by the PDF generator.
"""

# Michigan-specific notices
MICHIGAN_TRUTH_IN_RENTING = (
    "This lease is subject to the Michigan Truth in Renting Act (MCL 554.631 et seq.). "
    "Any provision of this lease that violates the Truth in Renting Act is void and unenforceable."
)

MICHIGAN_SECURITY_DEPOSIT_LAW = (
    "Security Deposit: Under Michigan law (MCL 554.602-554.616), the Landlord may not demand "
    "a security deposit in excess of one and one-half (1.5) months' rent. The Landlord must, "
    "within 30 days after the Tenant moves in, notify the Tenant in writing of the name and "
    "address of the financial institution where the security deposit is held. Within 30 days "
    "after termination of occupancy, the Landlord shall return the security deposit to the "
    "Tenant, together with an itemized list of any damages claimed, or mail such to the "
    "Tenant's last known address."
)

MICHIGAN_LEAD_PAINT_DISCLOSURE = (
    "Lead-Based Paint Disclosure (for housing built before 1978): Landlord has disclosed "
    "the presence of known lead-based paint and/or lead-based paint hazards in the dwelling, "
    "or has indicated no knowledge of such hazards. Tenant has received the federally approved "
    "pamphlet on lead poisoning prevention. Tenant has had the opportunity to conduct an "
    "independent risk assessment or inspection for lead-based paint."
)

# Section 2: Special Provisions (configurable per-lease)
SECTION_2_TEMPLATES = {
    "lease_term_fixed": (
        "LEASE TERM: This is a fixed-term lease beginning on {start_date} and ending on "
        "{end_date}. Upon expiration, this lease shall {expiration_action}."
    ),
    "lease_term_mtm": (
        "LEASE TERM: This is a month-to-month rental agreement beginning on {start_date}. "
        "Either party may terminate this agreement by providing at least 30 days' written "
        "notice before the end of any monthly period."
    ),
    "expiration_continue_mtm": (
        "automatically convert to a month-to-month tenancy under the same terms and conditions, "
        "until terminated by either party with at least 30 days' written notice"
    ),
    "expiration_terminate": (
        "terminate, and Tenant shall vacate the premises on or before the expiration date "
        "unless a new lease agreement is executed by both parties"
    ),
    "rent_payment": (
        "RENT: Tenant agrees to pay ${monthly_rent} per month as rent for the premises. "
        "Rent is due on the {rent_due_day}{ordinal} day of each month. Rent shall be paid "
        "via the following accepted methods: {payment_methods}."
    ),
    "late_fee": (
        "LATE FEE: If rent is not received by the {grace_days}{ordinal_grace} day of the month, "
        "a late fee of ${late_fee_daily} per day will be assessed, up to a maximum of "
        "{late_fee_max_days} days (${late_fee_max} maximum late fee per month)."
    ),
    "security_deposit": (
        "SECURITY DEPOSIT: Tenant has deposited ${security_deposit} as a security deposit. "
        "This deposit shall be held at {deposit_bank_name}, located at {deposit_bank_address}, "
        "and shall be returned in accordance with Michigan law (MCL 554.602-554.616)."
    ),
    "pet_policy_allowed": (
        "PETS: Pets are permitted on the premises subject to the following conditions: "
        "An additional pet deposit of ${pet_deposit} and monthly pet rent of ${pet_rent} "
        "shall apply. Approved pets: {pet_list}. Tenant is responsible for any damage "
        "caused by pets and for cleaning up after pets on the premises."
    ),
    "pet_policy_not_allowed": (
        "PETS: No pets are allowed on the premises without prior written consent from the "
        "Landlord. Violation of this provision may result in immediate lease termination."
    ),
    "smoking_not_permitted": (
        "SMOKING: Smoking (including e-cigarettes and vaping) is NOT permitted anywhere "
        "on the premises, including inside the dwelling, on balconies, patios, or in any "
        "common areas."
    ),
    "smoking_designated_areas": (
        "SMOKING: Smoking is only permitted in designated outdoor areas as specified by "
        "the Landlord. Smoking inside the dwelling is strictly prohibited."
    ),
    "parking": (
        "PARKING: {parking_rules}"
    ),
    "renters_insurance": (
        "RENTERS INSURANCE: Tenant is required to maintain a renter's insurance policy "
        "with a minimum coverage of $100,000 in liability coverage for the duration of "
        "this lease. Proof of insurance must be provided to Landlord within 30 days of "
        "lease execution and upon each policy renewal."
    ),
    "utilities": (
        "UTILITIES: The following utility responsibilities are assigned as follows:\n{utility_table}"
    ),
    "maintenance": (
        "MAINTENANCE REQUESTS: Tenant shall submit maintenance requests through the "
        "following channels: {maintenance_methods}. Emergency maintenance issues should "
        "be reported immediately by phone."
    ),
    "keys": (
        "KEYS: Tenant has been provided with the following keys/access devices:\n{keys_table}\n"
        "All keys must be returned upon termination of this lease. Unreturned keys may "
        "result in a lock-change fee deducted from the security deposit."
    ),
    "early_termination": (
        "EARLY TERMINATION: Tenant may terminate this lease early by providing at least "
        "60 days' written notice and paying an early termination fee equal to two (2) "
        "months' rent. The security deposit may be applied toward this fee."
    ),
    "move_in_fees": (
        "MOVE-IN FEES: The following non-refundable fees are due at move-in:\n{fees_table}"
    ),
    "prorated_rent": (
        "PRORATED RENT: A prorated rent payment of ${prorated_rent} is due for the "
        "partial month of {prorated_month}."
    ),
}

# Section 3: General Provisions (standard Michigan boilerplate)
SECTION_3_GENERAL_PROVISIONS = [
    {
        "title": "USE OF PREMISES",
        "text": (
            "The premises shall be used exclusively as a private residential dwelling for "
            "the Tenant(s) and approved occupants listed in this agreement. Tenant shall not "
            "use the premises for any unlawful purpose or in any manner that creates a nuisance "
            "or disturbs the peace and quiet of other residents or neighbors."
        ),
    },
    {
        "title": "CONDITION OF PREMISES",
        "text": (
            "Tenant acknowledges that the premises have been inspected and are in satisfactory "
            "condition at the time of move-in, except as noted in the Move-In Condition Report. "
            "Tenant agrees to maintain the premises in a clean and sanitary condition and to "
            "return the premises in the same condition as received, less reasonable wear and tear."
        ),
    },
    {
        "title": "MAINTENANCE AND REPAIRS",
        "text": (
            "Landlord shall maintain the premises in a habitable condition in compliance with "
            "Michigan housing codes and shall make necessary repairs within a reasonable time "
            "after receiving written notice from Tenant. Tenant shall promptly notify Landlord "
            "of any needed repairs or unsafe conditions. Tenant shall not make alterations or "
            "improvements without prior written consent from Landlord."
        ),
    },
    {
        "title": "RIGHT OF ENTRY",
        "text": (
            "Landlord or Landlord's agents may enter the premises for inspection, maintenance, "
            "repairs, or to show the premises to prospective tenants or buyers. Except in cases "
            "of emergency, Landlord shall provide at least 24 hours' notice before entry and "
            "shall enter only during reasonable hours."
        ),
    },
    {
        "title": "ASSIGNMENT AND SUBLETTING",
        "text": (
            "Tenant shall not assign this lease or sublet the premises, in whole or in part, "
            "without the prior written consent of the Landlord. Any unauthorized assignment or "
            "subletting shall be a material breach of this lease."
        ),
    },
    {
        "title": "DEFAULT AND REMEDIES",
        "text": (
            "If Tenant fails to pay rent when due, or otherwise violates any term of this lease, "
            "Landlord may pursue all remedies available under Michigan law, including but not "
            "limited to serving a written demand for possession or payment (7-day notice for "
            "non-payment of rent, 30-day notice for other lease violations). If Tenant does not "
            "comply within the notice period, Landlord may initiate eviction proceedings in "
            "accordance with MCL 600.5701 et seq."
        ),
    },
    {
        "title": "HOLDOVER TENANCY",
        "text": (
            "If Tenant remains in possession of the premises after the expiration or termination "
            "of this lease without Landlord's written consent, Tenant shall be deemed a holdover "
            "tenant. Landlord may charge holdover rent at 150% of the monthly rent amount and "
            "may initiate eviction proceedings at any time."
        ),
    },
    {
        "title": "ABANDONMENT",
        "text": (
            "If Tenant abandons the premises during the lease term, Landlord may retake possession "
            "and re-rent the premises. Tenant shall remain liable for rent through the end of the "
            "lease term or until a new tenant is found, whichever occurs first."
        ),
    },
    {
        "title": "LIABILITY AND INDEMNIFICATION",
        "text": (
            "Landlord shall not be liable for any injury, loss, or damage to Tenant's person or "
            "property caused by other tenants, third parties, or events beyond Landlord's control. "
            "Tenant agrees to indemnify and hold Landlord harmless from any claims arising from "
            "Tenant's use of the premises or the actions of Tenant's guests."
        ),
    },
    {
        "title": "NOTICES",
        "text": (
            "All notices required or permitted under this lease shall be in writing and shall be "
            "deemed delivered when personally delivered, sent by certified mail (return receipt "
            "requested) to the parties at the addresses listed in this lease, or sent via email "
            "to the email addresses provided."
        ),
    },
    {
        "title": "GOVERNING LAW",
        "text": (
            "This lease shall be governed by and construed in accordance with the laws of the "
            "State of Michigan. Any disputes arising under this lease shall be resolved in the "
            "appropriate court of the county in which the premises are located."
        ),
    },
    {
        "title": "SEVERABILITY",
        "text": (
            "If any provision of this lease is found to be invalid or unenforceable, the remaining "
            "provisions shall continue in full force and effect."
        ),
    },
    {
        "title": "ENTIRE AGREEMENT",
        "text": (
            "This lease constitutes the entire agreement between Landlord and Tenant regarding the "
            "rental of the premises. No oral agreements or representations shall be binding unless "
            "incorporated into this lease in writing and signed by both parties."
        ),
    },
]


def ordinal(n: int) -> str:
    """Return ordinal suffix for a number: 1st, 2nd, 3rd, etc."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return suffix
