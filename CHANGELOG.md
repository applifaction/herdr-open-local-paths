# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- Optional Linux/X11 LibreOffice foreground activation, using the full document URI from AT-SPI and an unambiguous frame/window mapping.
- Black-box CLI regression tests for file-link safety and desktop activation without launching real GUI applications.

### Fixed

- POSIX executable-file checks also apply to local `file://` links.
- POSIX symlink targets cannot bypass the risky-extension check through an innocuous link name.
- Added manifest regression coverage so the sized path picker cannot use an unsupported non-popup placement or lower its required Herdr runtime contract.

### Changed

- Public-facing setup, usage, safety and troubleshooting documentation for this fork.
- CI runs on `master` and compiles the optional activation helper.
- Machine-local installation notes, diagnostic artifacts and agent runtime data are excluded from version control.

## [0.4.0] - 2026-07-18

### Added

- Native Windows manifest and documented installation path.
- Native Windows CI coverage with Python 3.12.

### Changed

- File rows in the picker now show the complete path, matching folder rows.
- Native Windows subprocess output is decoded consistently as UTF-8.
- PowerShell prompt working directories are excluded from detected output paths.
- The picker recognizes the native Windows Escape key sequence.

## [0.3.0] - 2026-07-18

### Added

- Adaptive picker for multiple existing files and folders.
- Quoted, backticked, Markdown-linked, Windows, WSL, POSIX, and relative path detection.
- File-first ordering, deduplication, source excerpts, and plain-language item labels.
- Remote-pane checks for SSH, Mosh, and common container exec commands.
- Automated tests and release CI.

### Changed

- The launch shortcut now determines the picker's Enter action.
- Initial supported platform claim is limited to Linux and WSL.
- Popup size is reduced to 75% width and 55% height.

### Security

- Risky extensions and extensionless POSIX executables are refused by open.
- Win32 trailing-dot, trailing-space, and alternate-data-stream aliases are refused.
- Network path checks, subprocess calls, clipboard calls, and picker snapshots are bounded.
- Decoded file URLs and terminal control sequences are validated before use.

[Unreleased]: https://github.com/applifaction/herdr-open-local-paths/compare/ce94304...master
[0.4.0]: https://github.com/yigitkg/herdr-open-local-paths/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/yigitkg/herdr-open-local-paths/releases/tag/v0.3.0
