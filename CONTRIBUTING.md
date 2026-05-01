# Contributing

Thanks for taking the time to contribute to Actions Monitor.

This document covers how to file issues, propose changes, and get a pull request merged. For local dev setup, building binaries, and the release pipeline, see [DEVGUIDE.md](DEVGUIDE.md). For deep architecture (threading model, file layout, config resolution, visual system), see [CLAUDE.md](CLAUDE.md).

By participating in this project you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs

Open a [GitHub issue](https://github.com/WizX20/ActionsMonitor/issues/new) with:

- What you did (steps to reproduce)
- What you expected
- What happened (logs, screenshot, full text of any error dialog)
- Your OS + Actions Monitor version (shown in the app footer)
- The relevant slice of `config.yaml` — **redact your `github_token`**

If you can reproduce on the latest binary from [Releases](https://github.com/WizX20/ActionsMonitor/releases/latest), say so.

## Suggesting features

Open an issue describing the use case before writing code. Small fixes and tweaks can go straight to a PR, but anything that touches the config schema, polling logic, or the visual system benefits from a short design discussion first so the PR doesn't bounce on architectural feedback.

## Security issues

Do **not** open a public issue for security-sensitive bugs. Use GitHub's [private security advisory](https://github.com/WizX20/ActionsMonitor/security/advisories/new) on this repo instead.

## Submitting a pull request

1. Fork the repo and create a topic branch off `main`.
2. Make your change. Keep the diff focused — one concern per PR.
3. Test on Windows. If your change touches Linux paths, notification rendering, the tray icon, or the update flow, test on Linux as well. PR mode, actor mode, and URL mode each have different code paths — exercise the one you touched.
4. Update [`CHANGELOG.md`](CHANGELOG.md) — append a new dated entry at the top of the list for any user-visible change. Never edit existing entries.
5. Update [`config.template.yaml`](config.template.yaml) if you added or changed a config option, with a comment explaining what it does and a sensible default.
6. Push and open a PR against `main`. Reference any related issue (`Fixes #123`).

GitHub Actions builds Windows + Linux binaries on every PR — make sure both jobs pass before requesting review.

### Branch naming

- `feature/<short-description>` — new functionality
- `fix/<short-description>` — bug fixes
- `chore/<short-description>` — refactors, build/CI, docs, dependency bumps

### Commit messages

- Imperative subject, ≤72 characters, no trailing period (`Add staleness badge`, not `Added staleness badge.`).
- Optional `feat:` / `fix:` / `chore:` prefix when it adds clarity — match the existing `git log` style.
- Body (when needed): wrap at 72 columns, explain **why** more than what.
- Create new commits — do not amend or force-push published commits.
- Do not skip pre-commit hooks (`--no-verify`) or signing.

### Code style

- The codebase is split between `src/main.py` (config, pollers, widgets, MainWindow, notifications, update flow) and `src/icons.py` (PIL icon rendering + Qt pixmap caches). Within `main.py`, keep the layout: constants → helpers → classes → `main()`. New low-coupling chunks are candidates for their own module — keep `icons.py`'s pattern of self-contained, no-circular-import design.
- 4-space indentation, `snake_case` for functions and variables, `PascalCase` for classes.
- Type hints encouraged but not required; match the surrounding style.
- All GitHub API calls go through `_github_api_get` / `_gh_headers`. Never call `requests.get` against `api.github.com` directly — you'll bypass ETag, cooldown, 401 invalidation, and rate-limit handling.
- Never call widget methods from poller threads. Pollers emit `StatusEvent`s onto a queue; the Qt main thread drains it via `_drain_queue`.
- No new top-level dependencies without discussion — every added wheel grows the PyInstaller bundle.
- Never edit `config.yaml` directly while developing; edit `config.template.yaml` and apply the change to your own config by hand.

## Releasing

Maintainers only. See [DEVGUIDE.md → Release process](DEVGUIDE.md#release-process).

## Licence

By contributing you agree that your contribution is licensed under the [WizX20 Free Use License](LICENSE), and that the [NOTICE](NOTICE) file is preserved in any redistribution.
