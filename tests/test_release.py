# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Release notes generation (tools/release_notes.py).

Run: python3 tests/test_release.py
"""
import hashlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release_notes as rn  # noqa: E402

LOG = """# Changelog

## [Unreleased]
- next thing

## [0.2.0] - 2026-12-01
### Added
- Two

## [0.1.0] - 2026-11-16
First release.
"""
assert rn.changelog_section(LOG, "0.2.0") == "### Added\n- Two"
assert rn.changelog_section(LOG, "0.1.0") == "First release."   # last section, up to the end
for missing in ["0.3.0", "0.1"]:  # absent, or only a prefix of a real version
    try:
        rn.changelog_section(LOG, missing)
        raise AssertionError(f"accepted {missing}")
    except SystemExit:
        pass
try:
    rn.changelog_section("## [1.0.0] - x\n\n## [0.9.0] - y\n- old\n", "1.0.0")  # heading with no entries
    raise AssertionError("accepted an empty section")
except SystemExit:
    pass
print("changelog section ok")

d = pathlib.Path(tempfile.mkdtemp())
(d / "multiput-setup-0.2.0.exe").write_bytes(b"installer")
(d / "multiput.uf2").write_bytes(b"firmware")
text = rn.notes("0.2.0", LOG, d / "multiput-setup-0.2.0.exe", d / "multiput.uf2")
assert "## Changes in 0.2.0\n### Added\n- Two" in text and "First release." not in text
assert f"{hashlib.sha256(b'installer').hexdigest()}  multiput-setup-0.2.0.exe" in text
assert f"{hashlib.sha256(b'firmware').hexdigest()}  multiput.uf2" in text
print("notes ok")
print("ALL OK")
