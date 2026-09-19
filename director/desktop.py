from __future__ import annotations

import configparser
import os
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


def launch(desktop_id: str, entries: dict[str, dict[str, str]], runner) -> None:
    if desktop_id not in entries:
        raise ValueError("desktop entry is not allowlisted")
    completed = runner(["gtk-launch", desktop_id], capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "gtk-launch failed")
