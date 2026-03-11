# Data Deletion and Retention Policy

**Blue Deer Property Management**
**Effective Date:** March 1, 2026
**Last Reviewed:** March 1, 2026
**Next Review Date:** March 1, 2027

---

## 1. Purpose

This policy defines how Blue Deer Property Management ("Blue Deer") collects, retains, and deletes consumer data in compliance with applicable data privacy laws, including state-level data protection regulations. This policy applies to all data processed through our property management platform, including data obtained via the Plaid API.

## 2. Scope

This policy covers:
- Tenant personal information (name, email, phone, address)
- Tenant financial data (bank account tokens, payment records)
- Plaid API data (access tokens, account identifiers, institution information)
- Property and lease records
- Communication records (SMS, notifications)

## 3. Data Retention Schedules

| Data Category | Retention Period | Justification |
|---|---|---|
| **Active tenant PII** | Duration of tenancy + 3 years | Lease compliance, legal requirements |
| **Plaid access tokens** | Duration of tenancy or until tenant unlinks account | Required for active payment processing |
| **Payment transaction records** | 7 years from transaction date | IRS record-keeping requirements (26 USC 6001) |
| **Bank account identifiers (masks, institution names)** | 7 years from last transaction | Financial audit trail |
| **Lease documents** | Duration of tenancy + 7 years | Legal compliance, dispute resolution |
| **SMS/communication logs** | 2 years from date of communication | Operational reference |
| **Inactive tenant records** | 3 years after lease termination | Legal compliance, reference |
| **Entity/landlord bank account info** | Duration of entity activity + 7 years | Financial record-keeping |

## 4. Data Deletion Procedures

### 4.1 Tenant Account Deletion
When a tenant's lease is terminated or a deletion request is received:
1. Plaid access tokens are revoked via the Plaid API (`/item/remove` endpoint)
2. Bank account records are deactivated and access tokens are purged
3. Personal contact information is anonymized after the retention period expires
4. Payment records are retained per IRS requirements but de-linked from PII after retention period

### 4.2 Plaid-Specific Data
- **Access tokens:** Deleted immediately upon tenant unlinking their bank account or upon lease termination by calling Plaid's `/item/remove` endpoint
- **Account metadata** (masks, institution names): Retained with payment records for the financial retention period, then deleted
- **No raw account or routing numbers** from Plaid are stored; only tokenized references

### 4.3 Consumer Data Deletion Requests
Upon receiving a verifiable consumer data deletion request:
1. Request is acknowledged within 5 business days
2. Plaid tokens are revoked within 10 business days
3. PII is deleted or anonymized within 30 business days
4. Financial records subject to legal retention requirements are retained per schedule but access is restricted
5. Requestor is notified upon completion

### 4.4 Entity/Landlord Bank Account Data
- Manually entered bank account details (routing/account numbers) are deleted when an entity is removed or the account is unlinked
- Plaid-linked entity accounts are revoked via the Plaid API upon unlinking

## 5. Data Minimization

Blue Deer follows data minimization principles:
- We only collect data necessary for property management and rent payment processing
- Plaid integration uses only the products required (Transfer for payment processing)
- We do not store raw bank account numbers from Plaid — we rely on Plaid's tokenized access
- Bank account masks (last 4 digits) and institution names are stored for display purposes only

## 6. Data Storage Security

- All data is stored in a managed PostgreSQL database hosted on Railway (cloud infrastructure)
- Data at rest is encrypted via the hosting provider's storage encryption
- Data in transit is encrypted using TLS 1.2 or higher
- Database access is restricted to the application service via environment-configured credentials
- Plaid API credentials are stored as environment variables, never in source code

## 7. Third-Party Data Sharing

Blue Deer does not sell consumer data. Data is shared only with:
- **Plaid:** For payment processing (governed by Plaid's own privacy policy)
- **Twilio:** For SMS notifications (phone numbers only)
- No other third parties receive consumer financial data

## 8. Policy Review

This policy is reviewed annually by the owner/operator of Blue Deer Property Management. Reviews assess:
- Compliance with current data privacy regulations
- Adequacy of retention periods
- Effectiveness of deletion procedures
- Changes in third-party data processor relationships

## 9. Contact

For data deletion requests or questions about this policy, contact:
- **Email:** silocapital@gmail.com

---

*This policy is maintained by Blue Deer Property Management and is subject to updates as regulations and business practices evolve.*
