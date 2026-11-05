# GreenPR

> **Autonomous Zero-Hallucination Dependency Remediation Engine.**  
> Automatically detects security vulnerabilities across monorepo trees, repairs breaking interface signatures, and enforces a strict Exit Code 0 test gate before opening a Pull Request.

Developed by **tech49labs** — [Website & Documentation](https://tech49labs.github.io/greenpr)

---

## Key Capabilities

* **Deterministic Verification Gate**: A Pull Request is ONLY published if your test harness (`pnpm typecheck`, `pytest`, `cargo test`, `go test`) exits with strict **Exit Code 0**. Zero broken builds.
* **Autonomous Polyglot Monorepo Routing**: Automatically scans nested submodules across Python, TypeScript/Node.js, Go, Rust, Java, and .NET. Runs subproject-native package managers (`pnpm`, `uv`, `cargo`, `go`) in their respective directories.
* **Semver-Aware Target Resolution**: Never downgrades versions across unmaintained branches or jumps to experimental pre-releases. Selects the minimal stable release satisfying the advisory.
* **Proprietary Native Code Healing**: Multi-tier syntax repair automatically resolves updated import paths, altered constructor signatures, and changed method callsites when breaking upgrades occur.
* **Non-Interactive Atomic Rollback**: If an upgraded package cannot pass verification, all changes are reverted cleanly without manual intervention.

---

## Quickstart

### 1. Local CLI Execution (Zero CI Cost)

Run directly on your local workstation without consuming GitHub Actions compute minutes:

```bash
# Clone and run
git clone https://github.com/tech49labs/greenpr.git
cd greenpr
pip install -r requirements.txt

# Run full autonomous remediation sweep across your project:
python remediate.py

# Verify and stage changes locally without pushing a remote PR:
python remediate.py --skip-pr

# Target a specific package directly:
python remediate.py --package vite --target-version 7.3.7
```

### 2. GitHub Actions Workflow

Add `.github/workflows/greenpr.yml` to your repository:

```yaml
name: GreenPR Dependency Remediation

on:
  schedule:
    - cron: '0 2 * * 1' # Weekly Monday sweep at 02:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  remediate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: tech49labs/greenpr@v1
        with:
          api_key: ${{ secrets.GREENPR_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

---

## Command Line Reference

| Flag | Type | Description |
| :--- | :--- | :--- |
| `--test-cmd` | string | Custom test command override (e.g. `pnpm typecheck`, `pytest`). Auto-detected if omitted. |
| `--package` | string | Target a specific package name directly, skipping discovery scan. |
| `--target-version` | string | Target version to update the specified package to. |
| `--limit` | int | Maximum number of packages to remediate in a single run. |
| `--skip-pr` | flag | Stage verified changes locally on the current branch without pushing a remote PR. |
| `--ecosystem` | string | Filter discovery by ecosystem (`npm`, `pypi`, `go`, `crates.io`, `all`). |
| `--verbose` | flag | Display full verbose package manager installation logs. |

---

## Commercial Licensing

GreenPR is distributed under the **Tech49 Labs Commercial & Fair-Source License (v1.0)**:

* **Community / Open Source ($0)**: Free forever for local evaluation and all public open-source repositories.
* **Team ($49 / repo / mo)**: Commercial private repository license including autonomous code healing and multi-tier syntax repair.
* **Enterprise Monorepo ($899 / org / mo)**: Organization-wide unlimited repositories, unlimited monorepo subprojects, private VPC runner support, and SLA compliance guarantee.

For commercial licensing and enterprise agreements: [licensing@tech49labs.com](mailto:licensing@tech49labs.com)  
Website: [https://tech49labs.github.io/greenpr](https://tech49labs.github.io/greenpr)
