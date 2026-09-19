# Contributing

Director keeps semantic interpretation and authority separate: Jev may select
only from typed candidates, while deterministic code validates and executes an
exact action. Contributions must preserve that boundary.

Director is an experimental, AI-assisted/vibe-coded release candidate. Keep
customization declarative and local-first: do not add telemetry, arbitrary shell
hooks, or claims of marketplace verification.

Before opening a pull request:

1. Run `./tests/director-lab fast` and `./tests/director-lab stress`.
2. Add regression coverage for changed routing, persistence, or execution.
3. Validate the checkout with `omarchy plugin validate .` on Omarchy.
4. Run `./tests/director-lab semantic` when routing changes and
   `./tests/director-lab live` when execution or undo changes.
5. Update `CHANGELOG.md` for user-visible behavior.

Never add prompt-produced shell, credential forwarding, implicit configuration
overwrites, or an irreversible action to YOLO's allowlist.
