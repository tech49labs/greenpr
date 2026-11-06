# GreenPR

Dependency updates checked against your verification command.

GreenPR scans for dependency advisories, updates a package, and runs the same
verification command before and after the change. Changes run in an isolated
Git worktree and can be published as a pull request. Your team reviews and merges.

[Website](https://greenpr-cw0.pages.dev/) ·
[Commercial licensing](https://github.com/tech49labs/greenpr/issues/new/choose)

## Release status

See [launch status](LAUNCH.md) for verified release checks and current limits.
Commercial sales use GitHub request forms, manual invoices, and signed licenses.
The public website does not require a billing server or customer account.

## Run locally

Install Python 3.11+, Git, your project's package manager, and OSV-Scanner v2:
[OSV-Scanner](https://google.github.io/osv-scanner/installation/).
Publishing pull requests additionally requires the authenticated GitHub CLI.
Use a disposable checkout: install scripts and verification commands execute
repository code, and Git cannot roll back their effects outside tracked files.

Install the tool separately from the target repository:

```sh
git clone https://github.com/tech49labs/greenpr.git
cd greenpr
python -m venv .venv
# Activate .venv using your shell's activation script.
python -m pip install -r requirements.txt

cd /path/to/target-repository
python /path/to/greenpr/remediate.py --scan-only
python /path/to/greenpr/remediate.py --test-cmd "npm test" --skip-pr
```

Use absolute paths on Windows, for example:

```powershell
& C:\tools\greenpr\.venv\Scripts\python.exe C:\tools\greenpr\remediate.py --scan-only
```

Choose a command that includes all required checks. GreenPR does not replace a
failed test suite with a passing build. A successful command only demonstrates
what that command actually checked.

Save the project directory and every required gate in a reviewed `.greenpr.toml`
at your repository root. The [setup guide](https://greenpr-cw0.pages.dev/guide.html)
describes test environment defaults, isolated setup and cleanup commands.
Run `python /path/to/greenpr/remediate.py --doctor` to check configured prerequisites
without installing dependencies or changing files. Configuration does not replace
the baseline: the same complete gates must pass before and after an update.
Additional `--test-cmd` arguments add checks to configured gates.

Failed runs retain redacted command output in diagnostic files beside the review
worktree. The `GREENPR_RESULT` receipt identifies the logs, exit codes and timings,
and distinguishes missing configuration, missing dependencies and test failures.

## Commands and boundaries

| Option | Behavior |
| --- | --- |
| `--scan-only` / `--dry-run` | Scan without running baseline tests, changing manifests, or calling a model. |
| `--doctor` | Check `.greenpr.toml` prerequisites without modifying files, even in a dirty checkout. |
| `--test-cmd "command"` | Use this exact trusted shell command for baseline and final verification. |
| `--package NAME --target-version VERSION` | Request an explicit update; provide both options together. |
| `--skip-pr` | Retain a separate review worktree, patch, and JSON receipt without publishing. |
| `--skip-hosted-ci` | Explicitly add `[skip ci]` to the generated commit after local verification; required GitHub checks remain pending and merge protections remain unchanged. |
| `--limit 1` | One package per invocation. Review it before running again. |
| `--ecosystem npm` | Select an ecosystem; use `--scan-only --ecosystem all` for broad discovery. |
| `--project PATH` | Select a nested project within the repository. |
| `--commercial` | Validate a signed commercial license before execution. |
| `--enable-model-repair` | Explicitly permit model-assisted repair and source disclosure to the configured provider. |
| `--verbose` | Show package-manager output. Review before sharing logs. |

Remediation requires a clean Git repository root, including no untracked files.
Scanner failure is an error, not evidence that dependencies are safe. A scan
with no actionable updates is not a security certification: advisories without
a selectable fix may remain. Installs and tests run in a detached worktree;
failed runs retain evidence for inspection. An exclusive repository lock blocks
concurrent GreenPR writers. Do not edit the source concurrently. A successful PR remains subject to review and the
repository's merge protections. Git delivery failures return a nonzero exit.

Adapters cover npm (including workspaces), Python requirements/PEP 621, Go,
Cargo, Maven, Gradle, and .NET. Each persists its supported declaration and
checks the resolved dependency before final verification and an OSV rescan.
Python uses a separate virtual environment. Nested non-npm projects require
`--project`; ambiguous or unsupported dependency declarations fail closed.
See the release record for actual package-manager acceptance results.
Automatic target selection requires a stable newer fix outside all reported
supported ranges; unrecognized advisory ranges are not guessed.

Every remediation run prints `GREENPR_RESULT=<path>` pointing to its JSON
receipt. The retained directory contains the review checkout and `changes.patch`.
Inspect those artifacts before merging; worktree isolation is not an operating
system sandbox for repository install scripts or verification commands.

## Optional model repair

Model calls are disabled unless `--enable-model-repair` is supplied. Merely
having provider credentials in the environment does not enable them. When
enabled, source content and error traces can leave your machine. Use an
approved provider and inspect the resulting diff. Test files, manifests,
untracked files, and paths outside the repository are excluded from repair.

Provider SDKs and credentials are required for the provider you select.
Model routing and third-party models need separate live acceptance; the local
suite does not call paid providers. Never commit API keys. There is no claim
of air-gapped model support or a model accuracy guarantee.

## Local verification

```sh
python -m py_compile remediate.py
python -m unittest discover -s tests -v
git diff --check
```

Opt-in network acceptance (public npm registry and OSV, temporary repository):

```sh
python tests/npm_acceptance.py
```

These checks run locally; GitHub Actions are not required as a release gate.
The composite action is an optional integration. Install a reviewed
OSV-Scanner version on its runner before calling it; the action no longer
downloads an unverified latest binary. Pin the action to a reviewed commit SHA.

## Commercial licensing

| Plan | Price (USD) | License scope |
| --- | --- | --- |
| Community | Free | Public open-source repositories and local personal evaluation |
| Team | $49 / repository / month | One private commercial repository |
| Enterprise | $899 / organization / month | Organization-wide repository licensing |

GreenPR is commercial source-available software under the included [license](LICENSE).
Compute and model-provider usage are separate. Enterprise is a license tier,
not an uptime, compliance, or accuracy guarantee. Support and deployment
commitments must be agreed before purchase.

Commercial onboarding starts with a public GitHub request form. Automated checkout is not live.
[Request Team](https://github.com/tech49labs/greenpr/issues/new?template=team-license.yml) or
[request Enterprise](https://github.com/tech49labs/greenpr/issues/new?template=enterprise-license.yml).
Do not include personal information, payment details, private repository names,
or code in public requests. Requests are assigned to `Mbuso-Harvey` through GitHub
notifications; delivery depends on the account notification settings. Payment
and private license delivery are arranged manually after intake. No private
contact channel is promised by the form.
After manual payment confirmation, GreenPR supplies a signed license scoped to
the purchased repository or GitHub organization and paid period. Set
`GREENPR_LICENSE_FILE` to that file and use `--commercial`. No billing server is
needed for this flow. The commercial self-service backend is maintained privately
and is not deployed.
