# GreenPR launch record

Status: **published on 2026-11-05 (America/Toronto)** at
https://greenpr-cw0.pages.dev/. Launch
scope is free Community download/setup plus paid Team and Enterprise requests
through free GitHub issue forms. Payment confirmation and signed license delivery
are manual. No paid mailbox, application server, database, or live checkout is
required for this launch.

Team is USD 49 per repository/month; Enterprise is USD 899 per GitHub
organization/month. Compute and model-provider usage are separate. GreenPR is
the customer-facing brand; do not change shared account-wide payment branding.

## Publication verification

- Release [PR #2](https://github.com/tech49labs/greenpr/pull/2) merged as
  `da1a1cafa58b86c39c752803f915242cd116ca4a`.
- Both plan-specific GitHub issue form files are present on the default branch.
  `Mbuso-Harvey` is an eligible assignee and is configured in both forms.
  A signed-out browser reaches GitHub sign-in with the correct Team form return URL.
  No customer request was submitted; notification delivery is not claimed tested.
- Deployed only the allowlisted `dist/site` artifact to Cloudflare Pages.
  Deployment: https://4c61da16.greenpr-cw0.pages.dev/.
- `python scripts/check_site.py --url https://greenpr-cw0.pages.dev` passed:
  all seven served files match local SHA256 digests; security headers and both
  plan links pass; `/app/`, `/api/license`, `/backend/app.py`, `/.env`, and
  `/_headers` return 404.
- Production desktop rendering and pricing links were inspected in a browser.
  The matching build was checked at a 390px mobile viewport without horizontal overflow.
- GitHub's repository homepage points to the live Cloudflare URL. The outdated
  GitHub Pages publication was disabled after the new site passed verification.
- Fresh Windows Python 3.11 installation and Linux Python 3.14 checks passed.

There is no mailbox/DNS launch blocker: public intake now uses GitHub. Private
payment and license delivery arrangements are established manually after intake;
the public forms do not promise an already configured private contact channel.

## Completed acceptance

These results establish local/fixture acceptance, not live customer delivery.

| Check | Recorded result |
| --- | --- |
| Root regression suite | 51 passed on Windows Python 3.11 and Linux Python 3.14 with cryptography 50.0.0 |
| Native package-manager acceptance | All seven paths passed: npm, Python, Go, Rust, Maven, Gradle, .NET |
| npm scenarios | Four passed |
| Manual license issuer | 9 passed; actual CLI with ephemeral signing key |
| OSV resolved dependency scan | Zero reported vulnerabilities; 33 CLI package entries |
| Static site build | Published and byte-matched against the production responses |
| PR delivery | Mocked regression present; live public PR creation not performed |
| Live payment or checkout | Not performed; automated checkout outside launch scope |
| Release PR merge, public deployment and smoke | Complete; see publication verification above |

See [DEPENDENCIES.md](DEPENDENCIES.md) for pinned versions, scan method and
platform scope. Run local checks against the final candidate when implementation
changes invalidate existing evidence. Do not start paid GitHub Actions as a
substitute for local acceptance.

## Operational follow-up

Before the first sale, use [billing/manual-sales.md](billing/manual-sales.md) to
verify the authorized invoice process and agree a private fulfillment channel.
Do not collect sensitive details or deliver signed licenses on public issues.
Payment-process verification is not a gate for publishing a request website.

Before unattended PR rollout, perform an authorized live GitHub delivery check:
scan, update, verification, branch push, PR creation, and changed-file review.
Mocked delivery regressions do not establish live delivery. Do not create a new
public repository solely to launch the static website.

`billing/catalog.json` is a manual pricing reference, not proof of provisioned
Stripe resources. The commercial self-service backend is maintained privately
and is not deployed. Automated accounts and checkout are outside this public
release.

## Release record

- Release commit and PR merge: `da1a1cafa58b86c39c752803f915242cd116ca4a`, PR #2.
- Final local evidence: 51 regressions passed; seven native manager paths passed; GreenPR public self-scan verified 33 packages with zero reported vulnerable packages.
- Verified request forms and assignee: `team-license.yml`, `enterprise-license.yml`; `Mbuso-Harvey`. No submission or notification-delivery test.
- Pages deployment identifier and URL: `4c61da16`, https://4c61da16.greenpr-cw0.pages.dev/.
- Public smoke-test result: all seven assets and five absent-route checks passed.
- Manual invoice/private delivery process (before first sale): operator follow-up, not yet exercised with a real customer.
- Live engine-generated PR acceptance (before unattended rollout): not performed; release PR publication is separate evidence.
- Rollback: redeploy the last verified static artifact; suspend new paid
  fulfillment if the operator cannot safely complete it.
