# Security policy

## Trust model

Omarchy shell plugins are unsandboxed code loaded into the long-running
`omarchy-shell` process. Review this repository before enabling it. Director
also runs its bundled Python executables as your user; it never uses `sudo`.

Director sends a compact desktop inventory and the user's command to the
configured local Jev gateway. It does not send clipboard contents, page
contents, credentials, environment variables, or arbitrary files. Jev returns
typed choices only. Director collects no telemetry. All permissions, allowlists,
bounds, and exact command arguments are enforced locally.

Common credential shapes and assignments are rejected before provider calls and
redacted before persistence. Pattern matching is not a universal secret scanner:
never place credentials or private configuration in a Director command.

Provider adapters own only credential naming and construction of the upstream
typed Decisions request. Their endpoint and pinned model are reviewed code, not
user-provided URLs, so configuration cannot redirect a credential elsewhere.
File mode 0600 and the private Unix socket isolate other OS users, not other
unsandboxed plugins running under the same account. Use a dedicated OpenRouter
key with the lowest practical spending/rate limits.

Voice mode delegates transcription to the separately installed `voxtype`
command. Director stores the temporary transcript under `$XDG_RUNTIME_DIR` with
user-only access and removes it after use. A custom microphone helper runs only
when explicitly configured through `DIRECTOR_MIC_CONTROL_BIN`.

## Execution boundaries

- No prompt text is evaluated as shell.
- Customization is declarative; arbitrary shell hooks are not supported.
- Application launches are restricted to installed desktop entries.
- Themes are restricted to `omarchy theme list`.
- Window and workspace operations use validated Hyprland typed dispatchers.
- Numeric changes are bounded.
- YOLO autoexecution is limited to actions with a complete local undo path.
  Hard safety validation cannot be bypassed by YOLO.
  Launches, scene application that may launch apps, screenshots, recording,
  reminders, output switching, wallpaper changes, and lock require Enter.

Some actions still have effects outside Director's history once explicitly
confirmed, such as files created by screenshots or recordings. The preview names
those actions; undo never claims to delete external artifacts.

The live E2E runner is fixture-owned: it refuses occupied reserved workspaces,
creates uniquely classified Foot windows, mutates only their validated addresses,
terminates only the process groups it created, and restores the previous focused
workspace. The semantic evaluator uses a synthetic desktop and never executes a
Jev-produced plan.

## Reporting a vulnerability

Do not open a public issue for an undisclosed vulnerability. Use GitHub's private
security advisory flow for `ieltxua/omarchy-director` and include the affected
version, reproduction steps, impact, and any suggested mitigation.
