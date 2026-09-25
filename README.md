# Switch

Switch lets Claude Code save its progress, clear its context, and continue the
same task in a fresh session. **[Herdr](https://herdr.dev) is required.**

`checkpoint → clear → resume → acknowledge → continue`

Choose a context limit such as `250k` tokens or `25%`. Switch asks the agent to
finish active work and save a checkpoint before resetting. The limit is a soft
threshold; finishing work can take it over the target.

## Requirements

- Python 3.9+, with no pip dependencies.
- Claude Code running in Herdr, with Herdr’s session-reporting integration enabled.
- A private local POSIX filesystem. Tested on macOS; see [validation](docs/validation.md).

## Quick start

Clone into a stable location, then choose the project to manage:

```sh
git clone https://github.com/HakAl/switch.git
cd switch
SWITCH_DIR="$PWD"
SWITCH_PROJECT=/absolute/path/to/your/project
SWITCH_STATE=/absolute/path/to/private/switch-state

python3 "$SWITCH_DIR/switch_auto.py" install 250k \
  --project "$SWITCH_PROJECT" --state-dir "$SWITCH_STATE" --dry-run
python3 "$SWITCH_DIR/switch_auto.py" install 250k \
  --project "$SWITCH_PROJECT" --state-dir "$SWITCH_STATE"
```

Add the installer’s `required_permissions` to the project’s
`.claude/settings.local.json` under `permissions.allow`, preserving existing
entries. Also allow reads of the task’s instruction and authority files, and the
actions the task needs. The installer preserves permissions; auto permission mode
alone does not authorize resets. See [permission setup](docs/reference.md#permissions-for-the-complete-path).

Start a **fresh Claude session inside Herdr** in that project. Keep the scripts
and interpreter at their installed paths. No session is reset during setup.

```sh
python3 "$SWITCH_DIR/switch_auto.py" status --project "$SWITCH_PROJECT"
# Remove the hooks later; saved state remains:
python3 "$SWITCH_DIR/switch_auto.py" uninstall --project "$SWITCH_PROJECT"
```

For user-wide installation or other limits, see [automatic setup](docs/auto.md).
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
