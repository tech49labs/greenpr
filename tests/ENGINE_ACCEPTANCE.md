# GreenPR engine acceptance evidence

Native acceptance: pre-publication engine implementation, November 2026.
The final public candidate must be recorded in the release record.
This record is local execution evidence, not a hosted deployment or live pull-request receipt.
The release owner must record the final commit and rerun the regression suite after integration.

## Completed native acceptance

| Command | Actual behavior verified | Result |
| --- | --- | --- |
| `python tests/npm_acceptance.py` | Root npm is-number 6.0.0 to 7.0.0; automatic OSV minimist 1.2.5 to 1.2.6; two npm workspaces updated together; failing typecheck rejects update despite passing tests | Four scenarios passed, exit 0; repeated successfully after integration fixes |
| `python tests/polyglot_acceptance.py --ecosystem python` | colorama 0.4.5 to 0.4.6 in a separate virtual environment; persisted requirement; installed version; behavior; fresh OSV scan; source checkout and host Python distribution unchanged | Passed, exit 0 |
| `python tests/polyglot_acceptance.py --ecosystem go` | uuid v1.3.0 to v1.6.0; persisted go.mod and go.sum; native resolved module; baseline and updated behavior; fresh OSV scan; original checkout unchanged | Passed, exit 0 |
| `python tests/polyglot_acceptance.py --ecosystem rust` (container) | itoa 1.0.10 to 1.0.15; persisted Cargo manifest and checksum lockfile; cargo metadata; baseline and updated behavioral test; fresh OSV scan; original checkout unchanged | Passed, exit 0 |
| `python tests/polyglot_acceptance.py --ecosystem maven` (container) | commons-lang3 3.17.0 to 3.18.0; persisted POM; native resolved dependency tree; JUnit baseline and updated behavior; fresh OSV scan; original checkout unchanged | Passed, exit 0 |
| `python tests/polyglot_acceptance.py --ecosystem dotnet` (container) | Newtonsoft.Json 13.0.2 to 13.0.3; persisted PackageReference and lock content hash; baseline and updated native runtime behavior; fresh OSV scan; original checkout unchanged | Passed, exit 0 |
| `python tests/polyglot_acceptance.py --ecosystem gradle` (container) | commons-lang3 3.17.0 to 3.18.0; persisted declaration and newly created reviewable lockfile; baseline and updated JUnit behavior; fresh OSV scan; original checkout unchanged | Passed, exit 0 |

Final integration result reported by the release owner: `python -m unittest discover -s tests -p 'test_*.py' -q` passed all 46 tests on fresh Windows Python 3.11 and Linux Python 3.14 environments with cryptography 50. The Linux release image is `sha256:c3fc471e90811408f93a30a488338b714483c6b3981ce9ae97ba9963872fce21`. These final regression results supersede the earlier 45-test run.

After the constrained-Python scanner correction, `.release311/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -q` passed **51 tests** on Windows Python 3.11. The complete 51-test suite also passed from the separated public checkout on Linux Python 3.14 using the release image above. Those regressions execute pip's real dry-run resolver against local binary-wheel fixtures: complete transitive pins, an unpinned transitive refusal, conflicting constraints, path/URL refusal, and preserving another ecosystem's findings while replacing only proven Python sources.

The actual npm minimist advisory flow was repeated through the corrected shared scanner: detected `GHSA-xvch-5gv4-984h` at 1.2.5, updated to 1.2.6, passed behavioral tests and the post-update rescan, preserved the original checkout, and exited 0.

The resolved CLI dependency scan covered **33 package entries with zero reported vulnerabilities**. The separated public checkout also passed GreenPR scan-only and a raw scanner-result assertion: 33 scanned packages, zero vulnerable packages. Resolution used pip dry-run, ignore-installed, and binary-only downloads; every resolved package had to match an exact tracked constraint. Other ecosystem sources keep normal transitive scanning.

## Remaining acceptance

All seven manager paths above have completed native acceptance. uv and Poetry manifest paths are implemented but have no completed native acceptance receipt. No hosted pull-request delivery or model-provider call is included in these results.

Native manager acceptance used `greenpr-acceptance:local`, image ID `sha256:24629111859acdb1da2dfcfa038385554f0358d43d95685852a71e1fa2b3cf51`, with the source repository mounted read-only at `/workspace`. Each scenario created disposable Git fixture repositories under container `/tmp`. That image contained the earlier cryptography 49 dependency; the final 46-test regression above used the updated cryptography 50 release environment. The native manager runs and final regression are distinct evidence.

The exact container command was run independently for each of `rust`, `maven`, `gradle`, and `dotnet`:

```powershell
docker run --rm --mount "type=bind,source=/absolute/path/to/greenpr,target=/workspace,readonly" greenpr-acceptance:local python tests/polyglot_acceptance.py --ecosystem rust
```

## Contract and boundaries

- Mutating execution requires a clean Git checkout and runs in a detached worktree with an exclusive repository lock. Original checkout files and installed dependencies are not used for execution.
- `--skip-pr` retains the worktree for review. It does not copy updates into the source checkout. `GREENPR_RESULT` identifies a JSON receipt; the run directory contains `result.json` and `changes.patch`.
- Receipt fields include run ID, base SHA, original repository, worktree, status, finish time, original-head equality, patch SHA256, updates, verification command, and baseline duration where available.
- Every configured gate is required. No weaker fallback follows a failed gate. Successful dependency updates require native target validation and a fresh OSV scan with no remaining reported vulnerability for the target.
- npm supports direct root and declared-workspace dependencies with package-lock v2/v3. Transitive-only, peer-only, and non-npm package managers fail explicitly.
- Non-npm nested projects require `--project`; cross-project mutation is refused before dependency installation. `--ecosystem all` is scan-only. Canonical selectors are npm, pypi, go, crates.io, maven, and nuget.
- Python requirements retain extras, environment markers, and comments. PEP621 extras, markers, and URL declarations are refused rather than silently simplified.
- Native manifest adapters reject ambiguous forms. These tests do not establish support for every Maven parent/BOM, Gradle catalog, Cargo workspace, Poetry source, or centrally managed NuGet layout.
- Model repair is opt-in. No provider calls, live PR creation, or GitHub Actions runs were used for this evidence.
- Commercial execution supports pinned-key Ed25519 offline licenses via `GREENPR_LICENSE_FILE` and explicit `--commercial`. Tests use generated test keys; no paid license was issued. Optional online verification is not a hosted launch dependency.
