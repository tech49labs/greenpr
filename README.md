# 🛡️ GreenPR: Autonomous Zero-Hallucination Dependency Remediation

> **Dependabot bumps versions and breaks your build. GreenPR patches breaking syntax and guarantees 100% green tests before opening a Pull Request.**

*Engineered by **tech49labs***

---

## ⚡ The Zero-Hallucination Guarantee

Traditional AI tools generate code and leave you to fix the bugs. **GreenPR operates on a closed-loop deterministic verification gate:**

1. **Vulnerability Radar**: Automatically maps your project's dependency graph against the global CVE advisory database.
2. **Semantic Migration Engine**: Synthesizes upstream changelogs into rigid, typed API transformation rules.
3. **Deterministic Code Engine**: Applies surgical, AST-level diffs to deprecated callsites and imports.
4. **The Zero-Hallucination Gate**: Executes your project's actual compiler and test suite (`npm test`, `pytest`, `cargo test`, `go test`).
   - If tests fail, the engine enters an autonomous healing loop to repair syntax discrepancies.
   - If tests cannot achieve **Exit Code 0**, the code is **immediately rolled back**. No broken code is ever committed.
5. **Verified Delivery Pipeline**: Publishes a cryptographically clean Pull Request with full test logs attached.

---

## 🌐 Supported Environments (Auto-Detected)

GreenPR auto-detects and supports all major ecosystems out of the box:
* **TypeScript / JavaScript** (`npm`, `pnpm`, `yarn`, `bun`, `tsc`, `eslint`, `vitest`/`jest`)
* **Python** (`pip`, `poetry`, `mypy`, `ruff`, `pytest`)
* **Go** (`go.mod`, `go build`, `golangci-lint`, `go test`)
* **Rust** (`Cargo.toml`, `cargo check`, `cargo clippy`, `cargo test`)
* **Java** (`pom.xml`, `build.gradle`, `mvn test`, `gradle test`)
* **C# / .NET** (`*.csproj`, `dotnet build`, `dotnet test`)

---

## 🚀 Usage

### Local CLI Execution

```bash
# Install GreenPR dependencies
pip install -r requirements.txt

# Run full vulnerability scan & remediation:
python remediate.py

# Or target a specific package upgrade:
python remediate.py --package ws --target-version 8.21.0 --test-cmd "npm test"
```

### GitHub Actions Workflow

Drop `.github/workflows/greenpr.yml` into any repository:

```yaml
name: GreenPR Security Remediation

on:
  schedule:
    - cron: '0 0 * * *' # Nightly automated sweep
  workflow_dispatch:     # On-demand manual trigger

permissions:
  contents: write
  pull-requests: write

jobs:
  greenpr:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tech49labs/greenpr@v1
        with:
          api_key: ${{ secrets.GREENPR_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

---

## 📄 License & Commercial Distribution

Proprietary enterprise distribution by **tech49labs**. All rights reserved.
