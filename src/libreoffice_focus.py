#!/usr/bin/env python3
"""Optional Linux/X11 adapter for LibreOffice's background-open behavior.

The parent validates the file and captures an X11 snapshot before opening it.
Activation prefers a full AT-SPI document URI. Some LibreOffice views expose no
URI; for those, a before/after window comparison prevents a process-wide open
file descriptor from being mistaken for frame-specific identity. Missing or
uncertain evidence leaves normal opening unchanged.
"""
from collections import Counter, deque
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


LIBREOFFICE_APP_RE = re.compile(
    r"libreoffice[-_](calc|writer|impress|draw|math|base)\.desktop"
)
MAX_NATIVE_WINDOWS = 32
MAX_ACCESSIBLE_NODES = 200
MAX_ACCESSIBLE_DEPTH = 16
MAX_ACCESSIBLE_CHILDREN = 50
WINDOW_CACHE_FILENAME = "libreoffice-window-map.json"
MAX_WINDOW_CACHE_ENTRIES = 64


def document_path(name: str) -> Path | None:
    # LibreOffice exposes '<full document URI> - <document role label>'. Split
    # from the right so a filename containing ' - ' cannot become a prefix match.
    uri = urlsplit(name.rsplit(" - ", 1)[0])
    if uri.scheme != "file" or uri.netloc.lower() not in ("", "localhost") or uri.query or uri.fragment:
        return None
    if re.search(r"%(?![0-9A-Fa-f]{2})", uri.path):
        return None
    try:
        path = unquote(uri.path, errors="strict")
    except UnicodeDecodeError:
        return None
    if not path.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return None
    try:
        return Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def frame_document_identity(frame, target: Path) -> str:
    """Return match, mismatch, absent, or unknown for document URI evidence."""
    queue = deque([(frame, 0)])
    seen = 0
    saw_document = False
    saw_match = False
    saw_mismatch = False
    uncertain = False
    while queue and seen < MAX_ACCESSIBLE_NODES:
        node, depth = queue.popleft()
        seen += 1
        role = node.get_role_name()
        if role.startswith("document"):
            saw_document = True
            name = node.get_name()
            reference = name.rsplit(" - ", 1)[0]
            if urlsplit(reference).scheme:
                path = document_path(name)
                if path == target:
                    saw_match = True
                else:
                    # A URI-like but invalid, inaccessible, or different path is
                    # authoritative conflicting evidence. Never bypass it.
                    saw_mismatch = True
            continue  # Never inspect spreadsheet cells or document content.
        count = node.get_child_count()
        if role in ("menu bar", "menu", "tool bar", "table", "spreadsheet"):
            continue
        if depth >= MAX_ACCESSIBLE_DEPTH or count > MAX_ACCESSIBLE_CHILDREN:
            uncertain = uncertain or count > 0
            continue
        for index in range(count):
            queue.append((node.get_child_at_index(index), depth + 1))
    if queue:
        uncertain = True
    if saw_mismatch:
        return "mismatch"
    if saw_match and not uncertain:
        return "match"
    if saw_document and not uncertain:
        return "absent"
    return "unknown"


def process_has_open_file(pid: int, target: Path) -> bool:
    """Check bounded procfs descriptors; this is process, not frame, evidence."""
    fd_dir = Path("/proc", str(pid), "fd")
    try:
        descriptors = list(fd_dir.iterdir())
    except OSError:
        return False
    if len(descriptors) > 4096:
        return False
    for descriptor in descriptors:
        try:
            if descriptor.resolve(strict=True) == target:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def expected_frame_titles(target: Path, role: str) -> set[str]:
    label = role.capitalize()
    return {
        f"{target.name} — LibreOffice {label}",
        f"{target.name} - LibreOffice {label}",
    }


def resolve_target_role(path_text: str, Gio) -> tuple[Path, str] | None:
    target = Path(path_text).resolve(strict=True)
    if not target.is_file():
        return None
    file = Gio.File.new_for_path(str(target))
    info = file.query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
    app = Gio.AppInfo.get_default_for_type(info.get_content_type(), False)
    match = None if app is None else LIBREOFFICE_APP_RE.fullmatch(app.get_id() or "")
    if match is None:
        return None
    return target, match.group(1)


def x11_windows_for_title(pid: int, title: str) -> list[str] | None:
    search = subprocess.run(
        ["xdotool", "search", "--all", "--pid", str(pid), "--name", "^" + re.escape(title) + "$"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, timeout=1,
    )
    if search.returncode != 0:
        return None
    windows = list(dict.fromkeys(search.stdout.split()))
    if len(windows) > MAX_NATIVE_WINDOWS or any(not re.fullmatch(r"[0-9]+", item) for item in windows):
        return None
    return windows


def native_title_window_ids(target: Path, role: str) -> set[str] | None:
    """Capture a conservative pre-open superset without filtering by WM_CLASS."""
    windows: set[str] = set()
    for title in expected_frame_titles(target, role):
        search = subprocess.run(
            ["xdotool", "search", "--all", "--name", "^" + re.escape(title) + "$"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=1,
        )
        if search.returncode != 0:
            # xdotool uses status 1 with no stderr for a valid search with no
            # matches. Any diagnostic means the snapshot is incomplete.
            if search.returncode == 1 and not search.stderr.strip():
                continue
            return None
        ids = search.stdout.split()
        if len(ids) > MAX_NATIVE_WINDOWS or any(not re.fullmatch(r"[0-9]+", item) for item in ids):
            return None
        windows.update(ids)
    return windows


def window_cache_path() -> Path | None:
    state_dir = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if not state_dir:
        return None
    path = Path(state_dir)
    if not path.is_absolute():
        return None
    return path / WINDOW_CACHE_FILENAME


def read_known_window(target: Path) -> str | None:
    path = window_cache_path()
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = data.get("entries") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(entries, dict) or len(entries) > MAX_WINDOW_CACHE_ENTRIES:
        return None
    window_id = entries.get(str(target))
    return window_id if isinstance(window_id, str) and re.fullmatch(r"[0-9]+", window_id) else None


def remember_window(target: Path, window_id: str) -> None:
    path = window_cache_path()
    if path is None or not re.fullmatch(r"[0-9]+", window_id):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"version": 1, "entries": {}}
        entries = data.get("entries") if isinstance(data, dict) and data.get("version") == 1 else None
        if not isinstance(entries, dict):
            entries = {}
        entries = {
            key: value for key, value in list(entries.items())[-(MAX_WINDOW_CACHE_ENTRIES - 1):]
            if isinstance(key, str) and isinstance(value, str) and re.fullmatch(r"[0-9]+", value)
        }
        entries[str(target)] = window_id
        payload = json.dumps({"version": 1, "entries": entries}, separators=(",", ":"))
        temp = path.with_name(path.name + f".{os.getpid()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temp, path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    except OSError:
        return


def capture_snapshot(path_text: str) -> dict[str, object] | None:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, Gio

    resolved = resolve_target_role(path_text, Gio)
    if resolved is None:
        return None
    target, role = resolved
    matching_ids = native_title_window_ids(target, role)
    if matching_ids is None:
        return None
    Atspi.set_timeout(400, 400)
    desktop = Atspi.get_desktop(0)
    if desktop is None or desktop.get_child_count() > 128:
        return None

    target_ids: list[str] = []
    known_window = read_known_window(target)
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if application.get_name().lower() not in ("soffice", "libreoffice"):
            continue
        pid = application.get_process_id()
        if pid <= 0 or application.get_child_count() > 64:
            return None
        frames = [application.get_child_at_index(i) for i in range(application.get_child_count())]
        titles = [frame.get_name() for frame in frames]
        basename_titles = [title for title in titles if target.name in title]
        if len(basename_titles) > 1:
            return None
        for title in titles:
            if title not in expected_frame_titles(target, role):
                continue
            windows = x11_windows_for_title(pid, title)
            if windows is None or len(windows) != 1:
                return None
            if any(window_id not in matching_ids for window_id in windows):
                return None
            if (len(basename_titles) == 1 and known_window in windows
                    and process_has_open_file(pid, target)):
                target_ids.append(known_window)
    return {
        "version": 1,
        "matching_window_ids": sorted(matching_ids),
        "target_window_ids": list(dict.fromkeys(target_ids)),
    }


def parse_snapshot(raw: str | None) -> tuple[set[str], set[str]] | None:
    if raw is None or len(raw) > 4096:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    matching = data.get("matching_window_ids")
    target = data.get("target_window_ids")
    if not isinstance(matching, list) or not isinstance(target, list):
        return None
    if len(matching) > MAX_NATIVE_WINDOWS or len(target) > MAX_NATIVE_WINDOWS:
        return None
    if any(not isinstance(item, str) or not re.fullmatch(r"[0-9]+", item)
           for item in [*matching, *target]):
        return None
    matching_set, target_set = set(matching), set(target)
    if not target_set.issubset(matching_set):
        return None
    return matching_set, target_set


def activate(path_text: str, snapshot_raw: str | None = None) -> bool:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, Gio

    resolved = resolve_target_role(path_text, Gio)
    if resolved is None:
        return False
    target, app_role = resolved
    snapshot = parse_snapshot(snapshot_raw)

    Atspi.set_timeout(400, 400)
    desktop = Atspi.get_desktop(0)
    if desktop is None or desktop.get_child_count() > 128:
        return False
    matches: list[str] = []
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
        basename_title_count = sum(target.name in title for title in titles)
        for frame, title in zip(frames, titles):
            if target.name not in title:
                continue
            identity = frame_document_identity(frame, target)
            if counts[title] != 1:
                return False
            windows = x11_windows_for_title(pid, title)
            if windows is None:
                return False
            if identity == "match":
                eligible = windows
            elif (identity == "absent" and snapshot is not None
                  and basename_title_count == 1
                  and title in expected_frame_titles(target, app_role)
                  and process_has_open_file(pid, target)):
                before_matching, before_target = snapshot
                if before_target:
                    # The target was already open: only a window proven before
                    # the new open request may be brought forward.
                    eligible = [item for item in windows if item in before_target]
                else:
                    # The target was not open: reject pre-existing same-title
                    # windows and require a newly matching native window.
                    eligible = [item for item in windows if item not in before_matching]
            else:
                eligible = []
            if len(eligible) > 1:
                return False
            matches.extend(eligible)
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        return False
    result = subprocess.run(
        ["xdotool", "windowactivate", "--sync", matches[0]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1,
    )
    if result.returncode == 0:
        remember_window(target, matches[0])
        return True
    return False


def environment_supported() -> bool:
    return (
        sys.platform == "linux"
        and bool(os.environ.get("DISPLAY"))
        and not os.environ.get("WAYLAND_DISPLAY")
        and os.environ.get("XDG_SESSION_TYPE") != "wayland"
        and not os.environ.get("WSL_DISTRO_NAME")
        and not os.environ.get("WSL_INTEROP")
        and os.environ.get("LOCAL_PATH_ACTIONS_DRY_RUN") != "1"
    )


def main() -> int:
    if not environment_supported():
        return 3
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "snapshot":
            snapshot = capture_snapshot(sys.argv[2])
            if snapshot is None:
                return 3
            print(json.dumps(snapshot, separators=(",", ":")))
            return 0
        if len(sys.argv) == 4 and sys.argv[1] == "activate":
            return 0 if activate(sys.argv[2], sys.argv[3]) else 3
        if len(sys.argv) == 2:  # Backward-compatible URI-authoritative invocation.
            return 0 if activate(sys.argv[1]) else 3
        return 3
    except Exception:
        # Optional desktop IPC must never prevent the validated file opening.
        # Do not log accessibility metadata of other documents/applications.
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
