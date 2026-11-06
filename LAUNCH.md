# GreenPR launch targets

Status: **build and local acceptance complete; publication pending**. Launch
scope is free Community download/setup plus paid Team and Enterprise requests
through free GitHub issue forms. Payment confirmation and signed license delivery
are manual. No paid mailbox, application server, database, or live checkout is
required for this launch.

Team is USD 49 per repository/month; Enterprise is USD 899 per GitHub
organization/month. Compute and model-provider usage are separate. GreenPR is
the customer-facing brand; do not change shared account-wide payment branding.

## Finish publication

- [ ] Review and merge the release PR, including `team-license.yml` and
  `enterprise-license.yml` issue forms, then record the exact release commit.
- [ ] Verify the merged [Team form](https://github.com/tech49labs/greenpr/issues/new?template=team-license.yml),
  [Enterprise form](https://github.com/tech49labs/greenpr/issues/new?template=enterprise-license.yml),
  and [general chooser](https://github.com/tech49labs/greenpr/issues/new/choose).
  Forms assign requests to verified account `Mbuso-Harvey`; GitHub notification
  delivery depends on account settings. Do not publish private information,
  payment details, private repository names, license files, or code in requests.
- [ ] Rebuild with `python scripts/build_site.py` and deploy only allowlisted
  `dist/site` to the free Cloudflare Pages project `greenpr-cw0.pages.dev`.
  The local build is complete; the public deployment is pending.
- [ ] Check the deployed URL on desktop/mobile: Community setup, repository
  links, both plan-specific request forms, pricing, policies, keyboard access,
  layout, security headers, and absence of future account/checkout routes.
  Use `python scripts/check_site.py --help` for the current public smoke command.
- [ ] Confirm canonical links and clean Community setup against the published
  release instructions. Record deployment identifier and smoke-test result.

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
| Static site build | Complete locally |
| PR delivery | Mocked regression present; live public PR creation not performed |
| Live payment or checkout | Not performed; automated checkout outside launch scope |
| Release PR merge, public deployment and smoke | Pending |

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

- Release commit and PR merge:
- Final local evidence:
- Verified request forms and assignee:
- Pages deployment identifier and URL:
- Public smoke-test result:
- Manual invoice/private delivery process (before first sale):
- Live PR acceptance (before unattended rollout):
- Rollback: redeploy the last verified static artifact; suspend new paid
  fulfillment if the operator cannot safely complete it.
