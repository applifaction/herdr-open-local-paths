# Security Policy

## Supported versions

Until this fork publishes its first release, the latest commit on `master` is the supported development line. Historical upstream releases are retained for reference; this fork does not promise security backports to them. Include the exact commit in a report and, where practical, check whether the latest `master` is affected.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not open a public issue for a vulnerability. If private reporting is unavailable, contact the repository owner through the email address published on the owner's GitHub profile.

Include the affected commit or version, operating environment, reproduction steps, and expected impact. Do not include credentials, private documents, or unredacted terminal transcripts. This fork does not currently promise a fixed response-time SLA.

## Security model

Terminal output is untrusted input. The plugin parses paths from recent output, checks that candidates exist locally, and invokes platform tools with argument arrays rather than shell interpolation.

The open action refuses high-risk executable types and executable POSIX files, including local file URIs. On POSIX systems it checks the extension of a symlink target as well as the visible link name. UNC/network paths are not probed. Remote panes are detected from foreground process information; open and reveal are refused for recognized SSH, Mosh, and container exec sessions. Because process detection cannot prove locality in every nested setup, users must not act on paths they do not trust.

Relative terminal hyperlinks are resolved against Herdr's absolute pane cwd, or the workspace cwd only when the pane cwd is absent. No cwd guessing or file search is performed. Relative URL paths are decoded once; encoded controls or paths that decode into absolute/network paths or another URI scheme are refused. URL query strings and fragments are not passed to the file opener. The relative-link manifest pattern does not intercept HTTP(S), other URI schemes, network URLs or anchor-only links. The existing locality and executable-file guards apply to relative links too.

`LOCAL_PATH_ACTIONS_ALLOW_RISKY=1` disables executable-file guards. `LOCAL_PATH_ACTIONS_ALLOW_REMOTE=1` bypasses the pane-locality guard. These are expert overrides, not recommended configuration or fixes for an unexplained failure. Leave both unset in normal use.

The optional Linux/X11 LibreOffice activation adapter compares the requested canonical path with the complete document URI exposed by AT-SPI. It requires an unambiguous accessible frame and X11 client before requesting focus; window-title or basename matching alone is not used as proof of document identity. Missing support leaves ordinary opening unchanged. This metadata lookup is not an atomic snapshot: concurrent document or window changes remain a limitation. It does not inspect or validate document contents, macros, or the security of the associated application.

Picker snapshots are stored in Herdr's plugin state directory with user-only permissions, random names, bounded size/count, single-use deletion, and stale-file cleanup. Diagnostic actions can print file paths, selected text and pane context; review and redact that output before sharing it. The plugin is not a sandbox and inherits the user's filesystem permissions.
