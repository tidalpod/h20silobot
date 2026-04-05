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


# ─── Comprehensive Section 2: Special Provisions (26 provisions) ─────────────
# Used for the comprehensive/master lease template.
# Includes all 15 standard provisions plus 11 new ones from the master lease.

COMPREHENSIVE_SECTION_2_PROVISIONS = [
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
            "accrued late fees, and any other charges are paid in full.\n\n"
            "If Tenant fails to pay the rent in full before the end of the 5th day after it's due, "
            "Tenant will be assessed a late charge of a fee of five percent (5%) of the rental "
            "payment. Landlord reserves and in no way waives the right to insist on payment of the "
            "rent in full on the date it is due."
        ),
    },
    {
        "key": "rent_increases",
        "title": "RENT INCREASES",
        "text": (
            "In the event of a rent increase, Tenant shall be notified pursuant to applicable state "
            "laws and/or statutes.\n\n"
            "Property Is Rented As Is. If you request Upgrades/Changes, an increase in rent may be "
            "required to cover these expenses."
        ),
    },
    {
        "key": "nsf_fees",
        "title": "BAD CHECKS / NSF FEES",
        "text": (
            "If a personal check or ACH draft is returned by Tenant's bank for any reason, a charge "
            "of {nsf_fee} shall be added to Rent for the month, and Tenant shall not be "
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
            "to that failure.\n\n"
            "In the event of the sale of the property upon which this premises is situated or the "
            "transfer or assignment by the Landlord of this Lease, the Landlord shall have the right "
            "to transfer said security deposit to the transferee, notify Tenant by mail of such transfer "
            "and of the transferee's name and address, and Landlord shall be considered released from "
            "all liability for the return of the security deposit, and the Tenant shall look solely to "
            "the new Landlord for the return of his security deposit."
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
        "key": "possession_at_commencement",
        "title": "POSSESSION AT COMMENCEMENT OF TERM",
        "text": (
            "Tenant shall not be entitled to possession of the premises designated for lease until "
            "the security deposit and first month's rent (or prorated portion thereof), less any "
            "applicable promotional discount, is paid in full and the premises designated for lease "
            "is vacated by the prior tenant. If Landlord is unable to deliver possession of the "
            "premises to Tenant on or before the commencement of the term of this Lease due to "
            "another person occupying the premises, Tenant's rights of possession hereunder shall "
            "be postponed until said premises are vacated by such other person, and rent due "
            "hereunder shall be abated at the rate of one-thirtieth (1/30) of a monthly installment "
            "for each day that possession is postponed. Tenant expressly agrees that Landlord shall "
            "not be liable for damages to Tenant in the event Tenant, for any reason whatsoever, is "
            "unable to enter and occupy the premises."
        ),
    },
    {
        "key": "condition_of_premises",
        "title": "CONDITION OF PREMISES / TENANT EXAMINATION",
        "text": (
            "Property is Rented As Is. Nothing can be deducted from the rent. You can do upgrades "
            "at your own expenses. You are accepting the property the way it is. Tenant acknowledges "
            "that prior to occupying the Premises, Tenant has examined the Premises and is satisfied "
            "with the condition, subject to those items specifically stated on the Property Condition "
            "Report (or like-titled document). By accepting possession of the Premises, Tenant "
            "acknowledges and agrees that no repairs or cleaning are required or requested. Tenant "
            "agrees and accepts the Premises \"As Is\" condition, and that no warranty or guarantees "
            "are expressed or implied by Landlord. In the event that not all Tenants can be present "
            "at the time of move-in, the acceptance of the condition by one or more than one "
            "Tenant(s) shall be sufficient as to establishing the condition at the start of the Term.\n\n"
            "Tenant agrees that no representations as to the condition of the premises have been "
            "made and that no agreement has been made to redecorate, repair or improve the premises "
            "unless hereinafter set forth specifically in writing. The Landlord will deliver the "
            "leased premises and all common areas in a habitable condition, pursuant to applicable "
            "State law. Tenant takes premises in its AS-IS condition. Tenant agrees not to damage "
            "the premises through any act or omission, and to be responsible for any damages "
            "sustained through the acts or omissions of Tenant, Tenant's family or Tenant's invitees, "
            "licensees, and/or guests. If such damages are incurred, Tenant is required to pay for "
            "any resulting repairs at the same time and in addition to the next month's rent payment, "
            "with consequences for nonpayment identical to those for nonpayment of rent described herein."
        ),
    },
    {
        "key": "cleaning",
        "title": "CLEANING",
        "text": (
            "Tenant(s) is responsible for cleaning all areas of the Premises, including but not "
            "limited to, living room, dining room, kitchen, hallways, laundry room, bedrooms, "
            "closets, bathrooms, outdoor walkways, and parking spaces. To prevent the infestation "
            "of rodents and insects, Tenants must remove any collected trash and food waste from "
            "the Premise at least once a week. Carpets and Rugs must be vacuumed at least once a "
            "week. Hardwood floors or Tiles must be swept once a week. Bathrooms must be cleaned "
            "regularly, and as frequently as needed, to prevent the formation of mold and mildew. "
            "If Tenant(s) does not clean adequately and regularly, Tenant(s) will be liable for "
            "reasonable cleaning charges - including charges for cleaning carpets, draperies, "
            "furniture, walls, etc. that are soiled beyond normal wear (that is, wear or soiling that "
            "occurs without negligence, carelessness, accident, or abuse). Landlord reserves the "
            "right to hire a recurring Professional Cleaning/Maid Service if Tenant(s) are not "
            "keeping the Premises in clean/sanitary order at Landlord's own judgment. This expense "
            "will be the responsibility of the Tenant(s)."
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
        "key": "alterations_repairs_by_tenant",
        "title": "ALTERATIONS AND REPAIRS BY TENANT",
        "text": (
            "Unless authorized by law, Tenant will not, without Landlord's prior written consent, "
            "alter, re-key or install any locks to the premises or install or alter any burglar alarm "
            "system. Tenant will not remodel or make any structural changes, alterations or additions "
            "to the premises, will not paper, paint or decorate, nor install, attach, remove or "
            "exchange appliances or equipment such as air conditioning, heating, refrigerating or "
            "cooking units, radio or television antennae; nor drive nails or other devices into the "
            "walls or woodwork (a reasonable number of picture hangers excepted), nor refinish or "
            "shellac wood floors, nor change the existing locks of the premises, without the prior "
            "written permission of the Landlord or his Agent. Any of the above-described work shall "
            "become part of the dwelling.\n\n"
            "The tenant will make all necessary repairs to the property (up to {max_repair_amount} "
            "per occurrence) to keep in a habitable condition and shall promptly repair after notifying "
            "the landlord, all facilities and appliances, including, electrical, plumbing, sanitary, "
            "heating, ventilating, and air conditioning systems. The tenant shall make any and all "
            "other repairs to the property to keep same in an aesthetically pleasing condition and "
            "appearance. HVAC AIR FILTERS WILL BE THE SOLE RESPONSIBILITY OF THE TENANT TO "
            "REPLACE ON A MONTHLY BASIS, ANY HVAC RELATED EXPENSES THAT COME AS A RESULT "
            "OF DIRTY FILTERS WILL BE THE TENANTS RESPONSIBILITY."
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
        "key": "landlord_responsibilities",
        "title": "LANDLORD'S RESPONSIBILITIES AND DUTIES",
        "text": (
            "Landlord shall maintain:\n"
            "- Comply with the current applicable building and housing codes.\n"
            "- Make all repairs and do whatever is necessary to put and keep the premises in a fit "
            "and habitable condition.\n"
            "- Keep all common areas of the premises in safe condition.\n"
            "- Maintain in good and safe working order and promptly repair all electrical, plumbing, "
            "sanitary, heating, ventilating, air conditioning, and other facilities and appliances "
            "supplied or required to be supplied by Landlord provided that notification of needed "
            "repairs is made to Landlord in writing by Tenant, except in emergency situations.\n"
            "- Provide operable smoke detectors, either battery-operated or electrical, having an "
            "Underwriters' Laboratories, Inc., listing or other equivalent national testing laboratory "
            "approval, and install the smoke detectors in accordance with either the standards of the "
            "National Fire Protection Association or the minimum protection designated in the "
            "manufacturer's instructions. Landlord shall replace or repair the smoke detectors within "
            "15 days of receipt of notification if Landlord is notified of needed replacement or "
            "repairs in writing by Tenant.\n\n"
            "But landlord shall have no duty to maintain any of the above if the noncompliance is "
            "the fault of the Tenant."
        ),
    },
    {
        "key": "tenant_responsibilities",
        "title": "TENANT'S RESPONSIBILITIES AND DUTIES",
        "text": (
            "Tenant shall:\n"
            "- Keep that part of the premises that Tenant occupies and uses as clean and safe as "
            "the conditions of the premises permit and cause no unsafe or unsanitary conditions in "
            "the common areas and remainder of the premises that Tenant uses.\n"
            "- Dispose of all ashes, rubbish, garbage, and other waste in a clean and safe manner.\n"
            "- Keep all plumbing fixtures in the dwelling unit or used by Tenant as clean as their "
            "condition permits.\n"
            "- Not deliberately or negligently destroy, deface, damage, or remove any part of the "
            "premises, nor render inoperable the smoke detector provided by Landlord, or knowingly "
            "permit any person to do so.\n"
            "- Comply with any and all obligations imposed upon Tenant by current applicable building "
            "and housing codes.\n"
            "- Be responsible for all damage, defacement, or removal of any property inside a dwelling "
            "unit in Tenant's exclusive control unless the damage, defacement or removal was due to "
            "ordinary wear and tear, acts of Landlord or Landlord's agent, defective products supplied "
            "or repairs authorized by Landlord, acts of third parties not invitees of Tenant, or "
            "natural forces.\n"
            "- Notify Landlord, in writing, of the need for replacement of or repairs to a smoke "
            "detector. Landlord shall ensure that a smoke detector is operable and in good repair at "
            "the beginning of each tenancy. Landlord shall place new batteries in a battery-operated "
            "smoke detector at the beginning of a tenancy and Tenant shall replace the batteries as "
            "needed during the tenancy.\n\n"
            "Tenant agrees that any violation of these provisions shall be considered a breach of "
            "this Lease."
        ),
    },
    {
        "key": "disturbances_violation_laws",
        "title": "DISTURBANCES AND VIOLATION OF LAWS",
        "text": (
            "Tenant, guests and invitees of either tenant or guests shall not use the premises for "
            "any unlawful purpose and shall comply fully with all applicable federal, state and local "
            "laws and ordinances, including laws prohibiting the use, possession or sale of illegal "
            "drugs. Nor shall Tenant, guests and invitees of either tenant or guests use the premises "
            "in a manner offensive to others. Nor shall Tenant, guests and invitees of either tenant "
            "or guests create a nuisance by annoying, disturbing, inconveniencing or interfering with "
            "the quiet enjoyment of any other tenant or nearby resident. Tenant agrees to immediately "
            "inform Landlord and the appropriate authorities upon obtaining actual knowledge of any "
            "illegal acts on or upon the leased premises."
        ),
    },
    {
        "key": "pest_control",
        "title": "PEST CONTROL",
        "text": (
            "Tenant shall be responsible for all pest control such as mice, fleas, roaches, ants, "
            "vermin, insects or other pests unless evidence of same is present for up to two weeks "
            "after the lease start date. It is required for the Tenant to notify Landlord of any "
            "roach or any mice infestation. If infestation is due to cleanliness, tenant will be "
            "responsible for monthly service and any additional fees provided by pest control vendor. "
            "Tenant shall maintain a clean living environment free from food waste, trash buildup, "
            "and standing water to prevent pest infestations. Landlord shall be responsible for "
            "structural pest issues, including pre-existing infestations or those caused by defects "
            "in the property (e.g., termites). If an infestation occurs due to tenant negligence, "
            "the tenant shall be responsible for all necessary extermination and remediation costs."
        ),
    },
    {
        "key": "vehicle_parking",
        "title": "VEHICLE PARKING",
        "text": (
            "No automobile, truck, motorcycle, trailers or other such vehicles shall be parked on "
            "the property without current license plates and said vehicles must be in operating "
            "condition. Such vehicles may be parked in driveways or other designated parking area, "
            "if provided, or in the street."
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
            "\"for sale\", \"for rent\", or \"vacancy\" signs in or about the Premises.\n\n"
            "In addition to the rights provided by law, in the event of an emergency, to make repairs "
            "or improvements or to show the premises to prospective buyers or tenants or to conduct an "
            "annual inspection or to address a safety or maintenance problem or to remove any "
            "alterations, additions, fixtures, and any other objects which may be affixed or erected in "
            "violation of the terms of this Lease, Landlord or Landlord's duly authorized agents may "
            "enter the premises. Furthermore, Landlord retains a Landlord's Lien on all personal "
            "property placed upon the premises to secure the payment of rent and any damages to the "
            "leased premises."
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
        "title": "DAMAGE TO PREMISES / DESTRUCTION OF PROPERTY",
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
            "recommence and the Agreement continue according to the terms.\n\n"
            "If the premises are rendered totally unfit for occupancy by fire, act of God, act of "
            "rioters or public enemies, or accident, and the damage or destruction occurred without "
            "negligence on the part of the Tenant or his agents or servants, Tenant may surrender the "
            "demised premises by a writing to that effect delivered or tendered to Landlord within 10 "
            "days from the damage or destruction, and by paying or tendering at the same time all rent "
            "in arrear, and a part of the rent growing due at the time of the damage or destruction, "
            "proportionate to the time between the last period of payment and the occurrence of the "
            "damage or destruction, and Tenant shall be thenceforth discharged from all rent accruing "
            "afterwards.\n\n"
            "Tenant, Tenant's guests and invitees of either Tenant or Tenant's guests will not engage "
            "in any activity or action that may cause severe property damage."
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
            "situations it is necessary to make a change to the billing method.\n\n"
            "The Landlord at his option may pay the bill and all fees in arrears and this amount paid "
            "shall be additional rent due from the Tenant to the Landlord, immediately upon the "
            "Landlord's payment. In such case, the Landlord shall have the right to file summary "
            "ejectment for non-payment of rent AND THE TENANT SHALL BE SUBJECT TO EVICTION FOR "
            "NON-PAYMENT OF WATER AND SEWER CHARGE, IN THE SAME MANNER OF ALL OTHER RENT."
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
        "key": "mold_and_mildew",
        "title": "MOLD AND MILDEW",
        "text": (
            "There are no established guidelines for unacceptable air quality caused by mold. Mold is "
            "a naturally occurring phenomenon. Mold and/or mildew should be cleaned as soon as it "
            "appears. Mold and/or mildew growth can often be seen in the form of discoloration. The "
            "different colors of mold range from white to black, including, but not limited to, green, "
            "gray, brown, orange, yellow and other colors. Your housekeeping and living habits are an "
            "integral part of the ability of mold to grow. In order for mold to grow, water and/or "
            "moisture must be present.\n\n"
            "TENANT AGREES to maintain the Premises in a manner that prevents the occurrence of mold "
            "or mildew growth within the Premises. In furtherance of such obligation, TENANT AGREES TO "
            "PERFORM THE FOLLOWING:\n"
            "- To keep the Premises free from dirt and debris that can harbor mold;\n"
            "- To inspect the Premises regularly for the indications and sources of indoor moisture;\n"
            "- To immediately report to management any discoloration evidenced on walls, floors, or "
            "ceiling and/or any water intrusion, such as plumbing leaks, drips or flooding;\n"
            "- To not air dry wet clothes indoors;\n"
            "- To always utilize stove hood vents when cooking items that may cause steam;\n"
            "- When showering/bathing, to always utilize the bathroom fan and to notify management "
            "of any nonworking fan;\n"
            "- To water plants outdoors;\n"
            "- To notify management in writing of overflows from bathroom, kitchen or any other water "
            "source facilities, especially in cases where the overflow may have permeated walls, "
            "flooring or cabinets;\n"
            "- TO IMMEDIATELY WIPE DOWN ANY WATER OR CONDENSATION THAT APPEARS AND/OR "
            "DEVELOPS ON ANY AREA OR ANY SURFACE;\n"
            "- To clean upon first appearance, any mildew from condensation on window interiors, "
            "bathroom & kitchen walls, floor and/or ceilings;\n"
            "- TO REPORT TO MANAGEMENT IN WRITING AND VERBALLY THE PRESENCE OF ANY MOLD "
            "GROWTH on surfaces inside the Premises;\n"
            "- To allow management immediate entry to the Premises to inspect and make necessary "
            "repairs in the event mold or water intrusion is present;\n"
            "- To use all reasonable care to close all windows and other openings in the Premises to "
            "prevent outdoor water from penetrating into the interior unit;\n"
            "- To clean and dry any visible condensation/moisture on windows and window tracks, "
            "walls and other surfaces, including personal property as soon as reasonably possible;\n"
            "- To notify management of any problems with air-conditioning or heating systems that "
            "are discovered by Tenant;\n"
            "- To maximize the circulation of air by keeping furniture away from walls and out of "
            "corners;\n"
            "- In addition to the above, Tenant further agrees to perform all responsibilities set "
            "forth in this MOLD/MOISTURE DISCLOSURE STATEMENT.\n\n"
            "TENANT FURTHER AGREES to indemnify and hold harmless Owner and Owner's management "
            "agents from any suits, actions, claims, losses, damages, and expenses (including "
            "reasonable attorney's and court costs) and any liability whatsoever that Owner and/or its "
            "management agents may sustain or incur as a result of Tenant's failure to comply or "
            "perform with the obligations set forth above or as the result of intentional or negligent "
            "action or failure to act on the part of Tenant or any other person living in, occupying, "
            "or using the Premises."
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


# ─── Comprehensive Section 3: General Provisions (33 provisions) ─────────────
# Used for the comprehensive/master lease template.

COMPREHENSIVE_SECTION_3_PROVISIONS = [
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
            "statutory rights to seek a release of rental obligation under MCL 554.601b.\n\n"
            "In the event Tenant is a member of the United States Armed Forces and (i) is required "
            "to move pursuant to permanent change of station orders to depart 50 miles or more from "
            "the location of the dwelling unit, or (ii) is prematurely or involuntarily discharged or "
            "released from active duty with the United States Armed Forces, Tenant may terminate his "
            "rental agreement for a dwelling unit by providing Landlord with a written notice of "
            "termination to be effective on a date stated in the notice that is at least 30 days after "
            "Landlord's receipt of the notice. The notice to Landlord must be accompanied by either a "
            "copy of the official military orders or a written verification signed by the member's "
            "commanding officer.\n\n"
            "In consideration of early termination of this rental agreement, Tenant is liable to "
            "Landlord for liquidated damages provided Tenant has completed less than nine months of "
            "the tenancy and Landlord has suffered actual damages due to loss of the tenancy. The "
            "liquidated damages shall be in an amount no greater than one month's rent if Tenant has "
            "completed less than six months of the tenancy as of the effective date of termination, "
            "or one-half of one month's rent if the tenant has completed at least six but less than "
            "nine months of the tenancy as of the effective date of termination."
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
            "modifications of such mortgages, liens, or encumbrances.\n\n"
            "Tenant agrees to accept the premises subject to and subordinate to any existing or future "
            "mortgage or other lien, and Landlord reserves the right to subject premises to same. "
            "Tenant agrees to and hereby irrevocably grants Landlord power of attorney for Tenant for "
            "the sole purpose of executing and delivering in the name of the Tenant any documents "
            "related to the Landlord's right to subject the premises to a mortgage or other lien."
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
            "Premises.\n\n"
            "Tenant will, upon termination of this Lease, surrender the premises and all fixtures and "
            "equipment of Landlord therein in good, clean and operating condition, ordinary wear and "
            "tear excepted. Tenant shall, at time of vacating premises, clean said premises including "
            "stove and refrigerator and remove trash from the premises. Upon vacating the premises "
            "Tenant shall deliver all keys thereto to the Landlord or his Agent within twenty-four "
            "(24) hours after vacating. Failure to comply will be cause to charge Tenant for "
            "changing locks."
        ),
    },
    {
        "title": "QUIET ENJOYMENT",
        "text": (
            "Tenant, upon payment of all of the sums referred to herein as being payable by Tenant, "
            "and Tenant's performance of all Tenant's agreements contained herein, and Tenant's "
            "observance of all rules and regulations, shall and may peacefully and quietly have, hold, "
            "and enjoy said Premises for the term hereof. Landlord agrees that Tenant, keeping and "
            "performing the covenants herein contained on the part of the Tenant to be kept and "
            "performed, shall at all times during the existence of this lease, renewals or extensions "
            "peaceably and quietly, have, hold, and enjoy the leased premises, without suit, trouble "
            "or hindrance from Landlord, or any person claiming under Landlord."
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
        "title": "TERMINATION OF LEASE - HOLD OVER",
        "text": (
            "Either Landlord or Tenant may terminate this lease at the expiration of said Lease or "
            "any extension thereof by giving the other thirty (30) days written notice prior to the "
            "due date. Since time is of the essence in all matters of this Lease, and especially with "
            "respect to the issue of renewal, if Tenant shall hold over after the expiration of the "
            "term of this Lease, Tenant shall, in the absence of any written agreement to the "
            "contrary, be a tenant from month to month, as defined by applicable Michigan law, at the "
            "monthly rate in effect during the last month of the expiring term. All other terms and "
            "provisions of this Lease shall remain in full force and effect.\n\n"
            "In the event Tenant becomes a month-to-month tenant in the manner described above, "
            "Tenant shall be required to provide Landlord, in advance, sixty (60) days written notice "
            "of Tenant's intention to surrender the Premises. Landlord, at Landlord's discretion, at "
            "any time during a month-to-month tenancy, may terminate the month-to-month tenancy or "
            "lease by serving Tenant with a written notice of termination, or by any other means "
            "allowed law. Upon termination, Tenant shall vacate the premises and deliver same unto "
            "Landlord on or before the expiration of the period of notice.\n\n"
            "However, in the event Tenant holds over after the expiration of the term of this Lease, "
            "and after Landlord or Landlord's agent makes demand, in writing, for the possession of "
            "the premises, Landlord or Landlord's agent may file a complaint with the clerk of the "
            "appropriate court and ask to be put in possession of the leased premises."
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
            "The Premises is also considered abandoned ten (10) days after the death of a sole Tenant.\n\n"
            "If Landlord finds evidence that clearly shows the premises has been voluntarily vacated "
            "after the paid rental period has expired and Landlord has no notice of a disability that "
            "caused the vacancy, a presumption of abandonment shall arise 10 or more days after "
            "Landlord has posted conspicuously a notice of suspected abandonment both inside and "
            "outside the premises and has received no response from Tenant. In such event, Tenant "
            "will be considered in default of this Lease and Landlord or Landlord's agents may "
            "immediately or any time thereafter enter and re-take the leased premises and terminate "
            "this Lease without notice to Tenant.\n\n"
            "Any personal property left by Tenant upon abandonment of premises shall also be "
            "considered abandoned."
        ),
    },
    {
        "title": "DISPOSITION OF TENANT'S PERSONAL PROPERTY",
        "text": (
            "If Tenant abandons personal property of five hundred dollar ($500.00) value or less in "
            "the demised premises, or fails to remove such property at the time of execution of a "
            "writ of possession in an action for summary ejectment, Landlord may, at Landlord's "
            "discretion, deliver the property into the custody of a nonprofit organization regularly "
            "providing free or at a nominal price clothing and household furnishings to people in "
            "need, upon that organization agreeing to identify and separately store the property for "
            "30 days and to release the property to the tenant at no charge within the 30-day period. "
            "In the event Landlord elects to use this procedure, Landlord shall immediately post at "
            "the demised premises a notice containing the name and address of the property recipient, "
            "post the same notice for 30 days or more at the place where rent is received, and send "
            "the same notice by first-class mail to Tenant at Tenant's last known address. Ten days "
            "after being placed in lawful possession by execution of a writ of possession, Landlord "
            "may throw away, dispose of, or sell all items of personal property remaining on the "
            "premises."
        ),
    },
    {
        "title": "HOLD HARMLESS",
        "text": (
            "To the fullest extent permitted by law, Tenant hereby agrees that Landlord and his Agent "
            "will be held free and harmless from any and all loss, claim or damage by reason of any "
            "accident, injury, or damage to any person or property occurring on or about the leased "
            "premises, unless such accident, injury, or damage shall be caused by the negligence of "
            "the Landlord, its agents, servants and/or employees."
        ),
    },
    {
        "title": "DISCLAIMER OF SECURITY WARRANTIES",
        "text": (
            "Landlord, Landlord's agents or employees make no warranties, guaranties or "
            "representations regarding the security of the Premises, common areas, or the apartment "
            "community, and any such warranties and representations, whether expressed or implied, "
            "are hereby disclaimed. Tenant hereby agrees and acknowledges that Tenant and occupant(s) "
            "shall have the exclusive responsibility of protecting the Premises, Tenant(s), "
            "occupant(s) and Tenant's guests from crime, fire, and other danger. Landlord shall not "
            "provide and shall have no duty to provide any security devices to Tenant or the apartment "
            "community with the exception of those required by applicable law. Tenant shall look "
            "solely to the Public Police Force and other forms of Public Safety for protection. "
            "Tenant agrees and acknowledges that protection against criminal action is not within the "
            "power of Landlord, Landlord's agents or employees, and though Landlord, from time to "
            "time, may provide crime deterrent services, those services cannot be relied upon by "
            "Tenant and shall not constitute a waiver of, or in any manner modify, the above "
            "agreement. Upon Tenant's reasonable request, Landlord shall consider permitting Tenant "
            "to install fire safety and/or crime deterrent devices, provided such devices do not "
            "damage the Premises, create danger, and Tenant provides Landlord with duplicate keys "
            "and alarm codes enabling Landlord to access Premises."
        ),
    },
    {
        "title": "DEFAULT / BREACH BY TENANT",
        "text": (
            "In the event of any default hereunder on the part of the Tenant, his family, servant, "
            "guests, invitees, or should the Tenant occupy the subject premises in violation of any "
            "lawful rule, regulation or ordinance issued or promulgated by the Landlord or any rental "
            "authority, then and in any of said events the Landlord shall have the right to terminate "
            "this lease by giving the Tenant personally or by leaving at the leased premises a thirty "
            "(30) day written notice of termination and this Lease shall terminate upon the expiration "
            "of thirty (30) days from the delivery of such notice if the default is not remedied "
            "within a reasonable time not in excess of thirty (30) days and the Landlord, at the "
            "expiration of said thirty (30) day notice or any shorter period conferred under or by "
            "operation of law, shall thereupon be entitled to immediate possession of said premises "
            "and may avail himself of any remedy provided by law for the restitution of possession "
            "and the recovery of delinquent rent. If this Lease is terminated, Landlord shall return "
            "all prepaid and unearned rent, and any amount of the security deposit recoverable by "
            "the Tenant.\n\n"
            "However, in the event the default is nonpayment of rent, Landlord shall not be required "
            "to deliver thirty (30) days notice as provided above but may serve Tenant with a ten "
            "(10) day written notice of termination whereupon the Tenant must pay the unpaid rent in "
            "full or surrender the premises by the expiration of the ten (10) day notice period. "
            "Failure by Tenant to pay all past-due rent by the expiration of the ten (10) day notice "
            "period shall imply a forfeiture of the term and Landlord may forthwith enter and "
            "dispossess Tenant without having declared such forfeiture or having reserved the right "
            "of reentry in this Lease. Upon Landlord's termination of this Lease, Tenant expressly "
            "agrees and understands that the entire remaining balance of unpaid rent for the remaining "
            "term of this Lease shall ACCELERATE, whereby the entire sum shall become immediately due, "
            "payable, and collectible. Landlord may hold the portion of Tenant's security deposit "
            "remaining after reasonable cleaning and repairs as a partial offset to satisfaction of "
            "the accelerated rent."
        ),
    },
    {
        "title": "REMEDIES - CUMULATIVE",
        "text": (
            "The remedies and rights contained in and conveyed by this Lease are cumulative, and are "
            "not exclusive of other rights, remedies and benefits allowed by law."
        ),
    },
    {
        "title": "NOTICE OF INJURIES ON PREMISES",
        "text": (
            "In the event of any significant injury or damage to Tenant, Tenant's family, or "
            "Tenant's invitees, licensees, and/or guests, or any personal property, suffered in the "
            "leased premises or in any common area, written notice of same shall be provided by "
            "Tenant to Landlord at the address designated for delivery of notices (identical to "
            "address for payment of rent) as soon as possible but not later than five days of said "
            "injury or damage. Failure to provide such notice shall constitute a breach of this Lease."
        ),
    },
    {
        "title": "WAIVER / NON WAIVER",
        "text": (
            "Any waiver of a default hereunder shall not be deemed a waiver of this agreement or of "
            "any subsequent default. Acquiescence in a default shall not operate as a waiver of such "
            "default, even though such acquiescence continues for an extended period of time. No "
            "indulgence, waiver, election, or non-election by Landlord under this Agreement shall "
            "affect Tenant's duties and liabilities hereunder."
        ),
    },
    {
        "title": "GROUNDS FOR TERMINATION OF TENANCY",
        "text": (
            "The failure of Tenant, guests and invitees of either tenant or guests to comply with "
            "any term of this Lease is grounds for termination of the tenancy, with appropriate "
            "notice to Tenant and procedures as required by law."
        ),
    },
    {
        "title": "COURT COSTS AND ATTORNEY / COLLECTION FEES",
        "text": (
            "To the extent allowed under applicable law, should it become necessary for Landlord to "
            "employ an attorney to enforce any of the conditions or covenants hereof, or a collection "
            "company to recover any financial loss, including the collection of Rent or gaining "
            "possession of the Premises, the prevailing party may be awarded all related attorney's "
            "fees and/or collection expenses so incurred as allowed by Michigan statute Section "
            "600.5759. Tenant agrees to pay a reasonable attorney's fee and all expenses and costs "
            "incurred thereby, to the greatest extent allowed by applicable law."
        ),
    },
    {
        "title": "AGENTS AND AUTHORITY TO RECEIVE LEGAL PAPERS",
        "text": (
            "Any notice which either party may or is required to give, shall be in writing and may "
            "be given by mailing the same, by certified mail, and shall be deemed sufficiently served "
            "upon Tenant if and when deposited in the mail addressed to the leased premises, or "
            "addressed to Tenant's last known post office address, or hand delivered, or placed in "
            "Tenant's mailbox to Tenant at the premises. If Tenant is more than one person, then "
            "notice to one shall be sufficient as notice to all. The Landlord, any person managing "
            "the premises and anyone designated by the Landlord as agent are authorized to accept "
            "service of process and receive other notices and demands."
        ),
    },
    {
        "title": "EMINENT DOMAIN",
        "text": (
            "If the premises or any part thereof or any estate therein, or any other part of the "
            "building materially affecting Tenant's use of the premise, shall be taken by eminent "
            "domain, this lease shall terminate on the date when title vests pursuant to such taking. "
            "The rent shall be apportioned as of the termination date, and any rent paid for the "
            "period beyond that date shall be repaid to Tenant. Tenant shall not be entitled to any "
            "part of the award for such taking or any payment in lieu thereof."
        ),
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
        "title": "SEVERABILITY",
        "text": (
            "If any provision of this Agreement or the application thereof shall, for any and to any "
            "extent, be invalid or unenforceable, neither the remainder of this Agreement nor the "
            "application of the provision to other persons, entities, or circumstances shall be "
            "affected thereby, but instead shall be enforced to the maximum extent permitted by law. "
            "It is understood and agreed that the terms, conditions and covenants of this Lease would "
            "have been made by both parties if such invalid, illegal, unconstitutional, inapplicable "
            "or unenforceable provision, sentence, clause, section or part had not been included "
            "therein. It is further agreed that this Lease may be executed in counterparts, each of "
            "which when considered together shall constitute the original contract."
        ),
    },
    {
        "title": "TIME",
        "text": "Time is of the essence to the terms of this Agreement.",
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
        "title": "ENTIRE AGREEMENT",
        "text": (
            "The foregoing Agreement constitutes the entire Agreement between the Parties and "
            "supersedes any online, oral, or written representations or agreements that may have been "
            "made by either Party. Further, Tenant represents that he or she has relied solely on his "
            "or her own judgment, experience, and expertise in entering into this Agreement with "
            "Landlord. This document and any Attachments constitutes the final and entire Agreement "
            "between the parties hereto, and no promises or representations, other than those "
            "contained here and those implied by law, have been made by Landlord or Tenant. Neither "
            "Landlord or Tenant shall be bound by any terms, conditions, statements, warranties or "
            "representations, oral or written, not herein contained unless made in writing and signed "
            "by both Landlord and Tenant."
        ),
    },
]


# ─── Section 4: Tenant Responsibilities Addendum (12 provisions) ────────────
# Only used for the comprehensive/master lease template.

SECTION_4_TENANT_RESPONSIBILITIES = [
    {
        "title": "Plumbing & Drain Issues",
        "text": (
            "Tenant shall be responsible for maintaining clear and functional drains, toilets, and "
            "garbage disposals. Any clogs or damage caused by tenant negligence, including but not "
            "limited to flushing wipes, grease, food, hair buildup, or other non-flushable items, "
            "shall be repaired at the tenant's expense. Landlord shall be responsible for major "
            "plumbing issues not caused by tenant misuse, such as broken pipes due to age or "
            "structural failure."
        ),
    },
    {
        "title": "HVAC & Air Filters",
        "text": (
            "Tenant shall replace HVAC filters every one to three months to ensure proper system "
            "function. If failure to replace filters results in HVAC system damage (e.g., burnt-out "
            "motor, excessive wear), the tenant shall be liable for all repair or replacement costs."
        ),
    },
    {
        "title": "Pest Control",
        "text": (
            "Tenant shall maintain a clean living environment free from food waste, trash buildup, "
            "and standing water to prevent pest infestations. Landlord shall be responsible for "
            "structural pest issues, including pre-existing infestations or those caused by defects "
            "in the property (e.g., termites). If an infestation occurs due to tenant negligence, "
            "the tenant shall be responsible for all necessary extermination and remediation costs."
        ),
    },
    {
        "title": "Mold & Moisture Prevention",
        "text": (
            "Tenant shall report any water leaks, plumbing issues, or excessive moisture to the "
            "landlord immediately. Tenant shall use exhaust fans in bathrooms and kitchens, wipe "
            "down wet surfaces, and keep the premises adequately ventilated to prevent mold growth. "
            "If mold develops due to tenant neglect, such as failure to report leaks or properly "
            "ventilate areas, the tenant shall be responsible for all cleaning and remediation costs."
        ),
    },
    {
        "title": "Appliance Use & Damage",
        "text": (
            "Tenant shall operate all appliances properly and in accordance with manufacturer "
            "guidelines. Any damage resulting from improper use, such as overloading washing "
            "machines, inserting metal into microwaves, or misuse of the garbage disposal, shall "
            "be repaired at the tenant's expense. Landlord is responsible for appliance malfunctions "
            "due to normal wear and tear."
        ),
    },
    {
        "title": "Window, Screen, and Door Damage",
        "text": (
            "Tenant shall be responsible for replacing or repairing any broken windows, damaged "
            "screens, or door hardware, including locks and knobs, unless the damage is due to a "
            "documented break-in with a police report."
        ),
    },
    {
        "title": "Flooring and Carpet Maintenance",
        "text": (
            "Tenant shall keep all flooring clean and free from stains, burns, and excessive wear. "
            "Any damage beyond normal wear and tear, including pet-related damage such as scratches, "
            "chewing, or urine stains, shall be repaired at the tenant's expense."
        ),
    },
    {
        "title": "Light Bulbs and Batteries",
        "text": (
            "Tenant shall replace all light bulbs and smoke detector batteries as needed. Landlord "
            "shall be responsible for replacing bulbs or batteries that require special equipment or "
            "professional installation."
        ),
    },
    {
        "title": "Lawn Care",
        "text": (
            "The tenant is responsible for lawn maintenance, including mowing, trimming bushes, and "
            "keeping weeds under control. Failure to maintain the lawn may result in the landlord "
            "hiring a service at the tenant's expense."
        ),
    },
    {
        "title": "Unauthorized Alterations and Repairs",
        "text": (
            "Tenant shall not make any modifications, repairs, or alterations to the property "
            "including but not limited to painting, installing fixtures, or replacing hardware, "
            "without prior written consent from the landlord. Any unauthorized changes must be "
            "removed or restored to the original condition at the tenant's expense."
        ),
    },
    {
        "title": "Smoking and Fire Hazard Prevention",
        "text": (
            "The lease designates the property as non-smoking, the tenant shall not smoke inside "
            "the unit. Any costs associated with odor removal, burn marks, or deep cleaning due to "
            "smoking shall be charged to the tenant."
        ),
    },
    {
        "key": "water_bill_payment",
        "title": "Utilities - Water Bill Payment Requirement",
        "text": (
            "Tenant acknowledges that payment of the monthly water bill is a material condition of "
            "this lease and addendum, regardless of whether the bill is issued {water_bill_method}. "
            "Tenant agrees to pay the full water bill balance each month by the due date stated on "
            "the bill or as otherwise directed by the Landlord. Failure to pay the water bill in "
            "full shall constitute a material breach of the lease and this Addendum. In the event "
            "of nonpayment, the Landlord may issue a written notice of default and, if the balance "
            "remains unpaid after any applicable cure period required by law, the Landlord may pursue "
            "all remedies allowed under the lease and applicable state and local law, including but "
            "not limited to termination of tenancy and eviction proceedings. Any unpaid water charges "
            "may also be deemed additional rent to the extent permitted by law. This provision shall "
            "be enforced in compliance with all applicable HUD, Housing Choice Voucher (HCV), and "
            "state landlord-tenant regulations."
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
