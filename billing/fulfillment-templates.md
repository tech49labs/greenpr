# Manual fulfillment templates

Copy these to the approved private channel. Replace every bracketed field before
sending. These are drafts, not issued invoices or proof of payment. The private
operator inbox must never be inserted into a public issue or customer message.

## Private scope confirmation

Thanks for your GreenPR request [REQUEST REFERENCE]. Please confirm:

- [TEAM: USD 49 / repository / month OR ENTERPRISE: USD 899 / organization / month]
- Exact GitHub [OWNER/REPOSITORY OR ORGANIZATION] and customer billing identity.
- Agreed period [START UTC] through [END UTC], and [TAX / PAYMENT TERMS].

GreenPR runs on your infrastructure. You supply any optional model-provider key
and pay that provider directly. We will never ask you to send that key. Optional
AI repair is experimental. A license does not replace verification or review.
Payment and renewals are manual. An offline license remains valid until its
signed expiry; cancellation stops future invoices and issuance.

## Invoice fields

GreenPR — Invoice [UNIQUE INVOICE ID]

Issued: [DATE]; due: [DATE]

Merchant: [REQUIRED MERCHANT IDENTITY AND CONTACT]

Customer: [PRIVATE BILLING IDENTITY]

Description: [PLAN], scope [EXACT SCOPE], period [START] to [END]

Subtotal: USD [AMOUNT]; tax: [APPLICABLE TAX]; total: USD [TOTAL]

Payment: [APPROVED EXISTING METHOD / VERIFIED RECIPIENT / CURRENCY / REFERENCE]

Terms: [AGREED REFUND, CANCELLATION AND SUPPORT TERMS]

Do not replace required merchant information with a misleading brand name.
Confirm the actual recipient display and applicable fees before issuing.

## Private license delivery

Your GreenPR [PLAN] license for [SCOPE] is attached as [FILENAME.json]. It expires
at [EXPIRY UTC]. Store it outside source control; do not post it in GitHub issues.
Only the signed license is attached, never the signing key or operator audit.

From the repository root, set its private path and run a read-only activation scan:

```powershell
$env:GREENPR_LICENSE_FILE = 'C:\private\greenpr\customer-period.json'
& 'C:\tools\greenpr\.venv\Scripts\python.exe' 'C:\tools\greenpr\remediate.py' --commercial --scan-only --ecosystem all
```

Replace installation and license paths with your actual locations. A working
GitHub origin matching your licensed scope is required. Scanning contacts advisory
services and, where needed, registries. No model key is needed for this command.
`--help` does not validate activation. Reply privately with the GreenPR version,
OS and sanitized success/error result. Never send API keys, private source or
payment credentials. Support: [APPROVED PUBLIC CONTACT].

## Renewal

Your GreenPR [PLAN] license for [SCOPE] expires [EXPIRY UTC]. To renew for
[PERIOD], confirm [TERMS / PRICE]. We will send a manual invoice and issue the
replacement license after verifying settled payment. No automatic charge occurs.

## Support acknowledgment

We received request [REFERENCE]. Please send the GreenPR version, OS, sanitized
error and receipt/run ID through this private channel. Do not send keys, private
source or signed license contents. We will confirm the next action after review.
