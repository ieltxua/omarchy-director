from __future__ import annotations

import configparser
import os
import subprocess
from pathlib import Path


def desktop_entries(home: str | None = None) -> dict[str, dict[str, str]]:
    root = Path(home or os.path.expanduser("~"))
    directories = (root / ".local/share/applications", Path("/usr/share/applications"))
    result: dict[str, dict[str, str]] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.desktop"):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (OSError, KeyError, configparser.Error):
                continue
            if entry.get("Type") != "Application" or entry.getboolean("Hidden", fallback=False):
                continue
            desktop_id = path.stem
            # We deliberately do not parse or execute Exec. gtk-launch resolves this exact ID.
            result[desktop_id] = {"id": desktop_id, "name": entry.get("Name", desktop_id), "startup_wm_class": entry.get("StartupWMClass", ""), "generic_name": entry.get("GenericName", ""), "comment": entry.get("Comment", ""), "keywords": entry.get("Keywords", "")}
    return result


def launch(desktop_id: str, entries: dict[str, dict[str, str]], spawner=subprocess.Popen) -> None:
    if desktop_id not in entries:
        raise ValueError("desktop entry is not allowlisted")
    # GUI applications may keep gtk-launch's pipes open for their entire
    # lifetime. Detach all standard streams so planning can continue to window
    # discovery instead of waiting until the application exits.
    process = spawner(
        ["gtk-launch", desktop_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        returncode = process.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        return
    if isinstance(returncode, int) and returncode != 0:
        raise RuntimeError(f"gtk-launch failed with status {returncode}")
