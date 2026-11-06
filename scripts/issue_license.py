"""Issue an offline GreenPR license after manual payment verification.

The private signing key and issued licenses must remain outside the repository.
This command does not charge a customer or send email.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def publish_license(output, envelope, audit_record):
    """Publish complete files without overwriting either destination.

    The audit is linked first, so a valid license is never published without
    its audit. On a collision, remove only links created by this invocation.
    Staging and destination share a filesystem for atomic hard-link creation.
    """
    audit_path = output.with_suffix(output.suffix + ".audit.json")
    if output.exists() or audit_path.exists():
        raise FileExistsError("License or audit output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = []
    linked = []
    complete = False
    try:
        for destination, value in ((audit_path, audit_record), (output, envelope)):
            descriptor, name = tempfile.mkstemp(prefix=".greenpr-issue-", dir=output.parent)
            temporary = Path(name)
            staged.append(temporary)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(value, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, destination)
            linked.append((temporary, destination))
        complete = True
    finally:
        if not complete:
            for temporary, destination in reversed(linked):
                try:
                    if os.path.samestat(temporary.stat(), destination.stat()):
                        destination.unlink()
                except FileNotFoundError:
                    pass
        for temporary in staged:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, choices=["team", "enterprise"])
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--repository", action="append", default=[])
    parser.add_argument("--github-organization", action="append", default=[])
    parser.add_argument("--expires-at", required=True, type=timestamp)
    parser.add_argument("--payment-reference", required=True,
                        help="Operator-verified invoice/payment reference for local issuance audit")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--signing-key", type=Path,
                        default=Path.home() / ".codex/secrets/greenpr/license-signing.pem")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    repository = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    key_path = args.signing_key.resolve()
    if output.is_relative_to(repository) or key_path.is_relative_to(repository):
        parser.error("Signing keys and customer license files must be outside the source repository")
    if args.expires_at <= now:
        parser.error("Expiry must be in the future")
    repos = sorted(set(value.lower() for value in args.repository))
    orgs = sorted(set(value.lower() for value in args.github_organization))
    if any(not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", value) for value in repos):
        parser.error("Repositories must be owner/name")
    if any(not re.fullmatch(r"[a-z0-9-]+", value) for value in orgs):
        parser.error("GitHub organizations must be organization slugs")
    if args.plan == "team" and (len(repos) != 1 or orgs):
        parser.error("A Team license covers exactly one repository")
    owners = {value.split("/")[0] for value in repos} | set(orgs)
    if args.plan == "enterprise" and len(owners) != 1:
        parser.error("An Enterprise license covers exactly one GitHub organization")
    if not repos and not orgs:
        parser.error("At least one repository or GitHub organization is required")
    if not args.organization_id.strip() or not args.payment_reference.strip():
        parser.error("Organization and verified payment reference are required")
    if len(args.organization_id) > 200 or len(args.payment_reference) > 500:
        parser.error("Organization or payment reference exceeds the supported length")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        parser.error("Signing key must be Ed25519")
    expected = (repository / "engine/license_public_key.pem").read_bytes()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    if public != expected:
        parser.error("Signing key does not match the released verification key")
    payload = {
        "issuer": "GreenPR", "version": 1, "plan": args.plan,
        "organization_id": args.organization_id, "repositories": repos,
        "github_organizations": orgs,
        "issued_at": now.isoformat(), "expires_at": args.expires_at.isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    envelope = {"payload": payload, "signature": base64.b64encode(key.sign(canonical)).decode("ascii")}
    if len((json.dumps(envelope, indent=2) + "\n").encode("utf-8")) > 16384:
        parser.error("License scope exceeds the supported file size")
    try:
        publish_license(output, envelope, {"issued_at": now.isoformat(), "payment_reference": args.payment_reference,
                                         "organization_id": args.organization_id, "license": output.name})
    except OSError:
        parser.error("Could not publish license and audit; check permissions and existing output files")
    print(f"Created license: {output}")
    print("Send only the license file to the customer after verifying its scope and paid period.")


if __name__ == "__main__":
    main()
