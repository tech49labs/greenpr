"""Explicit commercial license validation; free evaluation makes no billing call."""
import json
import os
import re
import subprocess
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def repository_identity():
    remote = subprocess.run(["git", "remote", "get-url", "origin"], check=True,
                            capture_output=True, text=True).stdout.strip()
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", remote)
    if not match:
        raise ValueError("Commercial license requires an unambiguous GitHub origin")
    return match.group(1).lower()


def validate_commercial_license():
    if os.environ.get("GREENPR_LICENSE_FILE"):
        return validate_offline_license(os.environ["GREENPR_LICENSE_FILE"])
    base = os.environ.get("GREENPR_API_URL", "").rstrip("/")
    token = os.environ.get("GREENPR_LICENSE_TOKEN", "")
    parsed = urlsplit(base)
    if not token or not base or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Set GREENPR_API_URL and GREENPR_LICENSE_TOKEN for commercial execution")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("License service must use HTTPS")
    repository = repository_identity()
    request = Request(base + "/api/license?" + urlencode({"repository": repository}),
                      headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    # Do not follow redirects: a redirected Authorization header could disclose
    # the repository token to a different service.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            payload = json.loads(response.read(65537))
    except Exception as exc:
        raise ValueError("Commercial license could not be verified; no remediation started") from exc
    from datetime import datetime, timezone
    try:
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        current = datetime.now(timezone.utc)
        active = expires.tzinfo is not None and current < expires
    except (KeyError, TypeError, ValueError, AttributeError):
        active = False
    if (payload.get("licensed") is not True or payload.get("repository", "").lower() != repository
            or payload.get("plan") not in ("team", "enterprise") or not payload.get("organization_id") or not active):
        raise ValueError("License is inactive or does not cover this repository")
    return {key: payload.get(key) for key in ("plan", "organization_id", "repository", "expires_at")}


def validate_offline_license(filename, public_key_path=None, now=None):
    """Verify a vendor-signed manual license without contacting a server."""
    import base64
    from datetime import datetime, timezone
    from pathlib import Path
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    public_key_path = Path(public_key_path or Path(__file__).with_name("license_public_key.pem"))
    try:
        raw = Path(filename).read_bytes()
        if len(raw) > 16384:
            raise ValueError("License file exceeds size limit")
        envelope = json.loads(raw)
        payload = envelope["payload"]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        key = load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Unsupported verification key")
        key.verify(base64.b64decode(envelope["signature"], validate=True), canonical)
        current = now or datetime.now(timezone.utc)
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        issued = datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00"))
        if issued.tzinfo is None or expires.tzinfo is None or not issued <= current < expires:
            raise ValueError("License is not active")
        if payload.get("issuer") != "GreenPR" or payload.get("version") != 1 or payload.get("plan") not in ("team", "enterprise"):
            raise ValueError("Invalid license issuer or plan")
        repository = repository_identity()
        repositories = payload.get("repositories", [])
        organizations = payload.get("github_organizations", [])
        if (not isinstance(repositories, list) or not isinstance(organizations, list)
                or any(not isinstance(repo, str) or not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repo) for repo in repositories)
                or any(not isinstance(org, str) or not re.fullmatch(r"[a-z0-9_.-]+", org) for org in organizations)):
            raise ValueError("Malformed repository scope")
        if payload["plan"] == "team" and (len(repositories) != 1 or organizations):
            raise ValueError("Team license must cover exactly one repository")
        owners = {repo.split("/")[0] for repo in repositories} | set(organizations)
        if payload["plan"] == "enterprise" and len(owners) != 1:
            raise ValueError("Enterprise license must cover one GitHub organization")
        covered = repository in repositories or (payload["plan"] == "enterprise" and repository.split("/")[0] in organizations)
        if not covered or not payload.get("organization_id"):
            raise ValueError("License does not cover this repository")
        return {"plan": payload["plan"], "organization_id": payload["organization_id"],
                "repository": repository, "expires_at": payload["expires_at"]}
    except Exception as exc:
        raise ValueError("Offline license could not be verified: check signature, expiry, and repository coverage") from exc
