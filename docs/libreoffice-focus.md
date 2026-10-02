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
3. Before `xdg-open`, the adapter records a conservative set of every X11 window
   with the complete title expected for that filename and LibreOffice application
   role. Snapshot lookup errors disable the absent-URI fallback instead of becoming
   an empty snapshot.
4. After opening, the adapter inspects candidate LibreOffice accessibility frames.
   It first reads the document URI from a document node's accessible name, without
   inspecting spreadsheet cells or document contents.
5. When a document URI is present, its canonical local path must equal the requested
   file's canonical path. Conflicting, invalid or incompletely traversed URI metadata
   is never bypassed.
6. Some LibreOffice Writer views expose no URI. Only in that absent-URI case, the
   adapter requires the accessibility process to hold the exact canonical target
   open through `/proc/<pid>/fd`. An already-open window is eligible only when its
   X11 id was remembered from a prior successful URI-authoritative or newly-opened
   activation and is revalidated against the current unique frame. Without such a
   remembered mapping, only a newly matching window absent from the pre-open
   snapshot is eligible.
7. There must be exactly one matching frame, with no duplicate frame title in its
   application, and exactly one eligible X11 client matching that process ID and
   complete frame title.
8. Only that client receives an X11 activation request.

The parent limits the helper to four seconds. Accessibility traversal and native
command calls are bounded. No ambiguous-window fallback is used.

## Limits

- The adapter does not run on Wayland, WSL or Windows. Normal opening remains
  available on supported platforms.
- It is specifically for LibreOffice, not a generic foreground-window manager.
  Default desktop IDs must match the supported `libreoffice-…` or
  `libreoffice_…` forms; custom launchers may not be recognized.
- Missing GI bindings, an unavailable accessibility bus, unavailable procfs proof,
  incomplete snapshots, duplicate windows or no matching document produce a no-op,
  not a guessed focus target. The default opener is still used.
- Successful window mappings are stored in Herdr's private plugin state directory,
  capped to 64 entries, and revalidated before reuse. A stale mapping fails closed.
- A document that has not appeared in the accessibility tree yet may not be
  activated. There is no long-running watcher or background retry service.
- Filesystem and window state can change between the pre-open snapshot, opening and
  activation. The before/after comparison fails closed for pre-existing same-title
  windows but is not an atomic desktop transaction or a content-security boundary.

## Verify the behavior

On a local X11 desktop, open a harmless document in LibreOffice, switch back to a
Herdr terminal, and Ctrl-click its absolute `file://` hyperlink. Check that the
same document becomes foreground—not merely that the launcher exits successfully.

```bash
herdr plugin log list --plugin yigitkg.local-path-actions --limit 10
```

An applied activation emits `Activated the matching document window.` in the
action log. A successful action without that message may simply have used the
normal opener; it is not proof of foreground activation. On systems where Writer
exposes no AT-SPI document URI, exact `/proc/<pid>/fd` access must be available for
the fallback identity check.

The automated CLI tests use fake GI/AT-SPI, procfs evidence and X11 boundaries.
They cover full URI identity, conflicting/invalid URI metadata, the absent-URI
before/after fallback, same-named files in different directories, pre-existing
same-title windows, misleading filename prefixes, ambiguous frames/windows,
missing metadata and platform exclusions without opening real applications:

```bash
python3 -m unittest discover -s tests -p test_desktop_activation_cli.py -v
```
