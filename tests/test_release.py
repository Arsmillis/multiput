# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Release notes generation (tools/release_notes.py), and `tools/release.sh --verify` against a fake gh.

Run: python3 tests/test_release.py
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
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

# `tools/release.sh --verify`: the local build against the digests GitHub records for the
# release's files. Runs a copy of the script in a scratch tree, with a fake gh on PATH that
# answers from assets.txt ("name digest" lines; one call per line of calls.txt is logged).
tree = pathlib.Path(tempfile.mkdtemp())
(tree / "tools").mkdir()
shutil.copy(ROOT / "tools" / "release.sh", tree / "tools" / "release.sh")
(tree / "VERSION").write_text("0.9.0\n")
(tree / "build" / "installer").mkdir(parents=True)
(tree / "build" / "firmware").mkdir(parents=True)
(tree / "build" / "installer" / "multiput-setup-0.9.0.exe").write_bytes(b"installer")
(tree / "build" / "firmware" / "multiput.uf2").write_bytes(b"firmware")
bin_dir = tree / "bin"
bin_dir.mkdir()
(bin_dir / "gh").write_text(f"""#!/usr/bin/env bash
echo "$*" >> {tree}/calls.txt
case "$1 $2" in
  "repo view") echo owner/multiput ;;
  api*) [ -f {tree}/assets.txt ] || exit 1
        cat {tree}/assets.txt
        [ ! -f {tree}/later.txt ] || mv {tree}/later.txt {tree}/assets.txt ;;  # GitHub catching up
esac
""")
(bin_dir / "gh").chmod(0o755)
def verify():
    (tree / "calls.txt").unlink(missing_ok=True)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    r = subprocess.run(["bash", str(tree / "tools" / "release.sh"), "--verify"], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr
digest = lambda data: "sha256:" + hashlib.sha256(data).hexdigest()
good = f"multiput-setup-0.9.0.exe {digest(b'installer')}\nmultiput.uf2 {digest(b'firmware')}\n"
(tree / "assets.txt").write_text(good)
code, out = verify()
assert code == 0 and out.count(": matches") == 2 and "OK:" in out, out
assert "release download" not in (tree / "calls.txt").read_text()            # nothing downloaded
(tree / "assets.txt").write_text(good.replace(digest(b"firmware"), digest(b"other")))
code, out = verify()
assert code == 1 and "multiput.uf2 on GitHub doesn't match the local build" in out, out
(tree / "assets.txt").write_text(good.splitlines()[0] + "\n")
code, out = verify()
assert code == 1 and "multiput.uf2 isn't on the v0.9.0 release" in out, out
(tree / "assets.txt").write_text(f"multiput-setup-0.9.0.exe {digest(b'installer')}\nmultiput.uf2 \n")  # digest not recorded yet
(tree / "later.txt").write_text(good)
code, out = verify()
assert code == 0 and out.count(": matches") == 2, out                       # waited, then matched
(tree / "assets.txt").unlink()
code, out = verify()
assert code == 1 and "there's no v0.9.0 release" in out, out
(tree / "assets.txt").write_text(good)
(tree / "build" / "firmware" / "multiput.uf2").unlink()
code, out = verify()
assert code == 1 and "multiput.uf2 is missing" in out, out
r = subprocess.run(["bash", str(tree / "tools" / "release.sh"), "--verfy"], capture_output=True, text=True)
assert r.returncode == 2 and "usage:" in r.stderr                            # a typo never starts a release
print("release --verify ok")
print("ALL OK")
