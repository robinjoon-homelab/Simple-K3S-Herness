#!/usr/bin/env python3
"""Pin the central egress proxy to a published image digest for the CI release flow."""

import argparse
import re
import sys
from pathlib import Path


DEPLOYMENT = Path(__file__).resolve().parents[1] / "infrastructure/central-egress/deployment.yaml"
REPOSITORY = "registry.homelab.robinjoon.xyz/apps/agentgateway"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SOURCE_REVISION = re.compile(r"[0-9a-f]{40}")
IMAGE_LINE = re.compile(r"(?m)^( +image: )(\S+)$")


class ReleaseError(Exception):
    pass


def set_digest(digest, source_revision, deployment=DEPLOYMENT):
    """Return True when the file changed. Anything unexpected leaves it untouched."""
    if not DIGEST.fullmatch(digest or ""):
        raise ReleaseError("Digest must be sha256 followed by 64 lowercase hex characters.")
    if not SOURCE_REVISION.fullmatch(source_revision or ""):
        raise ReleaseError("Source revision must be a full lowercase commit SHA.")

    manifest = deployment.read_text()
    images = IMAGE_LINE.findall(manifest)
    if len(images) != 1:
        raise ReleaseError(f"Expected exactly one image line; found {len(images)}.")
    repository, separator, _ = images[0][1].partition("@")
    if repository != REPOSITORY or not separator:
        raise ReleaseError(f"The image must be {REPOSITORY} pinned by digest.")

    updated = IMAGE_LINE.sub(rf"\g<1>{REPOSITORY}@{digest}", manifest)
    if updated == manifest:
        return False
    deployment.write_text(updated)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--digest", required=True, help="Published image index digest")
    parser.add_argument("--source-revision", required=True, help="Commit the image was built from")
    args = parser.parse_args(argv)
    try:
        changed = set_digest(args.digest, args.source_revision)
    except (ReleaseError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    state = "Updated" if changed else "Already at"
    print(f"{state} {REPOSITORY}@{args.digest} from {args.source_revision}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
