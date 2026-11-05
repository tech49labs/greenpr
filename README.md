# 🛡️ Auto-Heal: Zero-Hallucination Dependency Remediation Engine

> **Dependabot bumps versions and breaks your build. Auto-Heal patches the breaking code and guarantees 100% green tests before opening a PR.**

---

## ⚡ What Makes This "Zero Hallucination"?

Standard AI coding tools generate code and hope it works. **Auto-Heal enforces a deterministic compiler and test gate:**

1. **Scans**: `google/osv-scanner` identifies real CVEs across your lockfiles.
2. **Extracts**: `pydantic-ai` parses changelogs into a strict, validated Python schema.
3. **Bumps & Edits**: Updates the manifest and uses `Aider` with AST-level diffing to patch callsites.
4. **The Deterministic Gate**: Runs your language's compiler and test suite (`npm test`, `pytest`, `cargo test`, `go test`).
   - If exit code $\neq 0$, terminal errors are fed back to Aider to iteratively fix syntax.
   - If tests do not pass, **the branch is rolled back completely. No broken code is ever committed.**
5. **Verified PR**: Opens a pull request via `gh` CLI with verified test run proof.

---

## 🌐 Supported Languages (Auto-Detected)

Auto-Heal automatically detects and supports:
* **TypeScript / JavaScript** (`npm`, `tsc`, `eslint`, `jest/vitest`)
* **Python** (`pip`, `poetry`, `mypy`, `ruff`, `pytest`)
* **Go** (`go.mod`, `go build`, `golangci-lint`, `go test`)
* **Rust** (`Cargo.toml`, `cargo check`, `cargo clippy`, `cargo test`)
* **Java** (`pom.xml`, `build.gradle`, `mvn test`, `gradle test`)
* **C# / .NET** (`*.csproj`, `dotnet build`, `dotnet test`)

---

## 🚀 Quickstart: Run It Locally Right Now

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

Make sure you have `osv-scanner` and `gh` installed:
```bash
# MacOS
brew install osv-scanner gh

# Linux
curl -fsSL https://github.com/google/osv-scanner/releases/latest/download/osv-scanner_linux_amd64 -o /usr/local/bin/osv-scanner
chmod +x /usr/local/bin/osv-scanner
```

### 2. Run Auto-Heal in Any Repository
```bash
export ANTHROPIC_API_KEY="your-api-key"
# or export OPENAI_API_KEY / GEMINI_API_KEY

python remediate.py
```

### 3. Target a Specific Package Upgrade
```bash
python remediate.py --package axios --target-version 1.7.0 --test-cmd "npm test"
```

---

## 📦 Run as a GitHub Action

Drop this into `.github/workflows/auto-heal.yml` in any repo:

```yaml
name: Auto-Heal Security Remediation

on:
  schedule:
    - cron: '0 0 * * *' # Nightly
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  remediate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: your-org/auto-heal-action@v1
        with:
          api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```
