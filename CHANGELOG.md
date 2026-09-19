# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

- Add typed, reversible global Hyprland styling for gaps, border size, opacity,
  blur, shadows, inactive-window dimming, animations, and five composable presets.
- Restrict visual configuration to a bounded property registry, verify every live
  effect, and automatically restore the observed values when verification fails.
- Add an exhaustive 331-phrase bilingual semantic suite covering 78 behavior
  families, exact plan parameters, automatic-execution policy, ambiguity, and
  unsupported or unsafe near-misses.
- Add installed-API auditing across 445 Omarchy commands and Hyprland's command
  surface, including supported mappings, available opportunities, and policy exclusions.
- Add bounded pacing, family filtering, and separately reported infrastructure
  retries so provider failures cannot be mistaken for semantic regressions.
- Route obvious native commands and explicit window intents deterministically,
  including multilingual resize, arrange, tiling, audio, capture, reminder,
  idle, lock, and window-rounding phrases.
- Reject screen OCR and external messaging explicitly instead of allowing them
  to collide with screenshot planning.
- Record release-gate results: 331/331 semantic cases after bounded failed-family
  reruns, 21/21 capability mappings, 10,000 generated desktop cases, and 11/11
  live Omarchy compositor cases with exact effect and undo; palette and microphone
  smoke tests remain manual release gates.

## [2.1.0-rc.5] - 2026-09-19

- Add reversible global Hyprland window rounding for rounded, more-rounded,
  square, and explicit pixel requests using the Lua runtime configuration API.
- Route explicit window-appearance requests deterministically so obvious visual
  commands do not depend on a probabilistic top-level classification.
- Expand real Jev acceptance to 28/28 semantic cases and live Hyprland
  acceptance to 9/10; the new rounding case verifies effect and exact undo.

## [2.1.0-rc.4] - 2026-09-19

- Target resize and directional tile swaps by exact window identity instead of
  depending on compositor focus side effects.
- Restore tiled layouts on their original visible workspace before rebuilding
  slot order, then return to the previously active workspace.
- Record the live Omarchy acceptance result: 8/9 effects and exact undos pass;
  exact focus remains pending validation with an active input seat.

## [2.1.0-rc.3] - 2026-09-19

- Wait for Hyprland focus acknowledgement before focus-dependent resize and
  tile-swap dispatches, failing closed when the compositor does not confirm it.

## [2.1.0-rc.2] - 2026-09-19

- Accept the existing Agent Lab gateway's authenticated `/health/ready`
  contract when the dedicated zero-inference upstream probe is unavailable.

## [2.1.0-rc.1] - 2026-09-19

This experimental release candidate documents the permanent plugin identity,
0BSD licensing, local-first/no-telemetry posture, and the native Omarchy install
and setup path. It is AI-assisted/vibe-coded and is not marketplace-verified.

### Added

- Reversible, bounded resizing for one clearly identified window, including
  natural references such as `make X smaller` and `make this window 20% larger`.
- Reversible directional swaps such as `move X to the left`.
- Exact installed-app launch and placement such as `open Slack on workspace 2`.
- Local diagnostics for recent plans, rejections, gateway failures, and history.
- Director Lab with seed-reproducible high-volume desktop simulation, a versioned
  bilingual Jev contract corpus, voice policy tests, and isolated live Omarchy E2E.
- CI coverage for Python 3.10 and 3.12 plus a 10,000-case stress gate.
- A bundled, pinned Jev/OpenRouter gateway with private Unix socket, systemd user
  service, rate/capacity limits, secret-field rejection, and one-command setup.
- Declarative app/window aliases, voice defaults, and a user-narrowable YOLO
  allowlist that cannot expand the compiled safety boundary.
- A provider-adapter boundary that keeps gateway IPC, typed validation, and
  policy stable while provider authentication and endpoints evolve independently.

### Changed

- YOLO eligibility is now computed by the Python plan model and serialized for
  the shell UI, keeping the tested policy boundary out of presentation code.

### Fixed

- GUI launches detach inherited pipes so Electron applications cannot leave
  Director waiting for the application to exit.
- Exact installed app names no longer depend on a probabilistic app-selection vote.
- Direct navigation such as `llevame a X` resolves to focus instead of workspace
  relocation when a unique window is named.
- Native commands beginning with `activate`/`activa` are no longer mistaken for
  missing scenes.
- Word-form resize percentages and Spanish reminder units retain their exact
  numeric amount and message.
- Undo restores the original relative tiled slot after moving a window between
  workspaces, and transient Jev 5xx failures receive one bounded retry.

## [2.0.0] - 2026-09-19

### Added

- Address-free named scenes with capture, update, list, apply, delete, launch of
  identifiable missing apps, and deterministic duplicate-window matching.
- Typed native capabilities for workspaces, window state, themes, audio,
  brightness, capture, reminders, idle behavior, and lock.
- Composed natural-language actions such as `float ChatGPT and save as review`.
- State-aware undo for workspaces, windows, scenes, themes, volume, and brightness.
- `doctor`, `configure`, and `--version` CLI surfaces.
- Public man page, optional user-integration installer, security policy, and CI.

### Changed

- Public installation now follows Omarchy's native git-plugin workflow.
- Voice preview is the default from the bar. YOLO refuses to autoexecute plans
  that do not have a complete undo boundary.
- Jev socket discovery supports environment, user configuration, and standard
  runtime locations instead of assuming one personal path.

## [1.0.0] - 2026-09-18

- Initial theme-native Director with typed Jev planning, Hyprland execution,
  preview, history, rollback, undo, bar entry, launcher, and voice adapter.

[Unreleased]: https://github.com/ieltxua/omarchy-director/compare/v2.1.0-rc.5...HEAD
[2.1.0-rc.5]: https://github.com/ieltxua/omarchy-director/compare/v2.1.0-rc.4...v2.1.0-rc.5
[2.1.0-rc.4]: https://github.com/ieltxua/omarchy-director/compare/v2.1.0-rc.3...v2.1.0-rc.4
[2.1.0-rc.3]: https://github.com/ieltxua/omarchy-director/compare/v2.1.0-rc.2...v2.1.0-rc.3
[2.1.0-rc.2]: https://github.com/ieltxua/omarchy-director/compare/v2.1.0-rc.1...v2.1.0-rc.2
[2.1.0-rc.1]: https://github.com/ieltxua/omarchy-director/releases/tag/v2.1.0-rc.1
[2.0.0]: https://github.com/ieltxua/omarchy-director/releases/tag/v2.0.0
[1.0.0]: https://github.com/ieltxua/omarchy-director/releases/tag/v1.0.0
