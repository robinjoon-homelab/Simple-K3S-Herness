"""Fail the image build if an eMudhra TLS issuer remains trusted."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import ssl
import sys

import certifi
import httpx
from pip._vendor import certifi as pip_certifi


# Trust anchors and direct issuer of the compromised TLS intermediates.
# https://emudhra.we-have-a-problem.com/
BLOCKED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": "emSign ECC Root CA - G3",
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d": "emSign Root TLS CA - G3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": "AAA Certificate Services",
}


def check_context(name, context):
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError(f"{name}: certificate or hostname verification disabled")
    certificates = context.get_ca_certs(binary_form=True)
    if not certificates:
        raise RuntimeError(f"{name}: empty trust store")
    fingerprints = {hashlib.sha256(cert).hexdigest() for cert in certificates}
    blocked = fingerprints & BLOCKED_ROOTS.keys()
    if blocked:
        raise RuntimeError(f"{name}: compromised issuer trusted: {sorted(blocked)}")
    return {"roots": len(certificates), "blocked_issuers": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--https", action="store_true", help="also probe public HTTPS upstreams")
    parser.add_argument("--require-nonroot", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 13, 17):
        raise RuntimeError("Python 3.13.17 or newer is required")
    versions = {name: importlib.metadata.version(name) for name in ("pip", "certifi")}
    for name, minimum in (("pip", (26, 2, 2)), ("certifi", (2026, 10, 19))):
        if tuple(map(int, versions[name].split("."))) < minimum:
            raise RuntimeError(f"{name} is below the security minimum")
    if tuple(map(int, pip_certifi.__version__.split("."))) < (2026, 10, 19):
        raise RuntimeError("pip's vendored certifi is below the security minimum")
    if args.require_nonroot and os.getuid() != 10001:
        raise RuntimeError("image must run as UID 10001")
    contexts = {
        "system": ssl.create_default_context(),
        "certifi": ssl.create_default_context(cafile=certifi.where()),
        "pip-vendored-certifi": ssl.create_default_context(cafile=pip_certifi.where()),
        "httpx-default": httpx.create_ssl_context(),
    }
    result = {
        "python": sys.version.split()[0],
        **versions,
        "pip-vendored-certifi": pip_certifi.__version__,
        "uid": os.getuid(),
        "trust": {name: check_context(name, context) for name, context in contexts.items()},
    }
    if args.https:
        result["https"] = {}
        for url in ("https://api.github.com/", "https://pypi.org/simple/pip/"):
            response = httpx.get(url, timeout=30)
            response.raise_for_status()
            result["https"][url] = response.status_code
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
