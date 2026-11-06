# GreenPR

Dependency remediation in isolated Git worktrees, with baseline checks, post-update checks, an OSV rescan, and reviewable evidence. Passing configured checks is not a production safety guarantee.

## Start with your own project

Install GreenPR separately from your target project. Requirements: Python 3.11+, Git, OSV-Scanner v2, and the project's package manager. GitHub CLI authentication and push permission are needed only for draft PR delivery. Use trusted repositories: worktrees isolate file changes but do not sandbox package managers or test code.

```bash
git clone https://github.com/tech49labs/greenpr.git /path/to/greenpr
python -m venv /path/to/greenpr-env
# Activate that environment using your platform's normal command.
python -m pip install -r /path/to/greenpr/requirements.txt
# Install OSV-Scanner v2 from its official release for your OS/architecture.

# Target YOUR project, not the GreenPR source directory:
python /path/to/greenpr/greenpr_cli.py --repo /path/to/your-project --preflight
python /path/to/greenpr/greenpr_cli.py --repo /path/to/your-project --dry-run
python /path/to/greenpr/greenpr_cli.py --repo /path/to/your-project --skip-pr
```

This safety revision is not yet released as `v1`; use a reviewed commit when testing. Do not assume an old tag contains these fixes.

`--preflight` checks prerequisites without installing dependencies or executing project code. `--dry-run` scans **committed HEAD**, reporting planned and blocked findings without applying them. A dry run exits **2** when vulnerabilities are found.

Existing staged, unstaged, and untracked work is excluded and preserved. Every package starts from the same captured HEAD in a temporary worktree. Failed attempts are discarded there. Successful attempts become independent local branches (`--skip-pr`) or **draft PRs**. The caller's current branch is never switched or reset. Inspect local commits using `git show <commit>` and cherry-pick only after review. Combining fixes requires another integration test run.

## Automatic repair coverage

OSV-Scanner recursively inventories supported manifests, including nested projects. Scanning coverage is broader than automatic repair coverage.

| Dependency form | Automatic update policy |
| --- | --- |
| Node direct dependencies and declared workspaces | Preserve dependencies/devDependencies/optionalDependencies; update the unique owner manifest and shared lockfile together. npm, pnpm, Yarn classic, and Bun require installed tooling; supported Windows wrappers use their Node entry point. |
| Transitive Node dependencies | Add a root override/resolution without promoting the package to a direct dependency. Existing override policies require manual review; pnpm uses an existing pnpm-workspace.yaml without an override block. |
| Plain Python requirements.txt | Exact direct pins only; persist the pin and install into a private temporary virtual environment. Include test dependencies in that file. |
| Ambiguous/multiple workspace owners, peer, local/aliased declarations, multiple-installed-version findings | Report for coordinated manual repair; never silently select the first matching owner. |
| Poetry/uv-managed Python, hashes/includes/conditional requirements, Go, Rust, Java, .NET, submodules | Automatic repair is not verified in this safety revision. Findings remain visible; unsupported operations fail closed. |

Node installation disables lifecycle scripts. Projects requiring them may fail baseline checks and need manual setup. Node auto-detection runs **both** typecheck and test when present, recognizes test:unit/test:ci when test is absent, and uses build only when no test/typecheck gate is defined. It never replaces a failing required check with a weaker passing one. Shared-workspace installs run at the lockfile root; required root checks and available owner checks run in their respective directories. Python defaults to the private environment's `python -m pytest`. Supply a meaningful custom check if needed; repeat `--test-cmd` to require several checks. Custom Node workspace commands run at the lockfile root. Do not put secrets in commands; evidence stores custom-command hashes rather than raw text.

```bash
python /path/to/greenpr/greenpr_cli.py --repo /path/to/your-project --skip-pr \
  --test-cmd "npm run typecheck" --test-cmd "npm test" --timeout 300
```

## Evidence and status

Every run prints a JSON report path outside the target repository. `--report` accepts a **new** external file. Reports include base commit, scope, all findings (including no proven fix), checks and exit codes, rescan evidence, retained commits/branches, and a PR URL only when confirmed. Raw logs are not persisted.

- **0:** preflight passed, no known findings, or all independent remediations prepared. Read the distinct `status` value.
- **1:** failure, blocked/partial/deferred work, scanner error, failed checks/rescan, or unsuccessful/uncertain delivery.
- **2:** dry run found vulnerabilities, or invalid arguments.

`--limit`, `--ecosystem`, and `--package` restrict attempts, not the reported inventory. Deferred findings prevent complete success. `--target-version` must match the proven advisory-derived target; it cannot bypass scanning. Unfixed advisories, unsupported version ordering, prereleases, and uncertain ranges require manual review. Rescanning must observe the requested version, no remaining advisory for that package, and no new advisory identifiers. Scanner configuration and database coverage still limit what can be detected.

`--scan-only` is retained as an alias for `--dry-run`. Workspace ownership follows declared npm/Yarn/Bun workspaces or pnpm package patterns (including exclusions), not an unrestricted search through unrelated projects. New declarations pin the exact validated target. Complex workspace glob forms and existing transitive override policies are refused rather than overwritten. Installation refreshes the actual dependencies used by checks, not only the lockfile.

Rescans must retain every previously inventoried manifest/ecosystem/package identity, including packages without advisories. An advisory cannot silently disappear while the affected version remains inventoried. A legitimate dependency removal, manifest rename, or advisory withdrawal therefore requires manual review until separate evidence can distinguish it from lost scanner coverage.

## GitHub Actions

The action supports Linux x64 and installs a pinned, SHA-256-verified OSV scanner. Set up your project's runtime/package manager first. Use manual/scheduled triggers on trusted branches, not untrusted pull-request code.

```yaml
name: GreenPR review
on:
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      # Replace after reviewing this revision:
      - uses: tech49labs/greenpr@REVIEWED_COMMIT_SHA
        with:
          dry_run: 'true'
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

A finding-only dry run exits 2 and marks the action unsuccessful while retaining its report. For draft delivery set `dry_run: 'false'` and enable repository settings allowing Actions-created PRs. No forced push, merge, or deployment occurs. A lost push/PR response may be uncertain; inspect the retained branch and remote before retrying.

## Optional Gemini repair and stages

The deterministic core needs no model key. This revision uses **Gemini only**, and does not read or use OpenAI credentials. Enable repair explicitly with `--enable-healing`; this sends bounded source files and failing-test diagnostics to Google and may incur provider charges. There are at most two repair calls per package attempt. Use `--limit` to cap attempts.

1. Scan and select a proven candidate without an LLM.
2. Install and test the baseline, then update persistent dependency files and verify without an LLM.
3. If verification fails (not a timeout), request one bounded **Flash** source repair and rerun every check.
4. Only if the Flash repair still fails verification, request one **Pro** repair and rerun every check. Then rescan before delivery.

This makes the previous Flash-first/Pro-fallback intent explicit. The previous code had no literal Stage 4 and a single model override collapsed both routes into one model. Separate settings now preserve distinct routes. Pro is an alternative escalation, not proof of higher quality; evaluate both against your real failure cases.

`--check-models` verifies the configured models against Google's account model list without generating content or executing project code. Defaults select `gemini-3.8-flash` and `gemini-3.1-pro-preview` if listed; the older `gemini-2.5-flash` / `gemini-2.5-pro` pair is eligible only when listed. Configure `--flash-model` / `--pro-model` or `GREENPR_FLASH_MODEL` / `GREENPR_PRO_MODEL` to pin your choices. Legacy `GREENPR_MODEL` changes Flash only. Explicit unavailable models fail rather than silently falling back; moving `latest` aliases are not defaults.

Use `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) for an API key. Standard OAuth can be explicitly configured with `GOOGLE_ACCESS_TOKEN` and, where needed, `GOOGLE_CLOUD_PROJECT`; an unsupported token fails with a redacted provider reason. A legacy OAuth token in `GEMINI_API_KEY` uses Bearer authentication rather than the wrong API-key header. No credential is loaded at import time or silently replaced from Windows settings.

On Windows, `--gemini-user-settings` explicitly reads the current user's saved `GEMINI_API_KEY`, useful when a stale session contains a different credential. It never rewrites your environment or prints the key. Example:

```bash
python /path/to/greenpr/remediate.py --check-models --gemini-user-settings
python /path/to/greenpr/remediate.py --repo /path/to/project --skip-pr --enable-healing \
  --flash-model gemini-3.8-flash --pro-model gemini-3.1-pro-preview --limit 1
```

The action accepts `gemini_api_key`, `enable_healing: 'true'`, `flash_model`, and `pro_model`. The legacy `api_key` input now means Gemini only. Repair cannot modify tests, configuration, or dependency manifests: only tracked source candidates from diagnostics, resolved inside the subproject, receive validated exact replacements. No full-file truncation/rewrite or shell command from the model is executed. Invalid/blocked/token-limited responses, authentication errors, and quota errors stop the attempt without automatic paid retries.

A provider key is not a GreenPR commercial license. Provider charges are separate. Account model listing is not a guarantee of quota or quality; see the precise live smoke-test scope in VALIDATION.md.

## Commercial licensing

GreenPR uses the [Tech49 Labs Commercial & Fair-Source License](LICENSE). It is source-available, not itself OSI-approved open-source software.

| Offer | Published price | Current delivery |
| --- | --- | --- |
| Community | $0 | Personal local evaluation and public OSI-licensed repository use under LICENSE. |
| Team | $49/repository/month | Contact licensing@tech49labs.com for a private-repository commercial agreement. |
| Enterprise | $899/organization/month | Contact licensing@tech49labs.com to agree organization scope and support terms. |

Sales are **manual**. This repository has no checkout, account system, activation key, automatic renewal/cancellation, billing portal, or technical tier/subproject enforcement. Confirm a written agreement before commercial private-repository use. All offers distribute the same code; distinctions are contractual permission and agreed support, not tested feature gates. Air-gapped operation, self-hosted inference, and SLAs require separate validation and written agreement; the default action does not guarantee them.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Regression tests exercise real temporary Git worktrees, preservation of existing edits, process output/timeouts, advisory ranges, scanner errors, persistent manifests, and delivery failures. External services and inference are mocked unless separately documented. See [VALIDATION.md](VALIDATION.md) for exact checks and remaining release gates.
