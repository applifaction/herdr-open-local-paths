<div align="center">

# Herdr Local Path Actions

**Open the files your terminal talks about.**

[![Herdr 0.7.4+](https://img.shields.io/badge/Herdr-0.7.4%2B-blue)](https://herdr.dev)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[Quick start](#quick-start) · [Usage](#usage) · [LibreOffice focus](#libreoffice-focus-on-linuxx11) · [Troubleshooting](#troubleshooting)

</div>

A [Herdr](https://herdr.dev) plugin for opening, revealing, and copying local files from terminal output. Ctrl-click a file link, or choose from a compact picker—without copying a path into another application.

This is an independently maintained fork of [yigitkg/herdr-open-local-paths](https://github.com/yigitkg/herdr-open-local-paths). It adds file-URI and symlink safety fixes plus document-aware LibreOffice window activation. It uses Herdr's plugin API; no Herdr, terminal, or coding-agent patches are required.

![Local path picker showing generated files](docs/path-picker.svg)

## Features

- **Ctrl-click file links:** open explicit `file://` or relative-path hyperlinks with the default application.
- **Pick recent files:** scan recent pane output; handle one existing path directly or show a picker when several are found.
- **Open, reveal, or copy:** files appear before folders, with repeated paths deduplicated.
- **Recognize common formats:** absolute and relative paths, file URIs, quoted paths, Markdown destinations, and source references such as `src/main.py:42`.
- **Bring the right document forward:** optional Linux/X11 support identifies an open LibreOffice document by its full URI, not just its filename.
- **Keep guards in place:** argument arrays instead of shell interpolation, executable-file checks, and remote-pane precautions. See [the security model](SECURITY.md).

## Quick start

### Requirements

| Environment | Requirements |
| --- | --- |
| Linux | Herdr **0.7.4+**, Python **3.10+** as `python3`, and `xdg-open` |
| WSL | Herdr **0.7.4+**, Python **3.10+** as `python3`, and Windows Explorer interop |
| Native Windows | Herdr **0.7.4+**, Python **3.10+** as `python` |

Core path actions use the Python standard library. The optional LibreOffice focus adapter has [additional desktop dependencies](#libreoffice-focus-on-linuxx11). macOS is not declared supported.

### Link a checkout

From the root of this repository on Linux or WSL:

```bash
herdr plugin link "$PWD"
herdr plugin action list --plugin yigitkg.local-path-actions
```

On native Windows, link the Windows manifest:

```powershell
herdr plugin link (Resolve-Path .\windows\herdr-plugin.toml).Path
```

> [!IMPORTANT]
> This fork retains the plugin ID `yigitkg.local-path-actions` for shortcut compatibility. Use either the upstream plugin or this fork, not both. Unlink a previous local checkout or uninstall a previous managed installation before switching sources.

### Install from GitHub

Once this fork is published at `applifaction/herdr-open-local-paths`:

```bash
# Linux / WSL
herdr plugin install applifaction/herdr-open-local-paths --ref master

# Native Windows
herdr plugin install applifaction/herdr-open-local-paths/windows --ref master
```

For reproducible installations, replace `master` with a reviewed commit or release tag. No build step is required. Herdr registers plugins for the current user across sessions.

## Usage

### Ctrl-click a file link

Use a destination in output from an application that renders terminal hyperlinks, such as pi:

```markdown
[Open report](file:///home/me/reports/quarterly%20report.csv)
[Project report](reports/quarterly%20report.csv)
[Preview](./output/preview.png)
[Readme](README.md)
```

**Ctrl-click** the label in Herdr. Relative links use the clicked pane's current working directory, falling back to the workspace directory only when the pane directory is unavailable. They never use the plugin's own directory or search other directories when a file is missing. Herdr must identify the pane as local; unknown or remote panes are refused.

Relative URL paths are percent-decoded once. Query strings and fragments are ignored when opening the local file; encode literal `#` and `?` in filenames as `%23` and `%3F`. HTTP(S), other URL schemes, network URLs and anchor-only links are not claimed by the relative-path handler. Absolute `file:///…` links remain the most reliable choice if the pane's working directory may change.

> [!NOTE]
> Clicks require an actual terminal hyperlink (OSC 8), not just path-shaped text. Use the recent-path picker for plain paths. Missing files are not created or downloaded.

After updating an already linked checkout, refresh the registered manifest once:

```bash
herdr plugin link /path/to/herdr-open-local-paths
```

No pi or Herdr restart is needed; existing terminal hyperlinks also use the refreshed handler.

### Add picker shortcuts

Add these optional bindings to your Herdr configuration, then reload it:

```toml
[[keys.command]]
key = "prefix+alt+o"
type = "plugin_action"
command = "yigitkg.local-path-actions.open-latest-path"
description = "open a recent local path"

[[keys.command]]
key = "prefix+shift+o"
type = "plugin_action"
command = "yigitkg.local-path-actions.reveal-latest-path"
description = "show a recent path in its folder"
```

```bash
herdr server reload-config
```

These actions inspect the focused pane's last **120 lines** by default. In the picker, use **↑/↓** or **j/k**, then **Enter**. **Esc** or **q** cancels. The initiating shortcut determines whether Enter opens, reveals, or copies the selection.

Additional actions include `copy-latest-path`, `open-path`, `reveal-path`, and `copy-resolved-path`. The non-`latest` actions use Herdr's selected text or clicked URL. List available actions with `herdr plugin action list --plugin yigitkg.local-path-actions`.

For scanned paths containing spaces, use quotes, backticks, or a Markdown destination:

```text
./output/report.csv
`/home/me/My Reports/final report.xlsx`
[report](</home/me/My Reports/final report.xlsx>)
C:\Users\me\Desktop\chart.png
```

## LibreOffice focus on Linux/X11

An open request can succeed while an existing Calc window stays behind the terminal. This fork adds a bounded, optional activation step:

1. Confirm that LibreOffice is the default application for the file type.
2. Read the full document URI from LibreOffice's AT-SPI accessibility metadata.
3. Require an exact canonical-path match and an unambiguous frame/window mapping.
4. Activate that window through X11.

It does **not** guess from a filename or choose the first matching window. Missing information, duplicate matches, or unavailable dependencies leave normal file opening unchanged.

The adapter requires `xdotool`, Python GI with Gio and AT-SPI introspection, and normally `/usr/bin/python3`. It does not run on Wayland, WSL, or Windows. See [setup, verification, and limitations](docs/libreoffice-focus.md).

## Safety and configuration

> [!WARNING]
> Terminal output is untrusted input. The plugin runs with your user permissions and is not a sandbox or malware scanner. Only open files you trust. Document contents and application behavior are outside its guarantees.

The open action refuses high-risk extensions, POSIX executables—including through file URIs—and risky POSIX symlink targets. Recognized SSH, Mosh, and container-exec panes are refused for open/reveal. Unknown pane locality blocks relative paths; remote detection cannot identify every nested setup.

Optional environment settings must be available to the plugin process:

| Variable | Purpose |
| --- | --- |
| `LOCAL_PATH_ACTIONS_SCAN_LINES` | Recent-output scan length; default `120`, bounded to `20–500` |
| `LOCAL_PATH_ACTIONS_DRY_RUN=1` | Report platform open/reveal commands without launching them; not a general no-side-effects mode for every action |

Expert overrides are documented in [SECURITY.md](SECURITY.md). Keep them disabled for normal use. Store machine-local configuration outside the source checkout.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Ctrl-click does nothing | Confirm enabled `file-url` / `relative-path` handlers, an actual terminal hyperlink, and an existing destination. Re-link the checkout after manifest updates. |
| Picker has no files | Ensure the path appeared recently and exists locally. Quote paths containing spaces. |
| File opens behind the terminal | Check the optional focus adapter's [dependencies and scope](docs/libreoffice-focus.md). |
| Open is refused | Check executable permissions, file type, symlink target, and pane locality. Reveal the file instead of disabling safeguards. |
| Clipboard action fails | Install a platform clipboard helper; the plugin also prints the resolved path. |

```bash
herdr plugin list --plugin yigitkg.local-path-actions --json
herdr plugin log list --plugin yigitkg.local-path-actions --limit 10
```

Diagnostic actions `diagnose` and `diagnose-latest-path` report resolution details. Their output can contain local paths or selected text; review it before sharing.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/local_path_actions.py src/libreoffice_focus.py src/path_picker.py
```

Use `python` on Windows. CI runs on pushes to `master` and on pull requests, with Linux and Windows jobs. Linux-only CLI tests replace desktop and accessibility boundaries with fakes; the automated suite does not launch GUI applications.

| Module | Responsibility |
| --- | --- |
| `src/local_path_actions.py` | Herdr context, path resolution, guards, and platform commands |
| `src/path_picker.py` | Interactive picker and private snapshot handling |
| `src/libreoffice_focus.py` | Optional exact-document Linux/X11 activation |

## Disable or remove

```bash
herdr plugin disable yigitkg.local-path-actions

# Unregister a linked checkout:
herdr plugin unlink yigitkg.local-path-actions

# Or remove a GitHub-managed installation:
herdr plugin uninstall yigitkg.local-path-actions
```
