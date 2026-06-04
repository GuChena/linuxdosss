# GUI Refactor Design

## Goal

Refactor the project structure without changing current behavior. The first pass should reduce the size and coupling of `src/linux_do_gui.py`, make pure logic easier to test, and keep the existing launcher, packaging flow, and public entry point working.

## Scope

This refactor is intentionally incremental. It will move stable, low-risk code out of the monolithic GUI file while leaving the browser automation flow and Tkinter screen construction mostly intact.

In scope:

- Create a focused `src/linux_do/` package.
- Move topic selection and reply-count filtering logic into a dedicated module.
- Move default configuration and category data into a dedicated module.
- Move small platform/resource helpers into a dedicated module.
- Keep `src/linux_do_gui.py` as the executable entry point.
- Re-export moved functions from `src/linux_do_gui.py` where existing tests or user scripts may already import them.
- Update tests so pure topic logic is tested directly from its new module.
- Add compatibility coverage for the old import surface.

Out of scope:

- Changing browser automation behavior.
- Changing GUI layout, text, default values, or runtime options.
- Rewriting `Bot` and `GUI` into many files in this pass.
- Changing the PyInstaller workflow beyond imports required by the new package.
- Adding new forum automation features.

## Architecture

The package will separate pure logic and static data from the Tkinter and DrissionPage runtime code:

- `src/linux_do/topics.py` owns topic payload filtering, merging, counting, and the JavaScript builder used to read topic rows.
- `src/linux_do/config.py` owns `VERSION`, `GITHUB_REPO`, default config values, and category defaults.
- `src/linux_do/resources.py` owns platform/resource helpers such as Linux input method setup, font selection, settings path, icon path, and tray image creation.
- `src/linux_do/__init__.py` provides a small package marker and may expose version metadata.
- `src/linux_do_gui.py` remains the CLI/GUI entry point and imports these modules. The `Bot` and `GUI` classes keep their current responsibilities for now.

This keeps the first refactor low risk: all browser state, callbacks, Tk widgets, and threading behavior stay in the same file.

## Component Boundaries

`topics.py` must have no dependency on Tkinter, DrissionPage, PIL, filesystem state, or network access. It should be importable in tests without monkeypatching external packages.

`config.py` should contain only static data and simple copy helpers if needed. Consumers should not mutate the module-level defaults directly when a runtime config copy is required.

`resources.py` may depend on `os`, `sys`, `platform`, and optionally PIL for tray image creation. It should avoid importing Tkinter or DrissionPage.

`linux_do_gui.py` should retain the executable behavior:

```bash
python src/linux_do_gui.py
```

It should also preserve the old top-level names used by tests:

- `parse_reply_count_range`
- `filter_topics_by_reply_count`
- `select_topic_candidates`
- `merge_topic_payloads`
- `count_topic_candidates`
- `build_get_topics_js`

## Data Flow

At startup, `linux_do_gui.py` imports static defaults from `linux_do.config` and platform helpers from `linux_do.resources`.

The GUI still collects user settings and persists them to `settings.json`. Runtime bot configuration still flows through the existing `cfg` dictionary.

When `Bot.get_topics()` scans a forum category, it still calls `build_get_topics_js()` and then filters/merges payloads through the same topic helper functions. Only the module location changes.

## Error Handling

The refactor should not change runtime error behavior. Existing broad exception handling can remain during this pass unless a moved pure function can be made clearer without changing returned values.

For topic parsing, existing fallback behavior must be preserved:

- Invalid reply range input returns the default range.
- Blank max reply count means unlimited.
- Missing or unparseable topic reply counts are skipped.
- `unread_only=True` never falls back to read topics.

## Testing

Testing must be test-first for new or moved behavior:

- Add direct tests for `linux_do.topics` before moving the implementation.
- Run the new tests and confirm they fail because the package/module does not exist yet.
- Move the topic helpers into `src/linux_do/topics.py` and confirm the direct tests pass.
- Add compatibility tests for the old `linux_do_gui.py` top-level function names before updating the compatibility imports.
- Run the full suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected final result: all tests pass.

## Packaging And Launch Compatibility

`start.bat` should continue to run:

```bat
%VENV_PY% "src\linux_do_gui.py"
```

No launcher change is expected.

PyInstaller should discover imports from `src/linux_do_gui.py`. If packaging needs explicit hidden imports for the new package, update `scripts/build.py`, `docs/BUILD_GUIDE.md`, and `.github/workflows/build-pyinstaller.yml` consistently.

## Risks

The main risk is accidental behavior drift from shared mutable defaults. To avoid this, config data should either preserve the same mutation model or provide explicit runtime copies where needed.

Another risk is import path behavior when running `python src/linux_do_gui.py`. The new package must live under `src/` so Python can import `linux_do` from the script directory.

## Success Criteria

- `src/linux_do_gui.py` is smaller and delegates topic/config/resource helpers to focused modules.
- Existing GUI startup command remains unchanged.
- Existing tests pass.
- New tests can import topic logic without loading DrissionPage.
- No functional behavior, default value, UI text, or browser automation flow changes in this pass.
