# GreenPR manual sales and license fulfillment

The launch uses public GitHub requests, manually confirmed payment, and signed offline
licenses. The website does not collect payment or activate subscriptions.
`catalog.json` records reference prices only. No hosted backend is required.
Use the [first-sale checklist](first-sale-checklist.md) for contact privacy,
payment confirmation, issuance, activation and renewal handoffs. Copy the empty
[customer register](customer-register.template.csv) to a private location before
recording any real customer information.

## Request and payment

1. Review the [Team request form](https://github.com/tech49labs/greenpr/issues/new?template=team-license.yml)
   or [Enterprise request form](https://github.com/tech49labs/greenpr/issues/new?template=enterprise-license.yml).
   General requests use the [issue chooser](https://github.com/tech49labs/greenpr/issues/new/choose).
   Forms assign requests to verified account `Mbuso-Harvey`; GitHub handles
   notifications according to that account's settings. No paid mailbox is needed.
2. Keep the public request limited to plan, repository count and non-sensitive
   requirements. Do not request personal information, payment details, private
   repository names, license files or code publicly. Agree an appropriate private
   channel manually before collecting customer identity, exact repository scope,
   payment information or delivering licenses. That channel is not yet configured
   or promised by the public form.
3. Quote Team at USD 49 per repository/month or Enterprise at USD 899 per GitHub
   organization/month. Team licenses each cover one repository; Enterprise covers
   one GitHub organization. Record applicable tax and payment terms on the agreed
   invoice before collecting payment. Automatic recurring collection is not live.
4. Issue the agreed invoice using the operator's authorized payment process.
   Product names, descriptions, customer communications, and license issuer must
   say **GreenPR**. Verify the actual receipt and statement information before
   using a payment method. Do not change shared account-wide branding or conceal
   legally required merchant information.
5. Confirm settled payment directly in the provider, matching customer, invoice,
   amount, currency, and paid period. A screenshot, email, or browser success page
   is not payment confirmation.

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
