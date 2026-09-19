# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Reversible, bounded resizing for one clearly identified window, including
  natural references such as `make X smaller` and `make this window 20% larger`.
- Reversible directional swaps such as `move X to the left`.
- Exact installed-app launch and placement such as `open Slack on workspace 2`.
- Local diagnostics for recent plans, rejections, gateway failures, and history.

### Fixed

- GUI launches detach inherited pipes so Electron applications cannot leave
  Director waiting for the application to exit.
- Exact installed app names no longer depend on a probabilistic app-selection vote.

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

[Unreleased]: https://github.com/ieltxu/omarchy-director/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ieltxu/omarchy-director/releases/tag/v2.0.0
[1.0.0]: https://github.com/ieltxu/omarchy-director/releases/tag/v1.0.0
