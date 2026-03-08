"""Michigan Residential Rental Agreement — boilerplate legal text.

All Section 2 (Special Provisions) and Section 3 (General Provisions)
text modeled after TurboTenant Michigan lease format.
Referenced by the PDF generator.
"""

# Michigan-specific notices
MICHIGAN_TRUTH_IN_RENTING = (
    "NOTICE: Michigan law establishes rights and obligations for parties to rental agreements. "
    "This agreement is required to comply with the Truth in Renting Act. If you have a question "
    "about the interpretation or legality of a provision of this agreement, you may want to seek "
    "assistance from a lawyer or other qualified person."
)

MICHIGAN_SECURITY_DEPOSIT_LAW = (
    "Under Michigan law (MCL 554.602-554.616), the Landlord may not demand a security deposit "
    "in excess of one and one-half (1.5) times the monthly rent. The security deposit shall be "
    "held in a regulated financial institution. Within 30 days after termination of occupancy, "
    "the Landlord shall return the security deposit to the Tenant, together with an itemized "
    "list of any damages claimed, or mail such to the Tenant's last known address."
)

MICHIGAN_LEAD_PAINT_DISCLOSURE = (
    "Housing built before 1978 may contain lead-based paint. Lead from paint, paint chips, and "
    "dust can pose health hazards if not managed properly. Lead exposure is especially harmful "
    "to young children and pregnant women. Before renting pre-1978 housing, landlords must "
    "disclose the presence of known lead-based paint and/or lead-based paint hazards in the "
    "dwelling. Lessees must also receive a federally approved pamphlet on lead poisoning prevention."
)


# ─── Section 2: Special Provisions ──────────────────────────────────────────────
# These are rendered as named subsections (2.1, 2.2, etc.) with titles and body text.
# Each entry has a 'title' and a 'text' template string with optional format vars.

SECTION_2_PROVISIONS = [
    {
        "key": "late_rent",
        "title": "LATE RENT",
        "text": (
            "Rent is due in full on the Due Date. If Rent is not received on or before the "
            "{rent_due_day}{ordinal} day of the month, a daily late fee of ${late_fee_daily} will be "
            "applied starting {late_fee_grace_days} days after the rent due date, total number of "
            "daily late fees applied will not exceed {late_fee_max_days} daily fees. All late fees "
            "shall be deemed additional rent for the month, and shall be paid and collected as such. "
            "Late fees will be assessed from the Due Date until the entire balance of unpaid Rent, "
            "accrued late fees, and any other charges are paid in full."
        ),
    },
    {
        "key": "nsf_fees",
        "title": "BAD CHECKS / NSF FEES",
        "text": (
            "If a personal check or ACH draft is returned by Tenant's bank for any reason, a charge "
            "of twenty dollars ($20.00) shall be added to Rent for the month, and Tenant shall not be "
            "current with Rent as long as said charge is not paid. If Rent payment is late, or if "
            "Tenant's electronic or personal check is returned due to insufficient funds, uncollected "
            "or unpaid, Landlord may require that all subsequent payments be made by cashier's check "
            "or money order."
        ),
    },
    {
        "key": "notice_to_tenant",
        "title": "NOTICE TO TENANT",
        "text": (
            "Notice to Tenant may be given in accordance with applicable law to the address of the "
            "Premises listed above, or to such other place as designated by Tenant in writing as the "
            "place for receipt of notices, or, in the absence of such designation, to Tenant's last "
            "known address."
        ),
    },
    {
        "key": "security_deposit_provisions",
        "title": "SECURITY DEPOSIT PROVISIONS",
        "text": (
            "Upon the due execution of this Agreement, Tenant shall deposit with Landlord a security "
            "deposit referenced in Section 1.8. The security deposit shall be held in a FDIC insured "
            "institution as shown below. The security deposit shall not exceed a sum equal to one and "
            "a half (1.5) times the monthly rent. Such deposit shall be returned to Tenant, and less "
            "any set-off for unpaid rent, unpaid late fees, unpaid utilities, damages, or any other "
            "money owing Landlord, along with an itemized statement showing any lawful charges or "
            "deductions, within thirty (30) days of lease termination, in accordance with the terms "
            "of this section and applicable laws.\n\n"
            "Financial institution holding the deposit: {deposit_bank_name}, {deposit_bank_address}\n\n"
            "You must notify your landlord in writing within 4 days after you move of a forwarding "
            "address where you can be reached and where you will receive mail; otherwise your landlord "
            "shall be relieved of sending you an itemized list of damages and the penalties adherent "
            "to that failure."
        ),
    },
    {
        "key": "use_of_premises",
        "title": "USE OF PREMISES / OCCUPANCY LIMITS",
        "text": (
            "The Premises shall be occupied as a residence exclusively by the Tenant and the Additional "
            "Occupant(s). To the extent allowed by applicable law, Tenant shall comply with any and all "
            "laws, ordinances, rules, and orders of any and all governmental or quasi-governmental "
            "authorities affecting the upkeep, use, occupancy, and preservation of the Premises. To the "
            "extent allowed by applicable law, Tenant shall indemnify Landlord against, and reimburse "
            "Landlord for, any fines, charges, damages, costs, or fees, including reasonable attorney "
            "fees, incurred or paid by Landlord as a result of any noncompliance of the occupancy "
            "limits by Tenant. No person who is not a Tenant or Additional Occupant(s) may occupy the "
            "Premises, except that Tenant may allow one guest to stay with Tenant for a maximum period "
            "of fifteen (15) days every six (6) months, provided that such guest at all times maintains "
            "a separate residence. Any guest who stays in excess of this amount shall be considered an "
            "unauthorized occupant."
        ),
    },
    {
        "key": "condition_of_premises",
        "title": "CONDITION OF PREMISES",
        "text": (
            "Tenant acknowledges that prior to occupying the Premises, Tenant has examined the Premises "
            "and is satisfied with the condition, subject to those items specifically stated on the "
            "Property Condition Report (or like-titled document). By accepting possession of the "
            "Premises, Tenant acknowledges and agrees that no repairs or cleaning are required or "
            "requested. Tenant agrees and accepts the Premises \"As Is\" condition, and that no warranty "
            "or guarantees are expressed or implied by Landlord. In the event that not all Tenants can "
            "be present at the time of move-in, the acceptance of the condition by one or more than one "
            "Tenant(s) shall be sufficient as to establishing the condition at the start of the Term."
        ),
    },
    {
        "key": "maintenance_communication",
        "title": "MAINTENANCE AND COMMUNICATION METHODS",
        "text": (
            "Tenant acknowledges that the Premises (including all fixtures, furniture, furnishings, and "
            "appliances) are in good and habitable condition, working order, and repair as of the lease "
            "start date. Any exceptions must be noted on the Property Condition Report.\n\n"
            "Tenant shall:\n"
            "- Keep the Premises in good order and condition, and immediately pay for any repairs "
            "caused by Tenant's negligence or misuse, that of their guests, or Additional Occupant(s).\n"
            "- Keep the Premises clean, sanitary, and in good order and condition.\n"
            "- Maintain and test all smoke and carbon monoxide alarms/detectors as required by law, "
            "regulation, or this Agreement (at least once every six months is advised).\n"
            "- Not commit any waste upon the Premises or any act that may disturb the quiet enjoyment "
            "of neighbors.\n"
            "- Not paint, wallpaper, redecorate, renovate, or otherwise alter the Premises without the "
            "Owner's express, prior, written consent.\n\n"
            "Failure to report a problem immediately may result in Tenant being held liable for damages "
            "caused by the delay in addressing the issue.\n\n"
            "Tenant must immediately notify Landlord in writing upon first discovering any need for "
            "repairs, maintenance, or signs of serious building problems. All non-emergency repair "
            "requests must be submitted in writing to the Landlord using the designated communication "
            "methods. Tenant is expected to perform necessary troubleshooting of common issues like "
            "resetting electrical or GFI breakers before submitting a request. The request must include "
            "a detailed explanation of the issue, steps taken to resolve it, and at least two photos.\n\n"
            "Once a vendor is assigned, Tenant must promptly communicate directly with the vendor to "
            "schedule the repair. Tenant is responsible for any cancellation or no-show fees charged "
            "by the vendor due to Tenant's action or inaction. Tenant must notify Landlord of the "
            "results of any repair within 24 hours of the work being performed.\n\n"
            "Landlord will pay for repairs of conditions that materially affect the health or safety of "
            "an ordinary resident as required by state law.\n\n"
            "Communication Methods Allowed: {maintenance_methods}"
        ),
    },
    {
        "key": "notification_building_problems",
        "title": "NOTIFICATION OF BUILDING PROBLEMS OR REPAIRS NEEDED",
        "text": (
            "Tenant shall keep the Premises in good order and condition, and immediately pay for any "
            "repairs caused by Tenant's negligence or misuse, that of their guests or Additional "
            "Occupant(s). Tenant agrees to notify Landlord immediately upon first discovering any "
            "repairs or maintenance needed, or signs of serious building problems, including but not "
            "limited to: a crack in the foundation, a tilting porch, a crack in the plaster or stucco, "
            "moisture in the ceiling, buckling sheetrock or siding, a leaky roof, a spongy floor, any "
            "leaking or running water, appliance malfunction, and/or electrical shorting or sparks. "
            "Failure to report a problem may create a situation where the Tenant will be liable for "
            "damages due to the problem not being addressed sooner. Notwithstanding anything to the "
            "contrary in this Agreement, Landlord will pay for repairs of conditions that materially "
            "affect the health or safety of an ordinary resident (i.e., dangerous or hazardous conditions)."
        ),
    },
    {
        "key": "entry_access",
        "title": "ENTRY/ACCESS TO PREMISES BY LANDLORD",
        "text": (
            "Landlord shall have the right at all reasonable times during the term of this Agreement to "
            "enter the Premises for the purpose of inspecting and exhibiting the Premises and all "
            "buildings and improvements thereon. In non-emergency situations, Landlord will make a good "
            "faith effort to notify Tenant at least 24 hours prior to entry, and having made such good "
            "faith effort shall enter as necessary. In an emergency situation, or if a repair is "
            "requested by Tenant, Landlord is permitted to enter immediately without prior notice. "
            "Tenant understands that Landlord may show the Premises to prospective tenants, purchasers, "
            "or lenders at any time with proper notice. Landlord shall further have the right to display "
            "\"for sale\", \"for rent\", or \"vacancy\" signs in or about the Premises."
        ),
    },
    {
        "key": "absences",
        "title": "ABSENCES",
        "text": (
            "Tenant is required to notify Landlord in writing of any anticipated absence from the "
            "Premises in excess of seven (7) days, and shall make arrangements for the Premises to be "
            "routinely checked on during absence. Such written notice must be provided no later than "
            "the first day of any such absence. Landlord may enter the Premises at any time for any "
            "reasonable purpose during Tenant's absence."
        ),
    },
    {
        "key": "fair_housing",
        "title": "FAIR HOUSING",
        "text": (
            "The federal Fair Housing Act prohibits discrimination based on race, color, national "
            "origin, religion, sex (including gender identity and sexual orientation), familial status "
            "and disability. All Parties to this Agreement shall act according to said law or any other "
            "classification protected by federal, state, or local law applicable in the jurisdiction "
            "where the Premises is located."
        ),
    },
    {
        "key": "damage_to_premises",
        "title": "DAMAGE TO PREMISES",
        "text": (
            "In the event the Premises are destroyed or rendered wholly untenable by fire, storm, or "
            "other casualty not caused by the negligence of Tenant, this Agreement shall terminate from "
            "such time except for the purpose of enforcing rights that may have then accrued hereunder. "
            "The Rent provided for herein shall then be accounted for by and between Landlord and Tenant "
            "up to the time of such injury or destruction of the Premises, Tenant paying Rent up to "
            "such date and Landlord refunding Rent collected beyond such date. Should a portion of the "
            "Premises thereby be rendered untenable, the Landlord shall have the option of either "
            "repairing such injured or damaged portion or terminating this Agreement. In the event that "
            "Landlord exercises its right to repair such untenable portion, the Rent shall abate in the "
            "proportion that the injured parts bears to the whole Premises, and such part so injured "
            "shall be restored by Landlord as speedily as practicable, after which the full Rent shall "
            "recommence and the Agreement continue according to the terms."
        ),
    },
    {
        "key": "security_devices",
        "title": "SECURITY DEVICES AND EXTERIOR DOOR LOCKS",
        "text": (
            "Tenant shall not add or change any: lock, locking device, bolt or latch on the Premises "
            "without the express written consent of Landlord. All notices or requests by Tenant for: "
            "rekeying, changing, installing, repairing, or replacing security devices must be in writing. "
            "Installation of additional security devices or additional rekeying or replacement of "
            "security devices desired by Tenant will be paid by Tenant, in advance, and may only be "
            "installed by Landlord or Landlord's contractors after receiving a written request from Tenant."
        ),
    },
    {
        "key": "utilities_services",
        "title": "UTILITIES AND OTHER SERVICES",
        "text": (
            "Landlord is not responsible for any discomfort, inconvenience, or damage of any kind "
            "caused by the interruption or failure of any Utilities or Other Services. Landlord is not "
            "responsible for outages or lapses caused by outside providers or for Tenant's use thereof. "
            "Any billing methods described herein may be changed by Landlord by providing Tenant with "
            "thirty (30) days prior written notice, or by the minimum number of days as required by "
            "state and/or local law(s) (whichever is shorter), and Tenant acknowledges that in certain "
            "situations it is necessary to make a change to the billing method."
        ),
    },
    {
        "key": "smoke_co_detectors",
        "title": "SMOKE / CARBON MONOXIDE DETECTORS",
        "text": (
            "Smoke and carbon monoxide (if applicable) detectors (hereinafter referred to collectively "
            "as \"Detectors\") have been installed at the Premises. Upon commencement of this Agreement, "
            "Landlord and Tenant have verified that the Detectors in the Premises are in good working "
            "order. Tenant agrees to keep the Detectors operational at all times and take no measures "
            "to render them non-operational or to diminish their effectiveness. Tenant agrees to perform "
            "the manufacturer's recommended test on Detectors and to report the failure of any such "
            "test, or any other apparent malfunction of the Detectors to Landlord immediately upon "
            "discovery in writing. Tenant acknowledges that the Detectors may be battery operated and "
            "agrees to replace the batteries, at Tenant's expense, promptly, as needed, for the "
            "duration of their stay at the Premises."
        ),
    },
    {
        "key": "truth_in_renting",
        "title": "STATE OF MICHIGAN TRUTH IN RENTING NOTICE",
        "text": (
            "NOTICE: Michigan law establishes rights and obligations for parties to rental agreements. "
            "This agreement is required to comply with the Truth in Renting Act. If you have a question "
            "about the interpretation or legality of a provision of this agreement, you may want to "
            "seek assistance from a lawyer or other qualified person."
        ),
    },
]


# ─── Section 3: General Provisions ──────────────────────────────────────────────
SECTION_3_GENERAL_PROVISIONS = [
    {
        "title": "ASSIGNMENT AND SUBLETTING",
        "text": (
            "Tenant shall not assign this Agreement, or sublet or grant any license to use the "
            "Premises or any part thereof without the prior written consent of Landlord. Consent by "
            "Landlord to one such assignment, subletting, or license shall not be deemed to be consent "
            "to any subsequent assignment, subletting, or license. An assignment, subletting, or "
            "license without the prior written consent of Landlord or an assignment or subletting by "
            "operation of law shall be absolutely null and void and shall, at Landlord's option, "
            "terminate this Agreement."
        ),
    },
    {
        "title": "ALTERATIONS AND IMPROVEMENTS",
        "text": (
            "Tenant shall make no alterations to the buildings on the Premises or construct any "
            "building, or make any other improvements (including painting of any kind) on the Premises "
            "without the prior written consent of Landlord. Any and all alterations, changes, and/or "
            "improvements built, constructed, or placed on the Premises by Tenant shall, unless "
            "otherwise provided by written agreement between Landlord and Tenant, be and become the "
            "property of Landlord, and remain on the Premises at the expiration of this Agreement. "
            "Notwithstanding the foregoing, the Landlord may require the Tenant at Tenant's sole cost "
            "and expense, to remove such improvements at the expiration of this Agreement and return "
            "the Premises to its original condition at the commencement of this Agreement."
        ),
    },
    {
        "title": "HAZARDOUS MATERIALS",
        "text": (
            "Tenant shall not keep on the Premises any item of a dangerous, flammable, or explosive "
            "character that might unreasonably increase the danger of fire or explosion on the "
            "Premises, or that might be considered hazardous or extra hazardous by any responsible "
            "insurance company."
        ),
    },
    {
        "title": "MOLD AND MILDEW DISCLOSURE",
        "text": (
            "Prior to commencement of this Agreement, Landlord and Tenant have visually inspected the "
            "Premises and observed no visible mold or mildew, obvious water leaks, or presence of "
            "excess moisture conducive to mold growth, unless expressly noted on the Condition of "
            "Premises (or like-titled document). Landlord is not representing that a significant mold "
            "problem exists or does not exist on the Premises, as such a determination may only be "
            "made by a qualified inspector. Tenant agrees that it is their responsibility to hire a "
            "qualified inspector to determine if a significant mold problem exists or does not exist "
            "on the property. Tenant further acknowledges and agrees that Landlord, who has provided "
            "this section, is not liable for any action based on the presence of or propensity for "
            "mold in the property. Instead, Tenant must promptly notify Landlord in writing of a "
            "condition that poses a hazard to property, health, or safety. Landlord will take "
            "appropriate action to comply with applicable law, subject to any exceptions for natural "
            "disasters and other casualty losses."
        ),
    },
    {
        "title": "LEAD-BASED PAINT DISCLOSURE AND WARNING STATEMENT",
        "text": (
            "Housing built prior to 1978 may contain lead-based paint. Lead from paint, paint chips, "
            "and dust can pose health hazards if not managed properly. Lead exposures are especially "
            "harmful to children and pregnant women. Before renting pre-1978 housing, Landlord must "
            "disclose any known presence of lead-based paint, lead-based paint hazards, and/or records "
            "or reports of lead-based paint in the dwelling. Tenant must also receive a federally "
            "approved pamphlet on lead poisoning prevention."
        ),
    },
    {
        "title": "MODIFICATION",
        "text": (
            "This Agreement shall not be modified, changed, altered, or amended in any way except "
            "through a written amendment signed by all of the Parties hereto."
        ),
    },
    {
        "title": "CREDIT REPORTING DISCLOSURE",
        "text": (
            "Tenant is hereby notified that a negative credit report statement may be submitted to a "
            "credit reporting agency if Tenant fails to fulfill the terms of this Agreement."
        ),
    },
    {
        "title": "MILITARY PERSONNEL CLAUSE / FAMILY VIOLENCE / SEX OFFENSES OR STALKING",
        "text": (
            "The federal Servicemembers Civil Relief Act allows a Tenant to terminate this Agreement, "
            "under certain circumstances, if they enlist, are moved, or are drafted or commissioned in "
            "the U.S. Armed Forces. Tenants may have additional rights, under state or local laws, to "
            "terminate this Agreement early in certain situations involving family violence, certain "
            "sexual offenses, or stalking. All Parties to this Agreement shall act according to any "
            "such federal, state, or local law applicable in the jurisdiction where the Premises is "
            "located. A tenant who has a reasonable apprehension of present danger to him or her or "
            "his or her child from domestic violence, sexual assault, or stalking may have special "
            "statutory rights to seek a release of rental obligation under MCL 554.601b."
        ),
    },
    {
        "title": "MATERIALITY OF APPLICATION TO RENT",
        "text": (
            "All representations made by Tenant on the application (or like-titled document) (defined "
            "as \"Application to Rent\") are material to the grant of this Agreement, and the Agreement "
            "is granted only on the condition of the truthfulness and accuracy of said representations. "
            "If a failure to disclose or lack of truthfulness is discovered on said Application to "
            "Rent, Landlord may deem Tenant to be in breach of this Agreement and shall be good cause "
            "for termination."
        ),
    },
    {
        "title": "SUBORDINATION OF LEASE",
        "text": (
            "This Agreement and Tenant's interest hereunder are, and shall be, subordinate, junior, "
            "and inferior to any and all mortgages, liens, or encumbrances now or hereafter placed on "
            "the Premises by Landlord, all advances made under any such mortgages, liens, or "
            "encumbrances (including, but not limited to, future advances), the interest payable on "
            "such mortgages, liens, or encumbrances and any and all renewals, extensions, or "
            "modifications of such mortgages, liens, or encumbrances."
        ),
    },
    {
        "key": "choice_of_law",
        "title": "CHOICE OF LAW",
        "text": (
            "THIS AGREEMENT SHALL BE GOVERNED BY AND CONSTRUED IN ACCORDANCE WITH THE LAWS OF THE "
            "STATE OF MICHIGAN. All Parties to this Agreement, including Third Party Guarantors, if "
            "any, expressly consent to the venue of the courts of the county in which the Premises is "
            "located."
        ),
    },
    {
        "title": "SURRENDER OF PREMISES",
        "text": (
            "Upon the expiration of the Term hereof, Tenant shall surrender the Premises in as good "
            "a state and condition as they were at the commencement of this Agreement, reasonable use "
            "and wear and tear thereof excepted. For purposes of this Agreement, Tenant has "
            "\"surrendered\" the Premises when: (i) the move-out date has passed and no one is living "
            "in the Premises in Landlord's reasonable judgment; or (ii) the keys and access devices "
            "listed in this Agreement have been turned in to Landlord, whichever happens first. "
            "Surrender, abandonment, or judicial eviction ends Tenant's right of possession for all "
            "purposes, and gives Landlord the immediate right to clean up, make repairs in, and relet "
            "the Premises; determine any Security Deposit deductions; and remove property left in the "
            "Premises."
        ),
    },
    {
        "title": "QUIET ENJOYMENT",
        "text": (
            "Tenant, upon payment of all of the sums referred to herein as being payable by Tenant, "
            "and Tenant's performance of all Tenant's agreements contained herein, and Tenant's "
            "observance of all rules and regulations, shall and may peacefully and quietly have, hold, "
            "and enjoy said Premises for the term hereof."
        ),
    },
    {
        "title": "COMPLIANCE WITH LAWS",
        "text": (
            "Tenant shall not violate any law or ordinance (federal, state, or local), or commit or "
            "permit any waste or nuisance in or about the Premises, or in any way annoy any other "
            "person residing within three hundred (300) feet of the Premises. Such actions shall be a "
            "material and irreparable violation of the Agreement and good cause for termination of "
            "Agreement."
        ),
    },
    {
        "title": "ABANDONMENT",
        "text": (
            "If at any time during the Term Tenant abandons the Premises, Landlord may, at Landlord's "
            "option, obtain possession of the Premises in the manner provided by law, and without "
            "becoming liable to Tenant for damages or for any payment of any kind whatever. Landlord "
            "may, at Landlord's discretion, as agent for Tenant, relet the Premises, or any part "
            "thereof, for the whole or any part of the then unexpired Term, and may receive and collect "
            "all Rent payable by virtue of such reletting, and, at Landlord's option, hold Tenant "
            "liable for any difference between the Rent that would have been payable under this "
            "Agreement during the balance of the unexpired Term, if this Agreement had continued in "
            "force, and the net Rent for such period realized by Landlord by means of such reletting. "
            "The Premises is also considered abandoned ten (10) days after the death of a sole Tenant."
        ),
    },
    {
        "title": "NO REPRESENTATIONS",
        "text": (
            "Tenant acknowledges that Landlord has not made any representations, written or oral, "
            "concerning the safety of the community or the effectiveness or operability of any security "
            "devices or security measures. Tenant acknowledges that Landlord does not warrant or "
            "guarantee the safety or security of Tenant or his or her guests or invitees against the "
            "criminal or wrongful acts of third parties. Each Tenant, guest, invitee and Additional "
            "Occupant(s) is responsible for protecting his or her own person and property."
        ),
    },
    {
        "title": "ATTORNEY / COLLECTION FEES",
        "text": (
            "To the extent allowed under applicable law, should it become necessary for Landlord to "
            "employ an attorney to enforce any of the conditions or covenants hereof, or a collection "
            "company to recover any financial loss, including the collection of Rent or gaining "
            "possession of the Premises, the prevailing party may be awarded all related attorney's "
            "fees and/or collection expenses so incurred as allowed by Michigan statute Section 600.5759."
        ),
    },
    {
        "title": "SEVERABILITY",
        "text": (
            "If any provision of this Agreement or the application thereof shall, for any and to any "
            "extent, be invalid or unenforceable, neither the remainder of this Agreement nor the "
            "application of the provision to other persons, entities, or circumstances shall be "
            "affected thereby, but instead shall be enforced to the maximum extent permitted by law."
        ),
    },
    {
        "title": "TIME",
        "text": "Time is of the essence to the terms of this Agreement.",
    },
    {
        "title": "INDEMNIFICATION",
        "text": (
            "To the maximum extent permitted under applicable law, Landlord shall not be liable for "
            "any damage or injury of or to the Tenant, Tenant's family, Additional Occupant(s), "
            "guests, invitees, agents, or employees, or to any person entering the Premises or the "
            "building of which the Premises are a part or to goods or equipment, or in the structure "
            "or equipment of the structure of which the Premises are a part, and Tenant hereby agrees "
            "to indemnify, defend, and hold Landlord harmless from any and all claims or assertions "
            "of every kind and nature."
        ),
    },
    {
        "title": "DESCRIPTIVE HEADINGS",
        "text": (
            "The descriptive headings used herein are for convenience of reference only, and they are "
            "not intended to have any effect whatsoever in determining the rights or obligations of "
            "the Landlord or Tenant."
        ),
    },
    {
        "title": "NON WAIVER",
        "text": (
            "No indulgence, waiver, election, or non-election by Landlord under this Agreement shall "
            "affect Tenant's duties and liabilities hereunder."
        ),
    },
    {
        "title": "ENTIRE AGREEMENT",
        "text": (
            "The foregoing Agreement constitutes the entire Agreement between the Parties and "
            "supersedes any online, oral, or written representations or agreements that may have been "
            "made by either Party. Further, Tenant represents that he or she has relied solely on his "
            "or her own judgment, experience, and expertise in entering into this Agreement with "
            "Landlord."
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
