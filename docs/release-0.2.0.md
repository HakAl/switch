# Switch 0.2.0 release check — September 21, 2026

Prepared for an initial public release under the [MIT license](../LICENSE).
This release contains a single root commit, with no development history.
The reset engine, companion, tests and checkpoint example are unchanged from the
reviewed v0.2 implementation. Release preparation changes documentation and the
public file set only.

## Public file set and scrub

[public-files.json](../public-files.json) is the exact 17-file allowlist:
the two scripts, five test files, checkpoint example, README, three user/design/
validation documents, this release note, sanitized installation output, license,
ignore file and the allowlist itself.

Excluded: the seed, private plans and review reports, dispositions, terminal and
prompt captures, and all four runtime evidence directories. README and automatic
setup links now resolve within the public tree. The design document describes
current v0.2 behavior rather than preserving superseded review discussion.
Validation uses short sanitized summaries, without local paths, pane/session IDs,
actor names or captured task inputs. Internal tool references were removed.
The requested public repository URL is the sole account-handle occurrence in
shipped file contents. No operator name or email is included in those contents.

All four original commits and 94 distinct historical file versions were scanned.
History contains local home paths, session and terminal identifiers, captured
prompts and internal process records; it is unsuitable for publication as-is.
The original repository is preserved. This export was initialized separately,
so no original commit objects or history are part of the public release.

## Fresh-clone installation check

A new local clone was made in a temporary directory outside the development tree.
Only the clone source was substituted for the README's public GitHub URL, because
publication is still awaiting approval. The checks used a temporary project,
private state path and isolated Claude configuration directory. No live seat,
real user settings or Herdr socket was used.

The README commands succeeded: version/help, full unit suite, project-scope
`install 250k --dry-run`, installation, merging the four printed permission entries,
status, uninstall, and base `hooks` generation. Dry-run created no settings;
status reported an intact wrapper and no live session; uninstall preserved the
added permissions. The base command printed all nine required hook events.
The clone stayed clean and the isolated user-config directory stayed empty.

```text
python3 --version: Python 3.14.7
python3 switch.py --version: 0.2.0
python3 switch_auto.py --version: 0.2.0
python3 -B -m unittest discover -s tests -v: 98 tests, OK (4.850s)
/usr/bin/python3 --version: Python 3.9.6
/usr/bin/python3 -B -m unittest discover -s tests -v: 98 tests, OK (4.466s)
```

[Commands and output](install-check.txt) retain installer and status output with
paths normalized; individual passing test names are omitted. The check does not
validate live permission enforcement, CLI startup hooks or a new reset. A new
live run was intentionally out of scope. No machine-layout dependency blocked
installation; hooks intentionally retain the chosen absolute script/interpreter
paths, so those locations must remain stable.

## Validation and publication

v0.2 reset and acknowledgment in auto permission mode with a manual trigger were
observed on Fable 5.1 on September 20. Sonnet 5 without request/ack allow rules
was denied as `Tmux Self Drive` before clear. Threshold-triggered end-to-end
validation of v0.2 in auto mode is **pending**. Earlier manual-mode tests do not
establish that result. See [validation](validation.md) for evidence limits.

The operator selected MIT and a fresh single-commit export. Push remains subject
to the operator's explicit approval of the reviewed commit. Repository visibility
is controlled by the operator on GitHub; it is not changed by these files.

One independent cross-family review of the shipped README and this release note
found no release blockers. Its two optional setup clarifications were applied:
the permission example identifies manual-trigger paths, and new-terminal setup
explains how to restore the clone path variable. Compatibility claims remain
limited to the versions and macOS environment actually tested.
