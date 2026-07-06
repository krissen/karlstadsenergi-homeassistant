"""Update the release version in manifest.json and const.py.

Run by the release workflow with the published tag, e.g.
``update_manifest.py --version v0.5.0``. Keeps both the manifest ``version``
(used by HACS) and ``const.VERSION`` (used as the device ``sw_version``) in
sync with the tag so the two never drift in a released artifact.
"""

import json
import os
import re
import sys

BASE = f"{os.getcwd()}/custom_components/karlstadsenergi"


def _requested_version() -> str:
    for index, value in enumerate(sys.argv):
        if value in ["--version", "-V"]:
            return sys.argv[index + 1].lstrip("v")
    return "0.0.0"


def update_manifest(version: str) -> None:
    """Set the version in manifest.json."""
    path = f"{BASE}/manifest.json"
    with open(path) as manifestfile:
        manifest = json.load(manifestfile)

    manifest["version"] = version

    with open(path, "w") as manifestfile:
        manifestfile.write(json.dumps(manifest, indent=4, sort_keys=True))


def update_const(version: str) -> None:
    """Set VERSION in const.py to match the manifest version."""
    path = f"{BASE}/const.py"
    with open(path) as constfile:
        content = constfile.read()

    new_content, count = re.subn(
        r'^VERSION = ".*"$',
        f'VERSION = "{version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit(f"Expected exactly one VERSION line in {path}, found {count}")

    with open(path, "w") as constfile:
        constfile.write(new_content)


def main() -> None:
    version = _requested_version()
    update_manifest(version)
    update_const(version)


main()
