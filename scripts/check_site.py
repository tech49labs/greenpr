"""Verify the deployed static artifact and private plan-enquiry links."""
import argparse
import hashlib
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from build_site import PUBLIC_FILES, ROOT

ENQUIRY_URL = 'https://docs.google.com/forms/d/e/1FAIpQLSd102fTw1I4rqFDYx00odjJO2aLth251H5znuUcI4KAitSokQ/viewform'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.requests = []

    def handle_starttag(self, tag, attributes):
        href = dict(attributes).get("href", "")
        if tag == "a" and href.startswith("mailto:"):
            raise AssertionError("Unexpected email link; the receiving inbox stays private")
        if tag == "a" and href == ENQUIRY_URL:
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
        with urlopen(Request(urljoin(base, path), headers={"User-Agent": "GreenPR-Release-Check/1.0"}), timeout=30) as response:
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
                assert len(links.requests) == 2, 'Both paid plans must reach the private enquiry form'
                assert b"$49" in payload and b"$899" in payload
        print("PASS:", filename)
    with urlopen(Request(ENQUIRY_URL, headers={"User-Agent": "GreenPR-Release-Check/1.0"}), timeout=30) as response:
        assert response.status == 200
        assert urlsplit(response.url).hostname == 'docs.google.com', 'Enquiry unexpectedly requires sign-in'
        form = response.read().decode('utf-8')
        for field in ('Request a GreenPR plan', 'Company name', 'Contact name', 'Email address', 'Other contact details', 'Submit'):
            assert field in form, field
    print('PASS: published enquiry form available without authentication')
    for path in ("app/", "api/license", "backend/app.py", ".env", "_headers"):
        try:
            urlopen(Request(urljoin(base, path), headers={"User-Agent": "GreenPR-Release-Check/1.0"}), timeout=30).close()
        except HTTPError as error:
            assert error.code == 404, (path, error.code)
        else:
            raise AssertionError("Unpublished route returned success: " + path)
        print("PASS: absent route", path)


if __name__ == "__main__":
    main()
