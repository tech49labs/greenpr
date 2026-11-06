"""CLI orchestration; reporting is separate from the caller's repository."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

from greenpr_core import (CommandResult, GreenPRError, git, isolated_checkout, plan_update, preflight,
                          repository_state, run_remediation, scan, finding_key)


def parser():
    p = argparse.ArgumentParser(description="GreenPR: isolated dependency remediation with reviewable evidence")
    p.add_argument("--repo", type=Path, default=Path.cwd(), help="Target Git repository root")
    p.add_argument("--preflight", action="store_true", help="Read-only prerequisite checks; no scan or package execution")
    p.add_argument("--dry-run", "--scan-only", dest="dry_run", action="store_true", help="Scan committed HEAD and report plans; do not install, test, or deliver")
    p.add_argument("--skip-pr", action="store_true", help="Keep verified commits on new local branches; leave caller checkout unchanged")
    p.add_argument("--test-cmd", action="append", default=[], help="Trusted shell test command; repeat for multiple required checks")
    p.add_argument("--timeout", type=int, default=180, help="Timeout in seconds for each subprocess")
    p.add_argument("--scanner", default="osv-scanner", help="OSV-Scanner v2 executable")
    p.add_argument("--limit", type=int, help="Maximum number of independent remediation attempts")
    p.add_argument("--ecosystem", default="all", help="Limit remediation scope; other findings remain in report")
    p.add_argument("--package", help="Select an existing scanner finding; does not bypass scanning")
    p.add_argument("--target-version", help="Require the scanner-derived safe target to match this version")
    p.add_argument("--report", type=Path, help="New JSON report path OUTSIDE the target repository")
    p.add_argument("--enable-healing", action="store_true", help="Opt in to sending bounded source/diagnostics to Gemini for repair")
    p.add_argument("--check-models", action="store_true", help="List/validate configured Gemini routes without inference or project execution")
    p.add_argument("--flash-model", help="Explicit available Gemini model for stage 3 repair")
    p.add_argument("--pro-model", help="Distinct available Gemini model for stage 4 escalation")
    p.add_argument("--gemini-user-settings", action="store_true", help="Explicitly read this Windows user's saved GEMINI_API_KEY instead of session credentials")
    return p


def main(argv=None, healer=None):
    args = parser().parse_args(argv)
    root = args.repo.resolve()
    if args.timeout <= 0 or (args.limit is not None and args.limit <= 0):
        parser().error("timeout and limit must be positive")
    if args.target_version and not args.package:
        parser().error("--target-version requires --package")
    report_path = args.report.resolve() if args.report else Path(tempfile.mkdtemp(prefix="greenpr-report-")) / "report.json"
    if report_path.is_relative_to(root) or report_path.exists():
        parser().error("--report must be a new file outside the target repository")
    report = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "scope": "committed HEAD only; existing local changes excluded",
              "results": [], "limitations": ["Passing configured checks is not a production safety guarantee",
                                               "Git worktrees isolate file changes, not execution of untrusted project code"]}
    exit_code = 1
    try:
        if args.enable_healing or args.check_models:
            from gemini_provider import GeminiClient, GeminiConfig, GeminiHealer
            client = GeminiClient(GeminiConfig.from_environment(args.flash_model, args.pro_model, args.gemini_user_settings))
            report["models"] = client.resolve_models()
            if args.enable_healing:
                healer = GeminiHealer(client)
        if args.check_models:
            report["status"] = "gemini_routes_available"
            exit_code = 0
        else:
            state = preflight(root, scanner=args.scanner, delivery=not (args.skip_pr or args.dry_run or args.preflight))
            report["base_commit"] = state["head"]
            report["base_branch"] = state["branch"]
            report["local_changes_excluded"] = bool(state["status"])
            if args.preflight:
                report["status"] = "preflight_passed"
                report["limitations"].append("Package tools, installs, tests, scanning, and provider connectivity were not exercised")
                exit_code = 0
            else:
                with isolated_checkout(root, state["head"]) as (work, temp):
                    inventory = scan(work, args.scanner, args.timeout)
                    report["scan"] = inventory.evidence
                    report["packages_scanned"] = len(inventory.packages)
                    report["findings"] = [{k: v for k, v in f.items() if k != "advisories"} for f in inventory.findings]
                    selected = [f for f in inventory.findings
                                if (args.ecosystem == "all" or f["ecosystem"] == args.ecosystem.lower())
                                and (not args.package or f["package"] == args.package)]
                    grouped = {}
                    for item in selected:
                        key = finding_key(item)
                        if key in grouped:
                            grouped[key] = None  # Multiple installed versions need a coordinated update.
                        else:
                            grouped[key] = item
                    selected = [f for f in grouped.values() if f is not None]
                    report["ambiguous_packages"] = [list(k) for k, v in grouped.items() if v is None]
                    if args.package and not selected:
                        raise GreenPRError("Requested package has no unambiguous finding in the scan")
                    if args.limit:
                        selected = selected[:args.limit]
                    if args.target_version and any(f["target_version"] != args.target_version for f in selected):
                        raise GreenPRError("Requested version differs from the proven scanner-derived target")
                    report["deferred_findings"] = len(inventory.findings) - len(selected)
                    if args.dry_run:
                        for item in selected:
                            entry = {"package": item["package"], "manifest": item["manifest_path"], "target": item["target_version"]}
                            try:
                                plan = plan_update(work, item, temp, args.test_cmd)
                                entry.update(status="planned", commands=plan.commands,
                                             checks=[CommandResult(c, 0).evidence()["command"] for c in plan.tests])
                            except (GreenPRError, OSError, ValueError) as exc:
                                entry.update(status="blocked", error=str(exc) if isinstance(exc, GreenPRError) else type(exc).__name__)
                            report["results"].append(entry)
                if not args.dry_run:
                    for item in selected:
                        report["results"].append(run_remediation(root, item, inventory, state,
                            scanner=args.scanner, timeout=args.timeout, tests=args.test_cmd,
                            skip_pr=args.skip_pr, healer=healer))
                if repository_state(root) != state:
                    raise GreenPRError("Caller checkout changed during execution; inspect concurrent activity")
                if not inventory.findings:
                    report["status"] = "no_known_vulnerabilities"
                    exit_code = 0
                elif args.dry_run:
                    report["status"] = "findings_reported"
                    exit_code = 2
                elif (not report["deferred_findings"] and all(r["status"] in ("local_verified", "draft_pr_created") for r in report["results"])):
                    report["status"] = "remediations_prepared"
                    report["limitations"].append("Independent branches have not been merged or tested together")
                    exit_code = 0
                else:
                    report["status"] = "incomplete"
                    exit_code = 1
    except (GreenPRError, OSError, ValueError) as exc:
        report["error"] = str(exc) if isinstance(exc, GreenPRError) else f"Local operation failed: {type(exc).__name__}"
    finally:
        report["exit_code"] = exit_code
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidental overwrites or symlink-target writes.
            with report_path.open("x", encoding="utf-8") as output:
                json.dump(report, output, indent=2)
                output.write("\n")
            print(f"GreenPR: {report['status']}. Evidence: {report_path}")
        except OSError:
            print("GreenPR: could not write evidence report", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
