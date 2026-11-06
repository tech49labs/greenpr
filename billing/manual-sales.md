# GreenPR manual sales and license fulfillment

The launch uses a private plan enquiry, owner-managed payment arrangements and
signed offline licenses. The website does not collect payment or activate
subscriptions. No GreenPR customer account or billing backend is required.

## Request and owner follow-up

1. Both paid-plan buttons open the [private enquiry form](https://docs.google.com/forms/d/e/1FAIpQLSd102fTw1I4rqFDYx00odjJO2aLth251H5znuUcI4KAitSokQ/viewform).
   It collects plan, company name, contact name, email and optional contact details.
   Visitors do not need to sign in. Responses are not published on GitHub or
   shared with other respondents.
2. The existing operator account owns the form and receives new-response email
   notifications. The receiving address stays outside source and public pages.
   Open the notification's View Response link to inspect the contact details.
   Do not place those details into a public issue.
3. The owner contacts the prospect and handles all payment arrangements directly.
   This launch task does not configure bank accounts, collect banking details,
   process funds or introduce automated billing. The form takes no payment.
4. Team remains USD 49 per repository/month; Enterprise remains USD 899 per GitHub
   organization/month. Licensing and any signed-license issuance follow the
   separately agreed customer scope and owner-confirmed payment.

A marked fixture enquiry was accepted on November 6, 2026 and its new-response
notification was found in the existing private inbox. No production customer
payment or license was involved. Public support still uses sanitized GitHub
issues; personal contact details belong in the private enquiry channel.

## Issue and deliver

Keep the signing key outside the repository, with restricted operator access and
backup. It must match the released `engine/license_public_key.pem`. Customer
licenses and audit records also stay outside the repository. Never send the key
or adjacent `.audit.json` file to the customer.

Example Team issuance; replace all illustrative values with verified ones:

```sh
python scripts/issue_license.py --plan team --organization-id CUSTOMER_ID --repository OWNER/REPOSITORY --expires-at 2027-01-01T00:00:00Z --payment-reference VERIFIED_INVOICE_REFERENCE --signing-key /secure/greenpr-signing.pem --output /secure/licenses/customer-period.json
```

For Enterprise, use `--plan enterprise --github-organization OWNER` instead of
`--repository OWNER/REPOSITORY`. Choose expiry from the paid period; the example
date is illustrative. Use a new filename for each issuance or renewal. The
issuer rejects existing output/audit destinations, mismatched keys, expired or
timezone-free dates, and invalid scope. It publishes the audit before the license.
It does not charge a customer or send email.

Review payload plan, scope, organization, and expiry. Retain the audit with the
verified payment reference. Deliver only the signed license JSON and setup through the separately agreed
private channel. Never attach license files to a public issue:

```sh
# macOS/Linux
export GREENPR_LICENSE_FILE=/secure/path/customer-period.json
python remediate.py --commercial --help
```

```powershell
# PowerShell
$env:GREENPR_LICENSE_FILE = 'C:\secure\customer-period.json'
python remediate.py --commercial --help
```

`--help` only displays usage; it does not validate a license. Run the chosen
documented command with `--commercial` in the licensed repository to validate
before remediation. Its GitHub `origin` must match the scope. Agree provider
calls and repository writes with the customer before onboarding.

## Renewals and cancellations

Keep an operator register of customer, scope, paid-through date, invoice reference,
delivered filename, and renewal status. Review upcoming expiries; confirm payment
before issuing replacements. Cancellation stops future invoices and renewal
issuance. Existing offline licenses last until signed expiry and cannot be
centrally revoked immediately. Explain this boundary when agreeing refund and
cancellation terms. Record refunds, disputes, corrections, and delivery failures.

## Rehearsal

Run `python -m unittest discover -s tests -p test_license_issue.py -v`. Nine tests
exercise the actual CLI using ephemeral keys and a disposable Git repository:
valid issuance, wrong scope/key, expiry/timezone rejection, existing output/audit
protection, and source-tree output refusal. They do not prove payment settlement,
GitHub notification delivery, production signing-key possession, or customer onboarding.

Before the first sale, rehearse with fixture keys and a clearly marked test
payment reference. Verify the authorized invoice process and agree private
fulfillment with the customer. These are required before a paid sale, not before
publishing the request website. Never use a real grant as a test artifact.
