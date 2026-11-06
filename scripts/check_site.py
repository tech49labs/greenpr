"""Verify the deployed static artifact and GitHub license-request links."""
import argparse
import hashlib
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import urlopen

from build_site import PUBLIC_FILES, ROOT


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.requests = []

    def handle_starttag(self, tag, attributes):
        href = dict(attributes).get("href", "")
        if tag == "a" and href.startswith("mailto:"):
            raise AssertionError("Unexpected email link; launch uses GitHub requests")
        if tag == "a" and href.startswith("https://github.com/tech49labs/greenpr/issues/new"):
            self.requests.append(href)
        if tag == "script":
            raise AssertionError("Public site unexpectedly contains a script")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    base = args.url.rstrip("/") + "/"
    assert urlsplit(base).scheme == "https", "Public release must use HTTPS"
    for filename in PUBLIC_FILES:
        if filename == "_headers":
            continue
        path = "" if filename == "index.html" else filename
        with urlopen(urljoin(base, path), timeout=30) as response:
            assert response.status == 200
            assert urlsplit(response.url).netloc == urlsplit(base).netloc
            payload = response.read()
            expected = (ROOT / "dist" / "site" / filename).read_bytes()
            assert hashlib.sha256(payload).digest() == hashlib.sha256(expected).digest(), filename
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            csp = response.headers.get("Content-Security-Policy", "")
            assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
        if filename.endswith(".html"):
            links = Links()
            links.feed(payload.decode("utf-8"))
            if filename == "index.html":
                templates = [parse_qs(urlsplit(link).query).get("template", [None])[0] for link in links.requests]
                assert "team-license.yml" in templates and "enterprise-license.yml" in templates
                assert b"$49" in payload and b"$899" in payload
        print("PASS:", filename)
    for path in ("app/", "api/license", "backend/app.py", ".env", "_headers"):
        try:
            urlopen(urljoin(base, path), timeout=30).close()
        except HTTPError as error:
            assert error.code == 404, (path, error.code)
        else:
            raise AssertionError("Unpublished route returned success: " + path)
        print("PASS: absent route", path)


if __name__ == "__main__":
    main()
