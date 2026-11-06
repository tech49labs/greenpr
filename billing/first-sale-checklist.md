# First paid customer: operator checklist

Use the existing [manual sales process](manual-sales.md). No checkout integration,
customer account, hosted backend, automated charge or paid mailbox is needed.
Use the [fulfillment templates](fulfillment-templates.md) for scope confirmation,
invoice fields, delivery, renewal and support; replace placeholders privately.
Keep the operator's destination inbox and customer register outside the repository.
Publish only an approved GreenPR contact address after a send/reply privacy test.

## Ready before collecting money

- Verify both pricing buttons reach the published private enquiry form. Check
  plan, company name, contact name, email and optional contact details, anonymous
  access, private responses and the new-response email notification.
- Keep the receiving inbox outside public pages and source. No new mailbox or
  forwarding-service account is required. The owner contacts prospects using
  their supplied details and handles payment arrangements directly.
- Do not add banking fields, checkout, customer accounts or automated billing.
  This form takes no payment and does not activate a subscription.
- Record signed-key readiness without exporting secrets. The November 6 read-only
  check found a matching Ed25519 key and restricted file access; a domain-separated
  non-license challenge verified. This does not establish backup recovery.
  Keep an owner-approved protected backup outside source, and verify a restored
  copy against the released public key before relying on it. Do not create a
  real production license as a test artifact.

## Request to activation

1. Open the private response from its notification. Follow up through the
   customer-provided contact details; do not copy their identity or scope to GitHub.
2. Privately confirm plan, exact GitHub owner/repository or organization, customer
   identity, USD price, paid period, tax/payment terms and support contact. BYOK
   credentials stay with the customer and are never requested for licensing.
3. Send the invoice: GreenPR product/description, invoice ID, customer, plan/scope,
   amount/currency, period, due date and approved payment instructions. Include
   required merchant information; verify the actual receipt display. Do not send
   an invoice until contact and payment details are approved.
4. Confirm settled payment directly in the receiving account. Match invoice,
   customer, amount, currency and period. A screenshot/email is not settlement.
5. Issue with scripts/issue_license.py, using the existing production key and
   a new private output filename. Team: exactly one repository. Enterprise:
   one organization. Match expiry to the paid period. Review the signed payload
   and retain the adjacent payment-reference audit privately.
6. Deliver only the signed license JSON and activation instructions through the
   approved private channel. Never send the signing key or audit sidecar.
7. Customer sets GREENPR_LICENSE_FILE and executes a documented command with
   --commercial in the covered repository. --help is not activation proof.
   A read-only --commercial --scan-only command checks licensing before scanning;
   repository origin must match. Obtain a sanitized acknowledgment of success.
8. Record delivery/activation in the private register. Keep fixture validation
   and real paid-customer activation evidence distinct.

## Renewal, support and cancellation

Use customer-register.template.csv outside source for real records. Review expiry
dates manually and send reminders through the approved channel. Confirm renewal
payment before issuing a replacement with a new filename/paid-through date.
Cancellation stops future invoices and issuance; offline licenses remain valid
until signed expiry. Explain that limit before purchase. Record refunds/disputes
and any corrected license. Support intake collects version, OS, receipt ID and
sanitized error; private code/credentials never belong in a public issue.

The owner handles payment and real fulfillment. Private-form submission and
notification were verified with fixture details on November 6. This does not
prove settled funds or customer activation. Key-backup recovery and any actual
license issuance remain separate operator responsibilities.
