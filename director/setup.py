from __future__ import annotations

import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

from .config import load_config, save_config
from .providers import get_provider


SERVICE_NAME = "omarchy-director-jev.service"


def _config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def credential_path(provider_name: str = "openrouter") -> Path:
    return _config_root() / "omarchy-director" / get_provider(provider_name).credential_filename


def service_path() -> Path:
    return _config_root() / "systemd" / "user" / SERVICE_NAME


def socket_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "omarchy-director" / "jev.sock"


def _quote_systemd(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _service_unit(command: Path, key_file: Path, socket_file: Path, provider_name: str) -> str:
    python = Path(shutil.which("python3") or "/usr/bin/python3")
    return f"""# Managed by Omarchy Director
[Unit]
Description=Local Jev gateway for Omarchy Director
Documentation=https://github.com/ieltxua/omarchy-director
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Environment={_quote_systemd(f'DIRECTOR_JEV_CREDENTIAL_FILE={key_file}')}
Environment={_quote_systemd(f'DIRECTOR_JEV_PROVIDER={provider_name}')}
Environment={_quote_systemd(f'JEV_SOCKET_PATH={socket_file}')}
Environment=JEV_DEFAULT_MODEL=typesafe/jev-1.13
UMask=0077
ExecStart={_quote_systemd(str(python))} {_quote_systemd(str(command))} gateway serve
Restart=on-failure
RestartSec=2s
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=default.target
"""


def _read_key(provider_name: str, *, key_stdin: bool) -> str | None:
    if key_stdin:
        return sys.stdin.readline().strip()
    provider = get_provider(provider_name)
    from_environment = os.environ.get(provider.credential_environment, "").strip()
    if from_environment:
        return from_environment
    if sys.stdin.isatty():
        return getpass.getpass(f"{provider.name} credential (input hidden): ").strip()
    return None


def _atomic_private_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def setup_gateway(command: Path, *, provider_name: str = "openrouter", key_stdin: bool = False, start: bool = True, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, str | bool]:
    get_provider(provider_name)
    key_file = credential_path(provider_name)
    unit_file = service_path()
    socket_file = socket_path()
    if unit_file.exists() and "# Managed by Omarchy Director" not in unit_file.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"Refusing to replace unmanaged service: {unit_file}")
    key = _read_key(provider_name, key_stdin=key_stdin)
    if key:
        _atomic_private_write(key_file, key + "\n")
    elif not key_file.is_file():
        env_name = get_provider(provider_name).credential_environment
        raise RuntimeError(f"Set {env_name}, use --key-stdin, or run setup interactively")
    _atomic_private_write(unit_file, _service_unit(command.resolve(), key_file.resolve(), socket_file, provider_name))
    values = load_config()
    values.update({"jev_socket_path": str(socket_file), "jev_provider": provider_name})
    save_config(values)
    if start:
        for argv in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", SERVICE_NAME]):
            result = runner(argv, capture_output=True, text=True, check=False)
            if result.returncode:
                raise RuntimeError((result.stderr or "").strip() or f"Failed: {' '.join(argv)}")
    return {"configured": True, "started": start, "provider": provider_name, "service": str(unit_file), "socket": str(socket_file), "credential": str(key_file)}


def teardown_gateway(*, purge_key: bool = False, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, bool]:
    unit_file = service_path()
    if unit_file.is_file() and "# Managed by Omarchy Director" not in unit_file.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"Refusing to remove unmanaged service: {unit_file}")
    selected_credential: Path | None = None
    if purge_key:
        configured_provider = str(load_config().get("jev_provider", "openrouter"))
        selected_credential = credential_path(configured_provider)
    if unit_file.is_file() and shutil.which("systemctl"):
        result = runner(["systemctl", "--user", "disable", "--now", SERVICE_NAME], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError((result.stderr or "").strip() or "Failed to stop Director's Jev service")
    removed_service = False
    if unit_file.is_file():
        unit_file.unlink()
        removed_service = True
    if removed_service and shutil.which("systemctl"):
        result = runner(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError((result.stderr or "").strip() or "Failed to reload user services")
    removed_key = False
    if selected_credential is not None and selected_credential.is_file():
        selected_credential.unlink()
        removed_key = True
    return {"service_removed": removed_service, "credential_removed": removed_key}
