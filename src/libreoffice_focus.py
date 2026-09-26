#!/usr/bin/env python3
"""Optional Linux/X11 adapter for LibreOffice's background-open behavior.

The parent already validated/opened the file. Prove the full document URI through
AT-SPI first, then map one unambiguous accessibility frame to one X11 client using
PID + exact full frame title. Never use a filename/title as document identity.
The parent bounds this optional subprocess to four seconds. Missing dependencies
or uncertain mappings simply leave normal desktop opening unchanged.
"""
from collections import Counter, deque
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


def document_path(name: str) -> Path | None:
    # LibreOffice exposes '<full document URI> - <document role label>'. Split
    # from the right so a filename containing ' - ' cannot become a prefix match.
    uri = urlsplit(name.rsplit(" - ", 1)[0])
    if uri.scheme != "file" or uri.netloc.lower() not in ("", "localhost") or uri.query or uri.fragment:
        return None
    path = unquote(uri.path)
    if not path.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return None
    try:
        return Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def frame_has_document(frame, target: Path) -> bool:
    queue = deque([(frame, 0)])
    seen = 0
    while queue and seen < 100:
        node, depth = queue.popleft()
        seen += 1
        role = node.get_role_name()
        if role.startswith("document"):
            if document_path(node.get_name()) == target:
                return True
            continue  # Never inspect spreadsheet cells or document content.
        if role in ("menu bar", "menu", "tool bar", "table", "spreadsheet"):
            continue
        if depth >= 8:
            continue
        count = node.get_child_count()
        if count > 30:
            continue
        for index in range(count):
            queue.append((node.get_child_at_index(index), depth + 1))
    return False


def activate(path_text: str) -> bool:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, Gio

    target = Path(path_text).resolve(strict=True)
    if not target.is_file():
        return False
    file = Gio.File.new_for_path(str(target))
    info = file.query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
    app = Gio.AppInfo.get_default_for_type(info.get_content_type(), False)
    if app is None or not re.fullmatch(r"libreoffice[-_](calc|writer|impress|draw|math|base)\.desktop", app.get_id() or ""):
        return False

    Atspi.set_timeout(400, 400)
    desktop = Atspi.get_desktop(0)
    if desktop is None or desktop.get_child_count() > 128:
        return False
    matches = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if application.get_name().lower() not in ("soffice", "libreoffice"):
            continue
        pid = application.get_process_id()
        if pid <= 0 or application.get_child_count() > 64:
            return False
        frames = [application.get_child_at_index(i) for i in range(application.get_child_count())]
        titles = [frame.get_name() for frame in frames]
        counts = Counter(titles)
        for frame, title in zip(frames, titles):
            # Only a cheap prefilter. Identity MUST come from the document URI.
            if target.name not in title and Path(path_text).name not in title:
                continue
            if frame_has_document(frame, target):
                if counts[title] != 1:
                    return False
                matches.append((pid, title))
    if len(matches) != 1:
        return False
    pid, title = matches[0]
    search = subprocess.run(
        ["xdotool", "search", "--all", "--pid", str(pid), "--name", "^" + re.escape(title) + "$"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, timeout=1,
    )
    windows = list(dict.fromkeys(search.stdout.split()))
    if search.returncode != 0 or len(windows) != 1 or not re.fullmatch(r"[0-9]+", windows[0]):
        return False
    result = subprocess.run(
        ["xdotool", "windowactivate", "--sync", windows[0]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1,
    )
    return result.returncode == 0


def main() -> int:
    if (len(sys.argv) != 2 or sys.platform != "linux" or not os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland"
            or os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")
            or os.environ.get("LOCAL_PATH_ACTIONS_DRY_RUN") == "1"):
        return 3
    try:
        return 0 if activate(sys.argv[1]) else 3
    except Exception:
        # Optional desktop IPC must never prevent the validated file opening.
        # Do not log accessibility metadata of other documents/applications.
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
