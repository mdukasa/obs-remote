"""Build OBS-Remote-Setup-<version>.exe:  python installer/build.py [--version X.Y.Z]

1. Downloads Python's official embeddable package (pinned version and SHA-256) into installer/cache/.
2. Puts the program files (what a release's source ZIP has, minus the repo-only and download-only parts) into
   installer/build/app, and Python into installer/build/runtime, set up to find the program's modules.
3. Compiles installer/obs-remote.iss with Inno Setup 6 (ISCC.exe) into installer/dist/.

Runs on Windows with Inno Setup 6 installed (winget install JRSoftware.InnoSetup; GitHub's runners: choco install
innosetup). Standard library only. The GitHub Action (.github/workflows/installer.yml) runs it for every release.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE, BUILD, DIST = (os.path.join(HERE, d) for d in ("cache", "build", "dist"))

PY_VERSION = "3.12.10"
PY_ZIP = "python-%s-embed-amd64.zip" % PY_VERSION
PY_URL = "https://www.python.org/ftp/python/%s/%s" % (PY_VERSION, PY_ZIP)
PY_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"  # its programs are signed by the Python Software Foundation

# Left out of the installed program: repo and build material, and the download-only scripts (an installed copy is
# set up and removed through the Start menu and Windows' Apps list instead of Install.bat / Uninstall.bat).
SKIP_TOP = {".git", ".github", "installer", "docs", "__pycache__", "Install.bat", "Uninstall.bat",
            ".gitattributes", ".gitignore"}


def program_files():
    """Files git knows or would add (tracked + untracked, not ignored), so a local build matches the working tree."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    for rel in sorted(set(f for f in out if f)):
        parts = rel.split("/")
        if parts[0] in SKIP_TOP or "__pycache__" in parts or not os.path.isfile(os.path.join(ROOT, rel)):
            continue
        yield rel


def get_python():
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, PY_ZIP)
    if not os.path.exists(path):
        print("Downloading", PY_URL)
        req = urllib.request.Request(PY_URL, headers={"User-Agent": "obs-remote-build"})
        with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(path + ".part", path)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if digest != PY_SHA256:
        os.remove(path)
        sys.exit("%s has SHA-256 %s, expected %s. Deleted it; not building." % (PY_ZIP, digest, PY_SHA256))
    return path


def iscc():
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        for sub in (r"Programs\Inno Setup 6\ISCC.exe", r"Inno Setup 6\ISCC.exe"):
            p = os.path.join(base or "", sub)
            if base and os.path.exists(p):
                return p
    return shutil.which("iscc") or sys.exit("Inno Setup 6 (ISCC.exe) not found: winget install JRSoftware.InnoSetup")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="default: the VERSION file")
    args = ap.parse_args()
    version = args.version or open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()

    shutil.rmtree(BUILD, ignore_errors=True)
    app, runtime = os.path.join(BUILD, "app"), os.path.join(BUILD, "runtime")
    n = 0
    for rel in program_files():
        dest = os.path.join(app, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dest)
        n += 1
    with open(os.path.join(app, "VERSION"), "w", encoding="utf-8") as f:
        f.write(version + "\n")
    print("Program: %d files" % n)

    with zipfile.ZipFile(get_python()) as z:
        z.extractall(runtime)
    # The embeddable Python only looks where its ._pth file says (not in the script's folder), so list the program
    # folder (..) there: server.py imports autofix, listen, youtube and paths from it.
    pth = [f for f in os.listdir(runtime) if f.endswith("._pth")]
    if len(pth) != 1:
        sys.exit("Expected one ._pth file in the embeddable Python, found %s" % pth)
    stdlib = [ln.strip() for ln in open(os.path.join(runtime, pth[0])) if ln.strip().endswith(".zip")]
    with open(os.path.join(runtime, pth[0]), "w") as f:
        f.write("\n".join(stdlib + [".", ".."]) + "\n")
    print("Python %s: %s" % (PY_VERSION, ", ".join(stdlib + [".", ".."])))

    os.makedirs(DIST, exist_ok=True)
    # Windows' file version must be numbers only: 1.11.0-beta1 -> 1.11.0
    num = ".".join((version.split("-")[0].split(".") + ["0", "0", "0"])[:3])
    subprocess.run([iscc(), "/Q", "/DAppVersion=" + version, "/DNumVersion=" + num, "/DBuildDir=" + BUILD, "/O" + DIST,
                    os.path.join(HERE, "obs-remote.iss")], check=True)
    out = os.path.join(DIST, "OBS-Remote-Setup-%s.exe" % version)
    print("Built %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
