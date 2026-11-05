# Safety revision validation — 2026-11-05

This revision replaces the unsafe single-file orchestration with separate CLI, isolation/scanner/dependency primitives, Windows process ownership, and optional Gemini repair modules. It is a draft for review, not a production certification.

## Confirmed locally

- **46 pytest tests passed** on Windows / Python 3.14.7. Covers advisory intersections/maintained branches/uncertain ranges, scanner failures, inventory/rescan checks, noisy child processes, descendant termination, preserved staged/unstaged/untracked work, persistent dependency categories/pins, failed installs, real local Git delivery, failed draft delivery, Gemini route separation/errors, protected source paths/edits, and the composite action's multiword argument handling.
- Real OSV-Scanner **v2.7.0**, downloaded from Google's release and checked against its published SHA-256, scanned a disposable npm fixture. It detected `minimist 1.2.5` / `GHSA-xvch-5gv4-984h`, selected `1.2.6`, installed the original locked project, passed both baseline checks, updated package.json and package-lock.json, passed both checks again, and rescanned with no remaining findings. A verified local branch/commit was retained. The caller's untracked user note and checkout state were unchanged. No remote fixture PR was created.
- A real Python fixture persisted a `requests 2.31.0` → `2.33.0` pin, installed the baseline and upgrade in a private temporary virtual environment, passed a local unittest check before and after, rescanned, and retained a verified local commit without changing the caller's user note. The overall CLI status correctly remained **incomplete / exit 1** because other initial findings were outside the selected package scope. Separate urllib3/idna fixtures had no proven safe target under the conservative range policy; both were retained for manual review without installs or false success.
- Existing Gemini account model-list request succeeded using the saved Windows user API key. `gemini-3.8-flash`, `gemini-3.1-pro-preview`, `gemini-2.5-flash`, and `gemini-2.5-pro` were listed for generateContent. No moving alias is the default route.
- One tiny synthetic structured-edit request per selected model succeeded. Flash used 423 total tokens and Pro 488, including reported thinking tokens. Exact edits were validated against fixture text; arbitrary model output was not executed. This is connectivity/schema verification, not a quality benchmark or a real-project AI repair test.
- Python syntax compilation and Git whitespace checks ran. Source and website copy now describe observed behavior and manual licensing rather than asserting zero hallucinations or production guarantees.

## Verified cause of the reported Gemini errors

The inherited session's `GEMINI_API_KEY` held an OAuth-style token. Google rejected API-key authentication with HTTP 400 / `API_KEY_INVALID`; using that token as a Bearer credential returned HTTP 401 / `ACCESS_TOKEN_TYPE_UNSUPPORTED`. The actual Windows user's saved `GEMINI_API_KEY` was different and successfully listed models and generated both synthetic edits. No key was printed, created, or changed.

The application now distinguishes authentication/quota/model/network failures and offers explicit `--gemini-user-settings` on Windows. It does not silently read the registry at import time. This resolves the configuration handling flaw; an unsupported or expired token still requires a valid configured credential.

## Stage policy

The prior implementation had migration analysis plus two healing attempts, not a literal Stage 4. Its generic model override assigned the same model to both repair tiers. The new documented flow uses deterministic scan/update/verification, Flash for stage 3 repair, and a distinct Pro model for stage 4 only after Flash's patch still fails tests. Timeout, baseline failure, or provider authentication/quota errors do not trigger paid escalation. Every edit is followed by the complete configured checks and a final vulnerability rescan. No model name alone proves a fix is better.

Google references: [model identifiers](https://ai.google.dev/gemini-api/docs/models), [Gemini 3 guide](https://ai.google.dev/gemini-api/docs/gemini-3), [model lifecycle](https://ai.google.dev/gemini-api/docs/deprecations). OSV references: [output and exit codes](https://google.github.io/osv-scanner/output/), [advisory schema](https://ossf.github.io/osv-schema/). Live account listing, not public availability alone, was used for the selected routes.

## Remaining release gates and limitations

1. Review the substantial orchestration change and compatibility changes before merge. The old v1 tag is unchanged. There has been no production deployment or merge.
2. CI adds Ubuntu/Windows × Python 3.11/3.14. Hosted results must be checked on the draft PR; local results do not substitute for those runners. Publication was blocked by automatic approval review pending explicit user approval of the public branch push/draft PR, so hosted CI has not run.
3. npm and a plain pinned Python requirement received live package/scanner checks. Other package managers have adapter coverage only; a representative real project matrix is still needed. Shared-workspace locks, transitive-only/peer dependencies, complex Python locks/requirements, Go, Rust, Java, .NET, and submodules are explicitly refused for auto-repair rather than silently mishandled. This narrows previously advertised coverage.
4. A successful fix is a separate branch from the captured base. Multiple fixes have not been tested together. Branch protection, real consumer-repository draft-PR permissions, ambiguous network delivery outcomes, and concurrent changes need deployment-environment testing. Local/failed delivery paths have regression coverage.
5. Gemini smoke tests use tiny synthetic code. Real migrations, quality/cost comparisons between Flash and Pro, rate-limit behavior, large projects, and extended reasoning are not certified. Explicit opt-in sends source and diagnostics to Google; project owners must choose suitable data and test coverage. Providers can change availability or pricing.
6. Worktrees protect the caller's files from GreenPR rollback; they do not sandbox malicious package scripts or tests. Node lifecycle scripts are disabled, but explicitly configured tests and package tooling still execute trusted code. No strong adversarial isolation is claimed.
7. Security conclusions depend on OSV extraction, advisory completeness, and scanner configuration. Unknown/unfixed findings and failed scans never count as clean. A passing check or clean scan is not proof of production security.
8. Paid offers remain manually contracted licenses. No checkout, activation, subscription lifecycle, or technical tier enforcement was introduced or tested. Decide and implement those separately if self-service SaaS billing is intended. Enterprise air-gap/model-hosting/SLA claims were removed from default capabilities.
