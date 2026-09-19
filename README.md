# Director for Omarchy

Director is a theme-native Omarchy shell plugin that turns natural language into
typed, previewable Hyprland actions. It can arrange windows, navigate workspaces,
control selected Omarchy features, and capture entire desktops as reusable scenes.

Jev interprets intent from closed candidate sets. Local deterministic code owns
permissions, validation, exact arguments, execution, verification, and undo.
Prompt text is never executed as shell.

## Highlights

- **Programmable desktops:** capture, update, invoke, list, and delete named scenes.
- **Address-free restore:** scenes match semantic window identity instead of stale
  Hyprland addresses and can launch identifiable missing applications.
- **Composition:** say `float ChatGPT and save as review` in one request.
- **Native control:** focus, move, resize, tile, float, fullscreen, launch, themes, audio,
  brightness, night light, notification silencing, capture, reminders, and lock.
- **Real undo:** restores observed window, workspace, scene, theme, volume, and
  brightness state instead of blindly issuing the opposite command.
- **Omarchy UI:** uses the current shell theme, typography, spacing, borders, and
  animation primitives. There is no separate Director theme to maintain.
- **Voice adapter:** optional Voxtype preview and guarded hands-free execution.

## Requirements

Required:

- Omarchy with shell-plugin support and typed Hyprland dispatchers.
- Python 3.10 or newer, `jq`, `hyprctl`, `omarchy`, and `omarchy-shell`.
- A local Jev gateway exposing `POST /v1/systemone` over a Unix socket and the
  pinned `typesafe/jev-1.13` model.

Optional:

- `voxtype` for voice commands.
- A microphone helper accepting `start` and `stop`, configured through
  `DIRECTOR_MIC_CONTROL_BIN`, for Bluetooth/profile bridges.

Director does not read an OpenRouter or TypeSafe credential. The local Jev gateway
owns provider authentication.

## Installation

Omarchy plugins are git repositories. Install and enable Director with:

```bash
omarchy plugin add https://github.com/ieltxu/omarchy-director.git --enable
```

That is sufficient to use Director from its bar icon. Left-click opens the text
palette; right-click starts voice in preview mode when Voxtype is installed.

### Optional CLI, launcher, man page, and shortcuts

The official Omarchy plugin installer intentionally runs no hooks. Director's
optional integration script must therefore be invoked explicitly:

```bash
cd ~/.config/omarchy/plugins/ieltxu.director
./install.sh
```

This adds user-owned CLI links, a desktop launcher, and `man omarchy-director`.
It does not edit Hyprland configuration unless you opt in:

```bash
./install.sh --bindings         # F10 and Super+Alt+J
./install.sh --voice-bindings   # above plus F8 preview and Super+Alt+V YOLO
```

The script refuses to overwrite unrelated commands or desktop entries and backs
up `bindings.lua` before changing its marked Director block.

## Jev configuration

Director searches, in order:

1. `JEV_SOCKET_PATH`;
2. the saved `jev_socket_path`;
3. `$XDG_RUNTIME_DIR/jev-gateway/jev.sock`;
4. `$XDG_RUNTIME_DIR/agent-lab/jev.sock`;
5. `$XDG_RUNTIME_DIR/jev.sock`.

Configure a nonstandard socket and verify the runtime:

```bash
omarchy-director configure --jev-socket /run/user/1000/jev-gateway/jev.sock
omarchy-director doctor
```

When Jev is unavailable, deterministic status, scene listing, and undo still work;
Director will not guess a new consequential plan.

## Usage

Open the palette and speak or type normally:

```text
move all terminals to workspace 3
make X 20% smaller
make the current window larger
move X to the left
open Slack on workspace 2
put Slack and Chromium side by side
take me to X
float ChatGPT
go to workspace 2
save this setup as deep-work
activate deep-work
move the terminals to workspace 4 and save as backend
toggle night light
silence notifications
raise volume 5 percent
change to the next wallpaper
take a fullscreen screenshot
remind me in 20 minutes to stretch
```

The preview updates as you type. Press **Enter** to execute, **Ctrl+Z** to undo the
latest reversible execution, and **Escape** to close.

Saved scenes appear on Director's home view as click-to-run entries. A scene stores
semantic application/window identity, workspace, tiled/floating/fullscreen state,
floating geometry, and the focused window. It never stores temporary window
addresses.

### CLI

```bash
omarchy-director status
omarchy-director plan --query 'put X and ChatGPT side by side'
omarchy-director diagnostics --limit 20
omarchy-director undo
omarchy-director history --limit 10

omarchy-director scenes save --name deep-work
omarchy-director scenes list
omarchy-director scenes apply --name deep-work
omarchy-director scenes update --name deep-work
omarchy-director scenes delete --name deep-work
```

See `omarchy-director --help` or `man omarchy-director` for the complete interface.

## Voice and YOLO

Voice preview is the public default:

```bash
omarchy-director-voice toggle --preview
```

Explicit YOLO asks Director to execute after transcription:

```bash
omarchy-director-voice toggle --yolo
```

YOLO does not bypass policy. Actions without a complete local undo boundary remain
in preview and require Enter. This includes application launches, scene application
that may launch apps, screenshots, recordings, reminders, audio-output switching,
wallpaper changes, and lock. Voice uses Voxtype's file-output mode and never types
into the application that currently has focus.

## Safety, privacy, and undo boundaries

Omarchy shell plugins are unsandboxed code running as your user. Review the source
before enabling any third-party plugin.

Director sends the user's command plus a compact inventory of window/application
candidates to the configured local Jev gateway. It does not send credentials,
clipboard contents, browser/page contents, environment variables, or arbitrary
files. Jev returns typed choices and never grants execution authority.

Execution uses a fixed action registry:

- desktop applications and themes come from live installed allowlists;
- window addresses and workspace values are validated before typed dispatch;
- numeric volume, brightness, duration, and message inputs are bounded;
- each plan is stored behind an expiring random token and rechecks stale windows;
- partial failures roll back the captured state when possible.

Undo is intentionally honest. It restores recorded local state, but does not close
newly launched applications or delete screenshots, recordings, or reminder
artifacts. See [SECURITY.md](SECURITY.md) for the complete trust model.

## Storage

Director follows XDG directories:

- configuration: `$XDG_CONFIG_HOME/omarchy-director/config.json`;
- scenes/history: `$XDG_STATE_HOME/omarchy-director/`;
- voice transients: `$XDG_RUNTIME_DIR/omarchy-director/`.

Configuration, scenes, history, and temporary transcripts use user-only
permissions. Removal preserves scenes and history unless the user deletes them.

## Update and removal

Update through Omarchy's reviewed fast-forward flow:

```bash
omarchy plugin update ieltxu.director
```

Remove optional integrations first, while the checkout still exists:

```bash
cd ~/.config/omarchy/plugins/ieltxu.director
./uninstall.sh
omarchy plugin remove ieltxu.director
```

The uninstall script removes only artifacts it can identify as Director-managed,
moves the man page/desktop entry and binding backup into Director's state directory,
and leaves scenes and history intact.

## Troubleshooting

Run:

```bash
omarchy-director doctor
omarchy plugin validate ~/.config/omarchy/plugins/ieltxu.director
omarchy plugin list --json | jq '.[] | select(.id == "ieltxu.director")'
journalctl --user --since '10 minutes ago' | grep -i director
```

- **No plan:** verify the Jev socket and local gateway with `doctor`.
- **CLI not found:** run the optional `./install.sh` or use
  `~/.config/omarchy/plugins/ieltxu.director/bin/omarchy-director` directly.
- **Voice unavailable:** install Voxtype and verify an input source; text mode is
  independent of voice.
- **Shortcut missing:** shortcuts are optional; run `./install.sh --bindings`.
- **Theme name rejected:** use an exact value from `omarchy theme list`.

## Development and release

```bash
./tests/director-lab fast
./tests/director-lab stress
```

The fast suite runs unit, policy, voice-adapter, packaging, Python compile, JSON,
shell-syntax, and symlink checks, including more than 5,000 generated desktop
states and action sequences. The stress gate raises that deterministic population
to at least 10,000 cases. Replay any failure with its reported seed:

```bash
DIRECTOR_GENERATIVE_SEED=20260919 DIRECTOR_GENERATED_CASES=10000 \
  ./tests/director-lab stress
```

Two explicit gates exercise real integrations and therefore do not run in the
portable GitHub job:

```bash
# Real pinned Jev; plans against a synthetic desktop and never executes them.
./tests/director-lab semantic --report ~/.local/state/omarchy-director/semantic-report.json

# Real Omarchy/Hyprland; owns only two Foot fixtures on reserved workspaces 91-92.
./tests/director-lab live --report ~/.local/state/omarchy-director/e2e-report.json
```

The live runner aborts if its workspaces are occupied or stale fixtures exist,
checks the effect and exact undo after every case, kills only processes it started,
and restores the previously focused workspace. On Omarchy the fast suite also
invokes the native plugin validator. A release requires all four gates plus bar,
F10, and one real microphone smoke test when voice behavior changed.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), and
[SECURITY.md](SECURITY.md).

## License

MIT © 2026 Ieltxu. See [LICENSE](LICENSE).
