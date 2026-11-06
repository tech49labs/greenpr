# Free customer installation acceptance — November 6, 2026

Decision: Community installation, scanning and verified local dependency updates
passed on the tested Windows x64 and Linux x64 environments. No GreenPR account,
model API key, commercial license or payment details were supplied. The manual
plan-enquiry flow remains separate and unchanged.

Both runs cloned public commit `87bdd5a41b71bfdd81dbef62592273a9822152fc`
without a Git credential helper, into new folders whose names contained spaces.
Each downloaded the pinned scanner and verified its SHA256, created a fresh
virtual environment without inherited site packages, and installed the published
`requirements.txt` and adjacent constraints. Existing developer environments
were not used as the installed customer runtime.

| Actual check | Windows x64 / Python 3.11.9 | Linux x64 / Python 3.14.10 |
| --- | --- | --- |
| Public clone and exact candidate identity | Passed | Passed |
| Fresh OSV-Scanner 2.7.0 download/checksum | Passed | Passed |
| Fresh venv and pinned requirements install | Passed | Passed |
| pip dependency consistency check | No broken requirements | No broken requirements |
| CLI help from the new installation | Passed | Passed |
| Full regression suite | 112/112 | 112/112 |
| Real npm acceptance | 4/4 scenarios | 4/4 scenarios |
| Real Python requirement update | Passed | Passed |
| Real Go, Cargo, Maven, Gradle and .NET updates | Not rerun on this platform | All five passed |
| Free scan of 33 constrained CLI packages | No actionable updates | No actionable updates |
| Source checkout preservation | Clean, unchanged | Clean, unchanged |
| PowerShell invocation with quoted paths containing spaces | Passed | Not applicable |

The four npm scenarios exercise a direct update, an advisory-selected minimist
update, two npm workspaces, and a failing typecheck. The rejection case passes
acceptance only when GreenPR refuses the update despite a passing test command.
No required verification gate was weakened.

Real dependency-manager checks verify persisted declarations/locks, actual
installed or resolved versions, behavioral checks before and after the update,
fresh target-advisory scans and source-checkout preservation. The Python case
also verifies that the host Python distribution was not changed. All customer
acceptance commands used `--skip-pr`; they published no branches or PRs.

Local operator evidence lives under ignored `dist/fresh-windows/` and
`dist/fresh-linux/`. Each `result.json` records the candidate, phase exit codes,
durations and SHA256 digests of the retained logs. Both result files report
`passed`. These receipts are separate from previous real PR-delivery evidence.

The associated release changes only installation instructions and this evidence;
runner code, runtime dependencies and regression tests remain identical to the
tested public candidate. The first-run guide uses explicit virtual-environment
paths, requires no shell activation, and documents checksum-verified scanner
installation and project prerequisites.

## Scope of the readiness claim

This establishes a working free installation and exercised dependency-update
paths, not universal compatibility with every computer or repository. Projects
still need their own package manager, supported manifests, test dependencies,
services and passing verification commands. A failed baseline or missing
prerequisite is reported as a failure, not a successful remediation. Other OS
and architecture combinations require their own checks.

No paid model inference, new hosted service, customer account, billing backend
or hosted CI run was used. Optional live AI repair remains experimental and is
not required for any free workflow exercised here. A clean advisory scan is not
a general security certification.
