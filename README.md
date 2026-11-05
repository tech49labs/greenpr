# GreenPR: Autonomous Zero-Hallucination Dependency Remediation

> **Standard security bots bump versions and break your build. GreenPR resolves breaking syntax and guarantees 100% green tests before opening a Pull Request.**

*Engineered by **tech49labs***

---

## The Zero-Hallucination Architecture

Traditional automated tools generate unverified code modifications and leave broken builds for developers to debug. **GreenPR operates on a deterministic, closed-loop verification pipeline:**

1. **Security Radar**: Automatically maps project dependencies across lockfiles to identify vulnerable packages.
2. **Interface Migration Analysis**: Analyzes target version changes and extracts structured interface transformation rules.
3. **Automated Remediation Engine**: Applies precise repairs to deprecated callsites, updated imports, and modified method signatures.
4. **The Deterministic Verification Gate**: Executes your project's actual compiler and test harness (`npm test`, `pytest`, `cargo test`, `go test`, `dotnet test`).
   - If tests fail, the engine enters an autonomous healing loop to resolve syntax and interface discrepancies.
   - If the codebase cannot achieve **Exit Code 0**, all modifications are **immediately rolled back**. No broken code is ever committed.
5. **Verified Delivery Pipeline**: Publishes a cryptographically clean Pull Request with deterministic test pass proof attached.

---

## Supported Ecosystems (Auto-Detected)

GreenPR auto-detects and supports all major development environments out of the box:
* **TypeScript / JavaScript**: `npm`, `pnpm`, `yarn`, `bun`, `tsc`, `eslint`, `vitest`, `jest`
* **Python**: `pip`, `poetry`, `mypy`, `ruff`, `pytest`
* **Go**: `go.mod`, `go build`, `golangci-lint`, `go test`
* **Rust**: `Cargo.toml`, `cargo check`, `cargo clippy`, `cargo test`
* **Java**: `pom.xml`, `build.gradle`, `mvn test`, `gradle test`
* **C# / .NET**: `*.csproj`, `*.sln`, `dotnet build`, `dotnet test`

---

## Model Agnostic Design

GreenPR is completely model and provider agnostic. You can connect whichever AI intelligence backend fits your organization's compliance and budget:

* **Google Gemini** (Gemini Flash & Gemini Pro)
* **Anthropic Claude** (Claude 3.5 Haiku & Sonnet)
* **OpenAI** (GPT-4o mini & GPT-4o)
* **DeepSeek** (DeepSeek-Chat & DeepSeek-Reasoner)
* **Groq / Llama** (Open Source Llama 3.3)
* **Local Self-Hosted Endpoints** (Ollama / vLLM / LiteLLM)

---

## Installation & Deployment

### GitHub Actions Workflow

Drop `.github/workflows/greenpr.yml` into any repository:

```yaml
name: GreenPR Dependency Remediation

on:
  schedule:
    - cron: '0 2 * * *' # Nightly automated remediation sweep
  workflow_dispatch:     # On-demand manual trigger

permissions:
  contents: write
  pull-requests: write

jobs:
  remediate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tech49labs/greenpr@v1
        with:
          api_key: ${{ secrets.GREENPR_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

### Local CLI Execution

```bash
# Run full automated dependency scan and verified PR delivery:
greenpr

# Run verification locally without publishing a remote PR:
greenpr --skip-pr

# Target a specific package directly:
greenpr --package ws --target-version 8.21.0 --test-cmd "npm test"
```

---

## Commercial Distribution

Proprietary software by **tech49labs**. All rights reserved.
