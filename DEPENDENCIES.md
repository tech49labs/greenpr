# Dependency resolution and security checks

`requirements.txt` loads the adjacent `requirements.lock.txt` as version constraints. Install from requirements, not
from the constraint file alone: this preserves dependency extras and platform
markers. Copy the adjacent constraint file into container build contexts too.

The constraints were generated from clean pip `--ignore-installed --dry-run
--report` resolutions on CPython 3.14 Windows. They pin the resolved version set,
not wheel hashes; pip chooses platform-specific distributions. Linux/container
acceptance is separate. Future Python/platform combinations may require a new
resolution and review; do not silently remove constraints to bypass conflicts.

Update procedure:

1. Resolve each requirements file in a clean isolated environment. When changing
   versions, revise the reviewed constraints together with direct requirements.
2. Save the resolver/install report and compare every installed distribution
   against the constraint set. Keep test-only tooling separate.
3. Scan the full resolved constraint files with no additional dependency solver:

```sh
osv-scanner scan source --no-resolve --format=json --all-packages --lockfile requirements.lock.txt --output-file dist/dependency-resolved-scan.json
```

`--no-resolve` scans every pinned direct/transitive package as listed; it avoids
replacing the tested environment with deps.dev's inferred minimum versions.
The first scan's unpinned resolution had reported older AnyIO, certifi and idna
versions; those are not the versions installed by this clean resolution.

The updated sets use cryptography 50.0.0, AnyIO 4.16.0, certifi 2026.10.23, and
idna 3.20. cryptography 50.0.0 was verified against its official PyPI release
metadata: https://pypi.org/pypi/cryptography/50.0.0/json . The previous 49.0.0 pin
was affected by GHSA-g6cj-pr64-35w5; the scanner identifies 50.0.0 as fixed.

The resolved CLI dependency scan covered 33 package entries and exited zero.
A clean advisory scan establishes the result against the scanner's current
advisory database; it does not guarantee absence of unknown vulnerabilities.

Local dependency validation uses an isolated virtual environment rather than
modifying global packages. Customer installation should use a fresh virtual environment and
`python -m pip install -r requirements.txt`.
