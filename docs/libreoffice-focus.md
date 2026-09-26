# LibreOffice focus on Linux/X11

An open request can succeed without bringing an already-open document in front of
the terminal. Herdr runs plugin actions in a background process; the normal
`xdg-open` handoff does not guarantee foreground activation.

This fork provides an optional adapter for that case. It does not change the
default application or replace normal file opening.

## Requirements

- Native Linux with an X11 desktop session and `DISPLAY`.
- `xdotool` on the plugin process's `PATH`.
- System Python with GI, Gio and the AT-SPI 2 introspection typelib.
- LibreOffice configured as the default application for the file type.
- A running accessibility bus exposing LibreOffice's document metadata.

Check desktop bindings independently from a virtualenv:

```bash
/usr/bin/python3 -c 'import gi; gi.require_version("Atspi", "2.0"); from gi.repository import Atspi, Gio; print("Desktop bindings available")'
command -v xdotool
```

Install missing dependencies through your distribution's package manager. The
plugin never installs them automatically. It prefers `/usr/bin/python3` for this
adapter because a virtualenv used to run Herdr may not contain distribution-provided
GI bindings. If that interpreter is absent, it uses the plugin's interpreter.

## Document identity before window activation

1. The normal plugin path guards run before the file is opened.
2. Gio confirms the file's default desktop application is a supported LibreOffice
   application: Calc, Writer, Impress, Draw, Math or Base.
3. The adapter inspects candidate LibreOffice accessibility frames. It reads the
   document URI from a document node's accessible name, not spreadsheet cells or
   document contents.
4. The URI's canonical local path must equal the requested file's canonical path.
   A filename prefix or matching basename is insufficient.
5. There must be exactly one matching frame, with no duplicate frame title in its
   application, and exactly one X11 client matching that process ID and complete
   frame title.
6. Only that client receives an X11 activation request.

The parent limits the helper to four seconds. Accessibility traversal and native
command calls are bounded. No ambiguous-window fallback is used.

## Limits

- The adapter does not run on Wayland, WSL or Windows. Normal opening remains
  available on supported platforms.
- It is specifically for LibreOffice, not a generic foreground-window manager.
  Default desktop IDs must match the supported `libreoffice-…` or
  `libreoffice_…` forms; custom launchers may not be recognized.
- Missing GI bindings, an unavailable accessibility bus, incomplete metadata,
  duplicate windows or no matching document produce a no-op, not a guessed focus
  target. The default opener is still used.
- A document that has not appeared in the accessibility tree yet may not be
  activated. There is no long-running watcher or background retry service.
- Filesystem and window state can change between observation and activation.
  This adapter is not an atomic desktop transaction or a content-security boundary.

## Verify the behavior

On a local X11 desktop, open a harmless document in LibreOffice, switch back to a
Herdr terminal, and Ctrl-click its absolute `file://` hyperlink. Check that the
same document becomes foreground—not merely that the launcher exits successfully.

```bash
herdr plugin log list --plugin yigitkg.local-path-actions --limit 10
```

An applied activation emits `Activated the matching document window.` in the
action log. A successful action without that message may simply have used the
normal opener; it is not proof of foreground activation.

The automated CLI tests use fake GI/AT-SPI and X11 boundaries. They cover full URI
identity, same-named files in different directories, misleading filename prefixes,
ambiguous frames/windows, missing metadata and platform exclusions without opening
real applications:

```bash
python3 -m unittest discover -s tests -p test_desktop_activation_cli.py -v
```
