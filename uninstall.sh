#!/usr/bin/env bash
set -euo pipefail

plugin_id="ieltxu.director"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}"
plugin_dir="$config_root/omarchy/plugins/$plugin_id"
bin_dir="${DIRECTOR_BIN_DIR:-$HOME/.local/bin}"
state_dir="$state_root/omarchy-director"
bindings_file="$config_root/hypr/bindings.lua"
stamp="$(date +%Y%m%dT%H%M%S)"

install -d -m 700 "$state_dir/removed"

for command_name in omarchy-director omarchy-director-ui omarchy-director-voice; do
  link_path="$bin_dir/$command_name"
  if [[ -L "$link_path" && "$(readlink "$link_path")" == "$plugin_dir/bin/$command_name" ]]; then unlink "$link_path"; fi
done

desktop_file="$data_root/applications/ieltxu-director.desktop"
if [[ -f "$desktop_file" ]] && grep -Eq '^(X-Omarchy-Director-Managed=true|Exec=omarchy-director-ui)$' "$desktop_file"; then
  mv "$desktop_file" "$state_dir/removed/ieltxu-director.$stamp.desktop"
fi

manual_file="$data_root/man/man1/omarchy-director.1"
if [[ -f "$manual_file" ]] && grep -q '^\.TH OMARCHY-DIRECTOR ' "$manual_file"; then
  mv "$manual_file" "$state_dir/removed/omarchy-director.$stamp.1"
fi

if [[ -f "$bindings_file" ]] && grep -Fq -- '-- BEGIN ieltxu.director' "$bindings_file"; then
  cp -p "$bindings_file" "$state_dir/removed/bindings.lua.$stamp"
  clean="$state_dir/bindings.clean.$$"
  awk '
    $0 == "-- BEGIN ieltxu.director" { skip = 1; next }
    $0 == "-- END ieltxu.director" { skip = 0; next }
    !skip { print }
  ' "$bindings_file" >"$clean"
  install -m 644 "$clean" "$bindings_file"
  unlink "$clean"
fi

if command -v hyprctl >/dev/null && [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then hyprctl reload >/dev/null 2>&1 || true; fi

echo "Director user integrations removed; scenes and history were preserved."
echo "Remove the plugin checkout separately with: omarchy plugin remove $plugin_id"
