# Setup and CLI reference

Detailed setup, agent procedure, permissions, and operating limits.

## Install and configure

Clone into a stable location and run the checks:

```sh
git clone https://github.com/HakAl/switch.git
cd switch
SWITCH_DIR="$PWD"
python3 switch.py --version
python3 switch_auto.py --version
python3 -B -m unittest discover -s tests -v
```

Keep both scripts and the Python interpreter at those paths: installed hooks
refer to their absolute locations. In a new terminal, set `SWITCH_DIR` to the
absolute path of this clone again. Choose **one** of the following hook setups.
No live session is reset during installation.

### Automatic context-limit hooks

Set these paths for the project you want to manage and a private state directory:

```sh
SWITCH_PROJECT=/absolute/path/to/your/project
SWITCH_STATE=/absolute/path/to/private/switch-state
python3 "$SWITCH_DIR/switch_auto.py" install 250k \
  --project "$SWITCH_PROJECT" --state-dir "$SWITCH_STATE" --dry-run
python3 "$SWITCH_DIR/switch_auto.py" install 250k \
  --project "$SWITCH_PROJECT" --state-dir "$SWITCH_STATE"
python3 "$SWITCH_DIR/switch_auto.py" status --project "$SWITCH_PROJECT"
```

The installer merges hooks and wraps the effective command statusLine in
`$SWITCH_PROJECT/.claude/settings.local.json`; it preserves existing permissions.
It prints `required_permissions`. Review those exact entries and add them to
`permissions.allow` in that project's settings file, preserving existing entries.
Also permit reads of the original task instructions and authority sources, and
only the actions the task needs. See [permissions below](#permissions-for-the-complete-path).
A Bash allow rule does not grant OS filesystem or socket access.

Start a fresh Claude session inside a Herdr pane in that project after setup.
Keep Herdr's own session-reporting integration enabled. Run `herdr agent list`
and check that the row for the pane identifies Claude and the current session.
If reporting is absent or names another process, fix Herdr's integration first.
Use the [agent procedure](#agent-procedure) for a manually triggered request;
the companion supplies preparation instructions when it observes the threshold.

For user scope, status, uninstall and retention details, see [automatic setup](auto.md).
To remove this project installation:

```sh
python3 "$SWITCH_DIR/switch_auto.py" uninstall --project "$SWITCH_PROJECT"
```

Uninstall preserves state and backups for recovery. Do not delete claims while
an old session might be resumed, or change state roots to bypass a claim.

### Manual-trigger hooks only

Skip this section if you installed the companion: it already records lifecycle hooks.
Set `SWITCH_STATE` to the same private state directory used by requests:

```sh
python3 "$SWITCH_DIR/switch.py" hooks --state-dir "$SWITCH_STATE"
```

This prints a settings fragment without changing configuration. Add each entry to
the corresponding hook array in Claude's settings, preserving existing hooks,
permissions and statusLine. Alternatively save the fragment and launch Claude
with `--settings /absolute/path/switch-hooks.json` after checking the effective
configuration. Then configure the scoped permissions below and start a fresh
Claude session under Herdr to obtain its SessionStart record.

Both setups use `HERDR_PANE_ID` from Herdr and `session_id` from hook input.
Required events are SessionStart, UserPromptSubmit, Stop, PreToolUse,
PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop and PermissionRequest.
Lifecycle snapshots contain identifiers and state, not tool arguments or prompt
text; the companion separately stores the inputs disclosed above.
Use a private local state directory; avoid shared, synced or network storage.

## Permissions for the complete path

The launching Claude Bash tool needs permission to execute the installed script's
`request` and `ack` commands, and optionally `preflight` and `status`. The example
below uses **manual-trigger setup paths**; for the companion, use its printed
`required_permissions`, including its `auto-checkpoints` path. Substitute your
actual interpreter and installation paths:

```json
{
  "permissions": {
    "allow": [
      "Bash(/usr/bin/python3 /opt/switch/switch.py preflight *)",
      "Bash(/usr/bin/python3 /opt/switch/switch.py request *)",
      "Bash(/usr/bin/python3 /opt/switch/switch.py status *)",
      "Bash(/usr/bin/python3 /opt/switch/switch.py ack *)",
      "Read(//absolute/path/reset-state/requests/**)",
      "Edit(//absolute/path/project/checkpoint.json)"
    ]
  }
}
```

Use the same interpreter spelling for invocation; bootstrap uses Python's
`sys.executable`, which can differ from `python3` or a symlink. Verify the emitted
command and permit that exact installed-script prefix too when necessary. The
trailing ` *` matches arguments; avoid pane-prefix patterns such as `w8:*`.
File rules use `//` for filesystem-root paths, and `Edit` covers Write. Grant
reads for the actual instruction/authority files and only the writes/commands
needed by the task's next action. An acknowledgment does not grant that next
action permission. Deny or managed rules still apply.

The helper and hooks need filesystem access to their state directory, the
checkpoint, instruction and authority sources, plus access to the local Herdr
socket and executable. The helper invokes only `herdr agent list`, `herdr pane
get`, `herdr pane read`, and `herdr agent prompt`. Claude's Bash allow rule does
not itself configure an OS sandbox's filesystem or socket access. Test this
setup with preflight and a disposable seat first. No broad Bash/Herdr allow rule,
bypass permission mode, or permission editing by the agent is required.

For recovery, `status` and reading saved checkpoint/bootstrap files need the same
read permissions. Manual bootstrap submission uses the operator's normal Claude
input (or their existing authorized Herdr prompt channel); it is never retried
automatically. The new context still needs the scoped `ack` command permission.

## Agent procedure

1. Finish useful foreground tools. Collect outstanding workers and their results.
   Finish waits, or deliberately stop disposable waits through the owning tool's
   normal interface. Do not cancel useful work to meet a reset deadline. Inspect
   Claude's background task list and any external worker/workflow system you used.
   Herdr idle and Stop alone cannot prove those resources are finished.
2. Write a concise checkpoint based on [examples/checkpoint.json](../examples/checkpoint.json).
   Include task, role, absolute worktree, refs, completed and unfinished work,
   concrete next action, instruction paths, original authority-source paths, and
   an explicit preparation inventory. `quiescent: true` attests that active tools,
   workers and waits are all empty **except the upcoming request command itself**.
   Hooks also check tools/workers, but cannot discover arbitrary external jobs or
   a process detached by a completed Bash call. This attestation is necessary.
3. Run preflight, then request. Bind to the exact pane and current session from
   Herdr; don't guess a label or pick the first Claude seat. Preflight is read-only
   and reports busy/input conditions without treating them as readiness.
4. After request reports `scheduled`, end the turn immediately. Additional user input cancels the pending reset. Start no more
   tools, workers, or background waits. The helper waits for a subsequent Stop,
   no tracked active resources, fresh lifecycle telemetry, idle/done Herdr status,
   and a readable empty prompt. Keep this pane exclusively owned during reset:
   no typing, scrolling, manual session switching, or other automation.

```sh
python3 /opt/switch/switch.py preflight \
  --state-dir /path/reset-state --pane PANE_ID --session OLD_SESSION \
  --checkpoint /path/project/checkpoint.json

python3 /opt/switch/switch.py request \
  --state-dir /path/reset-state --pane PANE_ID --session OLD_SESSION \
  --checkpoint /path/project/checkpoint.json \
  --resume 'Run the next action recorded in the checkpoint.' \
  --idle-deadline 300 --clear-deadline 60 --ack-deadline 120

# From outside the resetting turn, using the returned request ID:
python3 /opt/switch/switch.py status \
  --state-dir /path/reset-state --request-id REQUEST_ID
```

All deadlines are finite, from 1 to 3600 seconds. `clear-deadline` gives clear
confirmation and subsequent replacement readiness separate intervals of that
length (60 seconds each by default, at most 120 seconds combined). The readiness
interval starts once, after correlated clear confirmation; both its loop and
Herdr subprocess limits use the new budget. Missing Herdr reads during readiness
or acknowledgment polling consume the existing interval; confirmed identity
changes still refuse immediately. No prompt is resent. Lifecycle evidence must
still be at most 120 seconds old: a longer deadline does not make stale evidence
usable, and slow startup without further hook events can exhaust that freshness
window. `ack-deadline` bounds confirmation
of resumption, not completion of the resumed task. Each Herdr call is capped at
five seconds and the remaining phase budget. A detached process survives the
launching tool/turn ending, but not arbitrary host shutdown or OS sandbox teardown.

Local checkpoints are capped at 32 KiB and copied to private request storage;
the actual copy is reread and hashed before clearing and bootstrapping. Existing
handoff systems can supply the content, but an identifier in terminal output is
not a checkpoint. Export and verify the actual content first. Authority source
paths reference the operator's real instructions/grants, with their original
scope and expiry; agent-authored notes are separate and cannot extend a grant.
Empty resource inventories mean explicitly none, not unknown.

## Results and recovery

Each request directory contains `request.json`, the durable `checkpoint.json`,
`helper.log`, and, after clear, `bootstrap.txt`; `ack.json` appears when the fresh
agent acknowledges. Request records include IDs, terminal identity, stages,
timestamps, both send results, old/new sessions and recovery guidance.

| Outcome | Meaning |
| --- | --- |
| `resumed` | New session confirmed, bootstrap submission observed, and agent acknowledgment received. Task completion is separate. |
| `not_cleared` | This helper sent no clear. The original session should be inspected and preparation repaired. |
| `clear_uncertain` | Clear was attempted but not confirmed by both Herdr and a new SessionStart with source `clear`. Do not resend. |
| `cleared_not_resumed` | Clear was confirmed; bootstrap or acknowledgment failed/timed out. Inspect the pane and receipt before manual recovery. |
| `interrupted_uncertain` | Status found an abandoned helper, including one killed before its final write. Inspect saved intent and live evidence. |

Exit 0 means the command succeeded (scheduling is not reset completion); 3 is a
validation/setup refusal (including brief claim-lock contention); 4 is a recorded unsuccessful or uncertain outcome.
Only `resumed` is a completed reset-and-resume result. A successful Herdr send
alone is not proof of submission, and a working status is not an acknowledgment.
The agent's receipt attests that it read the checkpoint/instructions and rechecked
authority; it is not an independent proof of comprehension.

A finished `not_cleared` request can be retried explicitly if status reports
`retry_eligible: true`. Revalidate preparation and update the checkpoint, then
repeat `request` with `--retry-of FAILED_REQUEST_ID`. This creates a new request
and preserves the old receipt. A fresh Stop is required; new input cancels the
new attempt too. Status reports `current_request_id` when an attempt has been
superseded. Eligibility is advisory and is rechecked under locks at scheduling.

Never retry automatically, delete claims, or change state roots to bypass a claim.
`ack` acknowledges a resumed session; it cannot unlock a cancelled request.
If clear was attempted or its outcome is uncertain, inspect the live session and
saved evidence before recovery: a timed-out send can still arrive. If clear
succeeded but the bootstrap never ran, preserve any draft and manually submit
saved `bootstrap.txt` once after checking it was not already processed. Never
clear that session again as a recovery shortcut.

## Support and limits

Herdr has no atomic session-compare-and-prompt operation. The helper rechecks
identity and input immediately before sending, but cannot exclude an external
writer in the last instant. Exclusive pane ownership is a required operating
condition. Scrolled views, unfamiliar prompt layouts, permission dialogs, and
missing/stale telemetry are refused. Only actual SGR 2 dim runs are ignored;
RGB/palette color alone never proves text is a suggestion. The full bordered
input box is checked, including continuation lines.

Switch sends `/clear` in the existing process. It never restarts Claude, changes
its model/mode, or cancels work. See validation for what was actually observed in
the tested CLI; do not infer arbitrary resource survival from a successful clear.
State files and claims should be retained while an old session might be resumed.
Kernel locks disappear on process death; status uses those locks rather than a
PID that could have been reused. No process can promise a final disk write after
SIGKILL or power loss, so interrupted results remain explicit.

The base engine uses Claude's [SessionStart hook](https://code.claude.com/docs/en/hooks#sessionstart)
as clear evidence. The companion uses fresh session-bound
[status-line measurements](https://code.claude.com/docs/en/statusline) to request
preparation. See [the design](design.md) and [validation](validation.md).
Permission examples follow the [Claude permission reference](https://code.claude.com/docs/en/permissions).
