# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Write the GitHub release notes for a version: download guide, the version's
CHANGELOG.md section, and SHA-256 checksums of the release files.

Usage: python3 tools/release_notes.py VERSION INSTALLER UF2  > notes.md
"""
import hashlib
import pathlib
import re
import sys

REPO_URL = "https://github.com/Arsmillis/multiput"


def changelog_section(changelog, version):
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.S | re.M)
    body = m.group(1).strip() if m else ""
    if not body:
        raise SystemExit(f"CHANGELOG.md has no entries under '## [{version}]'.")
    return body


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def notes(version, changelog, installer, uf2):
    inst, fw = pathlib.Path(installer), pathlib.Path(uf2)
    return f"""Send one controller's input to your PC and a console at once.

## Download
- **`{inst.name}`**: the Windows installer. It includes the Pico firmware and walks you through flashing it. Windows may warn that the installer isn't code-signed: choose **More info → Run anyway**.
- `{fw.name}`: the generic Pico firmware on its own, for `multiput --setup --firmware {fw.name}`. Don't copy it onto the Pico directly: setup has to fill in your settings and key first, or the Pico just triple-blinks.

Setup and requirements are in the [README]({REPO_URL}#install). See [Tested consoles]({REPO_URL}#tested-consoles) for what it's been tested with.

## Changes in {version}
{changelog_section(changelog, version)}

## Checksums (SHA-256)
```
{sha256(inst)}  {inst.name}
{sha256(fw)}  {fw.name}
```
"""


if __name__ == "__main__":
    version, installer, uf2 = sys.argv[1:4]
    root = pathlib.Path(__file__).resolve().parent.parent
    sys.stdout.write(notes(version, (root / "CHANGELOG.md").read_text(), installer, uf2))
