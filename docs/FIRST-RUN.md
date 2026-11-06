# Your first free GreenPR run

Install the tool once, then run it from the project you want to check. No
GreenPR account, payment details, license file or model API key is needed for
Community use: public open-source projects and local personal evaluation.
Optional AI repair is a separate opt-in feature and is unnecessary here.

The examples below target Windows x64 PowerShell and Linux x64. Install Python
3.11 or later, Git and your project's package manager first. npm projects need
Node.js/npm and a committed `package-lock.json`; Yarn/pnpm-only projects are not
covered by the npm adapter. Python projects need a supported committed dependency
manifest. Other managers require their own runtime and project verification.

## Windows PowerShell: install

Run in PowerShell. The Python `py` launcher must be available; `py -3 --version`
must report Python 3.11 or later. This installs into your user folder and does
not require virtual-environment activation or an execution-policy change.
If the destination already exists, use that reviewed installation or choose
another empty folder; do not delete an existing project to make room.

```powershell
$greenprHome = Join-Path $env:USERPROFILE 'greenpr'
git clone https://github.com/tech49labs/greenpr.git $greenprHome
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; stop here.' }
py -3 -m venv (Join-Path $greenprHome '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
$greenprPython = Join-Path $greenprHome '.venv\Scripts\python.exe'
& $greenprPython -m pip install -r (Join-Path $greenprHome 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $greenprPython -m pip check
```

Install the reviewed scanner into a separate user tools folder. The checksum is
for the Windows x64 OSV-Scanner 2.7.0 release; stop if it differs.

```powershell
$greenprTools = Join-Path $env:LOCALAPPDATA 'GreenPR\bin'
New-Item -ItemType Directory -Path $greenprTools -Force | Out-Null
$greenprScanner = Join-Path $greenprTools 'osv-scanner.exe'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_windows_amd64.exe' -OutFile $greenprScanner
if ((Get-FileHash -LiteralPath $greenprScanner -Algorithm SHA256).Hash -ne '9964ed64ec9a387391eb4cc006ad5c531154821aef29b793e02c448de4686438') {
    throw 'Scanner checksum mismatch; do not run it.'
}
$env:PATH = $greenprTools + [IO.Path]::PathSeparator + $env:PATH
osv-scanner --version
```

## Windows PowerShell: scan and verify

Replace the example project path with your real project. Quotes preserve spaces.
These variables and PATH apply to the current terminal; repeat their assignments
when opening a new terminal. Leave the tool folder separate from your project.

```powershell
$greenprHome = Join-Path $env:USERPROFILE 'greenpr'
$greenprPython = Join-Path $greenprHome '.venv\Scripts\python.exe'
$greenprScript = Join-Path $greenprHome 'remediate.py'
$env:PATH = (Join-Path $env:LOCALAPPDATA 'GreenPR\bin') + [IO.Path]::PathSeparator + $env:PATH
Set-Location -LiteralPath 'C:\path\My Project'
& $greenprPython $greenprScript --scan-only --ecosystem all

# Example npm project: use the actual checks required by your project.
& $greenprPython $greenprScript --ecosystem npm --test-cmd 'npm test' --skip-pr
```

## Linux: install

Use a shell with Git, curl and `sha256sum`. Your Python installation needs venv
support (some distributions package it separately). These commands preserve an
existing installation by refusing to clone into a nonempty folder.

```sh
git clone https://github.com/tech49labs/greenpr.git "$HOME/greenpr" &&
python3 -m venv "$HOME/greenpr/.venv" &&
"$HOME/greenpr/.venv/bin/python" -m pip install -r "$HOME/greenpr/requirements.txt" &&
"$HOME/greenpr/.venv/bin/python" -m pip check
```

Install the reviewed Linux x64 scanner without root access:

```sh
mkdir -p "$HOME/.local/share/greenpr/bin" &&
curl --fail --location --proto '=https' --proto-redir '=https' \
  'https://github.com/google/osv-scanner/releases/download/v2.7.0/osv-scanner_linux_amd64' \
  --output "$HOME/.local/share/greenpr/bin/osv-scanner" &&
printf '%s  %s\n' '160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b' "$HOME/.local/share/greenpr/bin/osv-scanner" | sha256sum --check --strict &&
chmod 755 "$HOME/.local/share/greenpr/bin/osv-scanner" &&
export PATH="$HOME/.local/share/greenpr/bin:$PATH" &&
osv-scanner --version
```

## Linux: scan and verify

Repeat the PATH line in each new terminal, or add it to your own runner setup.
Replace the project path and example test command with your project's values.

```sh
export PATH="$HOME/.local/share/greenpr/bin:$PATH"
cd '/path/My Project'
"$HOME/greenpr/.venv/bin/python" "$HOME/greenpr/remediate.py" --scan-only --ecosystem all
"$HOME/greenpr/.venv/bin/python" "$HOME/greenpr/remediate.py" --ecosystem npm --test-cmd 'npm test' --skip-pr
```

## What a successful first run means

- Scan-only contacts advisory services and registries. It changes no project
  files and makes no model call. No actionable updates means there is nothing
  selectable to update in that scan, not a general security guarantee.
- Before an update, commit or move existing work through your normal review
  process. Do not discard changes just to pass GreenPR's clean-checkout guard.
- The same complete checks must pass before and after the update. Repeat
  `--test-cmd` for multiple required commands, or save them in `.greenpr.toml`.
  A Python project can use its own command, for example `python -m pytest`,
  after its test dependencies and configuration are available.
- `--skip-pr` publishes nothing. It prints `GREENPR_RESULT` with a JSON receipt,
  retained review checkout and patch. Your original checkout stays unchanged.
  Inspect the dependency declaration, lockfile, verification and rescan evidence.
- Optional PR publication needs GitHub CLI authentication, an intended GitHub
  origin and configured Git author details. It remains subject to review and
  repository protections. No GitHub login is needed for a local `--skip-pr` run.

Missing scanner or package manager: check `osv-scanner --version` and the
manager's version in the same terminal. A failed baseline means the project's
checks do not currently pass; fix that configuration or failure before updating.
Project-specific services, credentials and private registries still need the
project's own setup. Use the [full guide](https://greenpr-cw0.pages.dev/guide.html)
for reviewed setup commands, cleanup and read-only `--doctor` checks.

Other operating systems, architectures and project layouts need their own
verification. These instructions do not claim universal machine compatibility.
