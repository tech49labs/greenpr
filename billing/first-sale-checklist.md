# First paid customer: operator checklist

Use the existing [manual sales process](manual-sales.md). No checkout integration,
customer account, hosted backend, automated charge or paid mailbox is needed.
Use the [fulfillment templates](fulfillment-templates.md) for scope confirmation,
invoice fields, delivery, renewal and support; replace placeholders privately.
Keep the operator's destination inbox and customer register outside the repository.
Publish only an approved GreenPR contact address after a send/reply privacy test.

## Ready before collecting money

- Confirm the Team/Enterprise request reaches the assigned operator. Label
  rehearsals TEST; never put customer identity, scope, keys or licenses in issues.
- Choose a free customer-facing alias or a separate free inbox. A sender display
  name does not hide its underlying address. An alias must preserve privacy on
  replies, attachments, signatures, quoted headers and bounces. Verify both ends
  using controlled addresses before publishing it. Do not publish the internal
  operator inbox. SimpleLogin Free supports replies but not initiating new
  conversations; have customers initiate contact if that option is selected.
- Approve an existing manual payment method. A PDF invoice plus bank transfer is
  possible subject to the bank's fees/currency support. PayPal invoices are a
  separate optional method with transaction fees. There is no payment integration
  in this product. Verify actual customer-facing payee/receipt information and
  the agreed currency before use; a brand display name alone is insufficient.
- Record signed-key readiness without exporting secrets. The November 6 read-only
  check found a matching Ed25519 key and restricted file access; a domain-separated
  non-license challenge verified. This does not establish backup recovery.
  Keep an owner-approved protected backup outside source, and verify a restored
  copy against the released public key before relying on it. Do not create a
  real production license as a test artifact.

## Request to activation

1. Acknowledge publicly: "Thanks for your GreenPR request. Please contact us at
   [APPROVED PUBLIC CONTACT] with reference [ISSUE NUMBER]. Do not post private
   scope, personal details, payment evidence or keys here."
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

Owner sign-offs still needed: public contact/privacy test, payment method/payee
display, key-backup recovery, intake notification acknowledgment, and the actual
first paid fulfillment. This checklist is preparation, not a claim of settlement
or customer activation.

References: [SimpleLogin Free](https://simplelogin.io/pricing/),
[Proton free inbox](https://proton.me/support/create-a-free-email-account-address),
[PayPal invoicing](https://www.paypal.com/ca/business/accept-payments/invoice).
