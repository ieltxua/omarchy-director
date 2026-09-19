#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.ieltxua.director"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}"
plugin_dir="$config_root/omarchy/plugins/$plugin_id"
legacy_plugin_dir="$config_root/omarchy/plugins/ieltxu.director"
bin_dir="${DIRECTOR_BIN_DIR:-$HOME/.local/bin}"
apps_dir="$data_root/applications"
man_dir="$data_root/man/man1"
bindings_file="$config_root/hypr/bindings.lua"
state_dir="$state_root/omarchy-director"
install_bindings=false
install_voice_bindings=false
setup_gateway=false

usage() {
  cat <<'EOF'
Usage: ./install.sh [--setup] [--bindings] [--voice-bindings]

Install optional user integrations for an already installed Director plugin:
CLI links, desktop launcher, and the omarchy-director(1) manual.

  --bindings        also add F10 and Super+Alt+J
  --voice-bindings  also add F8 preview voice and Super+Alt+V YOLO voice
  --setup           securely configure and start the bundled Jev gateway

Install the plugin itself first with `omarchy plugin add <git-url> --enable`.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bindings) install_bindings=true ;;
    --voice-bindings) install_bindings=true; install_voice_bindings=true ;;
    --setup) setup_gateway=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ "$repo_dir" == "$plugin_dir" ]] || {
  echo "Director is not in Omarchy's managed plugin directory: $plugin_dir" >&2
  echo "Install it first with: omarchy plugin add https://github.com/ieltxua/omarchy-director --enable" >&2
  exit 2
}

for command_name in python3 omarchy omarchy-shell; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 1; }
done

python3 -m compileall -q "$repo_dir/director"
omarchy plugin validate "$repo_dir"
install -d -m 700 "$state_dir/backups" "$bin_dir" "$apps_dir" "$man_dir"

for command_name in omarchy-director omarchy-director-ui omarchy-director-voice; do
  source="$plugin_dir/bin/$command_name"
  target="$bin_dir/$command_name"
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then continue; fi
    if [[ -L "$target" && "$(readlink "$target")" == "$legacy_plugin_dir/bin/$command_name" ]]; then continue; fi
    echo "Refusing to replace existing path: $target" >&2
    exit 1
  fi
done

desktop_file="$apps_dir/omarchy-director.desktop"
if [[ -f "$desktop_file" ]] && ! grep -qx 'X-Omarchy-Director-Managed=true' "$desktop_file"; then
  echo "Refusing to replace unmanaged desktop entry: $desktop_file" >&2
  exit 1
fi
manual_file="$man_dir/omarchy-director.1"
if [[ -f "$manual_file" ]] && ! grep -qx '\.\\" Managed by Omarchy Director' "$manual_file" && ! grep -q '^\.TH OMARCHY-DIRECTOR ' "$manual_file"; then
  echo "Refusing to replace unmanaged manual page: $manual_file" >&2
  exit 1
fi

if [[ "$install_bindings" == true && ! -f "$bindings_file" ]]; then
  echo "Hyprland bindings file not found: $bindings_file" >&2
  exit 1
fi

for command_name in omarchy-director omarchy-director-ui omarchy-director-voice; do
  source="$plugin_dir/bin/$command_name"
  target="$bin_dir/$command_name"
  if [[ -L "$target" && "$(readlink "$target")" == "$legacy_plugin_dir/bin/$command_name" ]]; then
    unlink "$target"
  fi
  [[ -L "$target" && "$(readlink "$target")" == "$source" ]] || ln -s "$source" "$target"
done

legacy_desktop="$apps_dir/ieltxu-director.desktop"
if [[ -f "$legacy_desktop" ]] && grep -qx 'X-Omarchy-Director-Managed=true' "$legacy_desktop"; then
  mv "$legacy_desktop" "$state_dir/backups/ieltxu-director.desktop"
fi

desktop_tmp="$state_dir/director.desktop.$$"
cat >"$desktop_tmp" <<'EOF'
[Desktop Entry]
Type=Application
Name=Director
GenericName=Omarchy Desktop Director
Comment=Control Hyprland with typed natural-language plans
Icon=preferences-system-windows
Exec=omarchy-director-ui
Terminal=false
Categories=Utility;System;
Keywords=windows;workspace;scene;layout;jev;hyprland;
StartupNotify=false
X-Omarchy-Director-Managed=true
EOF
install -m 644 "$desktop_tmp" "$desktop_file"
unlink "$desktop_tmp"
install -m 644 "$repo_dir/man/omarchy-director.1" "$manual_file"

if [[ "$install_bindings" == true ]]; then
  stamp="$(date +%Y%m%dT%H%M%S)"
  cp -p "$bindings_file" "$state_dir/backups/bindings.lua.$stamp"
  clean="$state_dir/bindings.clean.$$"
  awk '
    $0 == "-- BEGIN io.github.ieltxua.director" || $0 == "-- BEGIN ieltxu.director" { skip = 1; next }
    $0 == "-- END io.github.ieltxua.director" || $0 == "-- END ieltxu.director" { skip = 0; next }
    !skip { print }
  ' "$bindings_file" >"$clean"
  {
    cat "$clean"
    echo
    echo '-- BEGIN io.github.ieltxua.director'
    echo 'o.bind("SUPER + ALT + J", "Director", "omarchy-director-ui")'
    echo 'o.bind("F10", "Director", "omarchy-director-ui")'
    if [[ "$install_voice_bindings" == true ]]; then
      printf '%s\n' \
        'o.bind("F8", "Director voice preview", "omarchy-director-voice toggle --preview")' \
        'o.bind("SUPER + ALT + V", "Director voice YOLO", "omarchy-director-voice toggle --yolo")'
    fi
    echo '-- END io.github.ieltxua.director'
  } >"$clean.with-director"
  install -m 644 "$clean.with-director" "$bindings_file"
  unlink "$clean"
  unlink "$clean.with-director"
  if command -v hyprctl >/dev/null && [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then hyprctl reload >/dev/null; fi
fi

if [[ "$setup_gateway" == true ]]; then
  "$bin_dir/omarchy-director" setup
fi

echo "Director integrations installed. Run: omarchy-director doctor"
[[ "$install_bindings" == true ]] && echo "Keyboard bindings installed from an explicit option."
exit 0
