"""Where OBS Remote keeps this PC's own files: logs and saved state.

They live in %LOCALAPPDATA%\\OBS Remote (or OBS_REMOTE_DATA), apart from the program folder, so updates and
reinstalls never have to step around them. Older versions kept them next to the program; the first run of a
newer version moves them across (migrate(), run on import).
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("OBS_REMOTE_DATA") or os.path.join(os.environ.get("LOCALAPPDATA") or HERE, "OBS Remote")

# file in DATA <- where versions before 1.11 kept it (relative to HERE)
_OLD = {
    "autofix.log": "autofix.log",
    "youtube.log": "youtube.log",
    "youtube_state.json": "youtube_state.json",
    "tailscale-route.txt": os.path.join("setup", "tailscale-route.txt"),
}


def data(name):
    """Full path of a file in the data folder (the folder is made if needed)."""
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)


def migrate():
    """Move files left by an older version into the data folder. A file already there wins."""
    for name, old in _OLD.items():
        src = os.path.join(HERE, old)
        try:
            if os.path.isfile(src) and os.path.normcase(src) != os.path.normcase(os.path.join(DATA, name)):
                dest = data(name)
                if os.path.exists(dest):
                    os.remove(src)
                else:
                    shutil.move(src, dest)
        except OSError:
            pass  # in use or read-only: try again next start


migrate()
