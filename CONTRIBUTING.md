# Contributing

Director keeps semantic interpretation and authority separate: Jev may select
only from typed candidates, while deterministic code validates and executes an
exact action. Contributions must preserve that boundary.

Before opening a pull request:

1. Run `./tests/run`.
2. Add regression coverage for changed routing, persistence, or execution.
3. Validate the checkout with `omarchy plugin validate .` on Omarchy.
4. Exercise changed UI or Hyprland behavior against a disposable window and
   verify readback plus undo.
5. Update `CHANGELOG.md` for user-visible behavior.

Never add prompt-produced shell, credential forwarding, implicit configuration
overwrites, or an irreversible action to YOLO's allowlist.
