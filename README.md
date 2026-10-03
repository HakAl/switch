# Switch

Switch lets Claude Code save its progress, clear its context, and continue the
same task in a fresh session. **[Herdr](https://herdr.dev) is required.**

`checkpoint → clear → resume → acknowledge → continue`

By default Switch resets at 25% of the reported context window; pass another
limit such as `40%` or `250k` tokens. Switch asks the agent to finish active work
and save a checkpoint before resetting. The limit is a soft threshold; finishing
work can take it over the target.

Release [0.4.1](docs/release-0.4.1.md) preserves bootstrap submission evidence
for acknowledgment recovery and seeds an exact standalone ack command.

## Requirements

- Python 3.9+, with no pip dependencies.
- Claude Code running in Herdr, with Herdr’s session-reporting integration enabled.
- A private local POSIX filesystem. Tested on macOS; see [validation](docs/validation.md).

## Quick start

Clone into a stable location, then install from the project to manage:

```sh
git clone https://github.com/HakAl/switch.git ~/switch
cd /path/to/your/project
python3 ~/switch/switch_auto.py install --dry-run   # preview, no writes
python3 ~/switch/switch_auto.py install
```

By default Switch manages the current directory and keeps state in
`$SWITCH_STATE_DIR`, otherwise `~/.local/state/switch`. Override with a limit
argument, `--project`, `--state-dir`, or `--scope user`; see [automatic setup](docs/auto.md).

The installer adds Switch’s own scoped `request`, `ack` and state-directory
entries to `permissions.allow` in `.claude/settings.local.json`, after saving a
byte-identical backup. It keeps your key order, indentation and line endings,
warns first if your file uses formatting it cannot reproduce, such as `\u`
escapes, and uninstall removes only the entries it added. You still allow reads of the task’s instruction
and authority files, and the actions the task needs; auto permission mode alone
does not authorize resets. See [permission setup](docs/reference.md#permissions-for-the-complete-path).

Start a **fresh Claude session inside Herdr** in that project. Keep the scripts
and interpreter at their installed paths. No session is reset during setup.

```sh
python3 ~/switch/switch_auto.py status
# Remove the hooks later; saved state remains:
python3 ~/switch/switch_auto.py uninstall
```

For manual-trigger hooks and CLI commands, see the [reference](docs/reference.md).
Run requests from the session being reset; Switch checks the inherited Herdr pane.

## When a reset is pending

Let the agent finish its turn and leave the pane alone while Switch resets it.
New input cancels a pending reset before clear. **You can say “try again”**:
the agent checks eligibility, refreshes the checkpoint, and requests an explicit
retry with `--retry-of`.

Only a finished request that never attempted clear can be retried. If a clear
might already have been sent, Switch refuses another attempt. Use
[`status` and the recovery instructions](docs/reference.md#results-and-recovery);
do not delete claims or use `ack` to unlock a session. `resumed` confirms the
reset and acknowledgment, not completion of the task.

## Local data

Automatic hooks retain verbatim prompts in private files, up to 512 KiB per
session, including nested sessions. There is no automatic expiry. Use private
local storage, not a shared or synced folder. Uninstall keeps state and backups
for recovery; [retention details](docs/auto.md#status-recovery-and-local-data).

## Development

```sh
python3 -B -m unittest discover -s tests -v
```

[Design](docs/design.md) · [Validation](docs/validation.md) · [MIT license](LICENSE)
