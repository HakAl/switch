# Automatic context limits

Switch includes `switch_auto.py`, an installable Claude Code hook companion to the
existing reset engine. Use an absolute input-context limit such as **250k** for a
usual reset point between 200–300k tokens. `25%` is equivalent when Claude reports
a 1M window. Percent limits use the actual reported window, without model-name
assumptions. This stays in the same Switch package; no pip install or daemon.

From the repo where you want it:

```sh
python3 /absolute/path/switch/switch_auto.py install 250k
python3 /absolute/path/switch/switch_auto.py status
python3 /absolute/path/switch/switch_auto.py uninstall
```

Project scope is the default and writes `.claude/settings.local.json`. To apply
across your user's Claude sessions instead:

```sh
python3 /absolute/path/switch/switch_auto.py install 250k --scope user
python3 /absolute/path/switch/switch_auto.py status --scope user
python3 /absolute/path/switch/switch_auto.py uninstall --scope user
```

User scope writes `$CLAUDE_CONFIG_DIR/settings.json`, otherwise
`~/.claude/settings.json`; it is not an all-OS-users system installation. Use
`--project /absolute/repo` to select another repo, `--state-dir /private/path` at
installation to choose storage, or `--dry-run` to inspect the target without
writes. Default state is `$SWITCH_STATE_DIR`, otherwise `~/.local/state/switch`.
Repeat install with a different limit to update it. Keep the installed scripts
and Python interpreter at stable paths. Start a new Claude session after setup.

The installer (including `--dry-run`) discloses verbatim prompt retention under
the state root and the explicit-retry policy. At user scope this covers all
hooked sessions for that user, including nested processes. Files are private and
bounded per session; there is no automatic retention expiry.

Version 0.2 changes the state layout. Finish pending requests before upgrading,
then start new Claude sessions so SessionStart writes fresh session records. Old
pane snapshots and pane-wide sample files are ignored, not migrated or deleted.

## Setup and permissions

**Actual resets currently require Claude running under Herdr**, with its session
reporting integration enabled. Plain Claude sessions receive no preparation
instructions or Stop blocks; their existing status display still works. Hooks
alone cannot execute `/clear` in an ordinary interactive Claude terminal. This
companion reuses Switch's verified Herdr transport.

The installer merges lifecycle hooks and wraps your effective command statusLine.
It prints `required_permissions` for the exact installed interpreter and paths.
Configure those scoped allow entries through your normal Claude permission setup
for an unattended request/ack/checkpoint path, plus reads for instruction and
original authority sources and permissions for the task itself. The installer
preserves existing permissions. See [the base setup](reference.md#permissions-for-the-complete-path)
for filesystem, socket and permission details. Runtime cannot grant permissions.

Without scoped request/ack permissions, auto mode has denied resets before clear.
Manual-trigger reset and acknowledgment have passed with explicit permissions;
see [validation](validation.md) for tested versions and limits. Configure scoped
permissions explicitly before relying on unattended resets. The latest release
smoke test exercises a manual trigger, not the threshold path.

Do not also install `switch.py hook`: the automatic hooks include that recorder.
The installer refuses detected standalone hooks; migrate those explicitly before
installation. It does not edit managed settings, CLI `--settings` files, or other
scopes to remove conflicts. Disabling hooks or installed settings sources, or
replacing statusLine in a higher-priority source, disables observation. Such
sessions cannot reliably auto-reset.

A project installation takes precedence over a user installation. Both can exist;
user hooks stay inactive inside that project. The project manifest intentionally
suppresses user fallback even if you disable that project's settings source in
Claude. Uninstall the project scope to restore user behavior. Changing working
directories across installed roots mid-session is unsupported: begin a new session
in the intended project. Existing inherited statusLine configuration is captured
at install time; later changes to that inherited command require reinstalling.

## What happens at the limit

1. StatusLine observes the current input + cache-write + cache-read tokens, bound
   to the Claude session and Herdr pane in `auto/PANE/SESSION.sample.json`. Cumulative billing and output totals do
   not count. Repeated redraws do not make an old measurement fresh.
2. A tool-completion hook can request preparation once. Stop can continue the
   turn once if necessary, respecting `stop_hook_active`. StatusLine itself never
   sends a prompt; unknown or older-than-60-second measurements cannot trigger.
   Malformed attributable updates replace older samples with unknown values and
   a diagnostic, while another session's updates cannot alter this one.
3. The agent finishes useful active resources, records a checkpoint and original
   authority sources, runs the concrete supplied Switch request, then ends its
   turn. Switch verifies the safe boundary, sends `/clear`, bootstraps the new
   session and requires explicit acknowledgment.
4. The replacement session stays disarmed until a fresh below-limit measurement
   after acknowledgment. A bootstrap already larger than your limit stays
   disarmed instead of clearing repeatedly.

This is a **soft preparation threshold**, not an exact ceiling. The current API
response and safe resource cleanup can overshoot. StatusLine runs asynchronously;
an eligible hook may consume the previous API measurement. If no fresh sample is
available, feedback waits for a later tool completion or Stop. A token limit at
or above a reported smaller context window is reported as
`limit_at_or_above_context_window`; it never silently changes your limit.

## Status, recovery, and local data

`status` reports installation health, permissions and the runtime-state directory.
Run it inside a managed pane to include the session selected by Herdr; unavailable
Herdr identity yields an unknown session rather than selecting a child's last hook. States
include `below_limit`, `measurement_unknown_or_stale`, `preparation_requested`,
`reset_requested`, and `awaiting_below_limit_after_bootstrap`. A request link leads
to the ordinary `switch.py status --state-dir PATH --request-id REQUEST_ID` result.

Each notice and Stop continuation happens at most once per session, including
later turns. The exact supplied request command's PreToolUse records an attempt;
even a refusal before claim creation suppresses further feedback. A durable reset
claim also suppresses it. Failure is reported, never automatically retried. If the
user asks to try again, inspect `switch.py status`: a finished `not_cleared`
request with `retry_eligible: true` supports `request --retry-of REQUEST_ID` after
fresh preparation and checkpoint validation. Status identifies the current claim
owner; an obsolete request cannot be retried. Explicit retries do not rearm
threshold feedback. Do not delete claims or change state directories to bypass
the base engine's guards. `ack` is a continuation receipt, not an unlock command.

Under the private state root, `auto/PANE/` contains measurements, session states,
and bounded verbatim UserPromptSubmit inputs as provenance. Lifecycle records
are separately isolated at `panes/PANE/SESSION.json`. Nested sessions sharing a
pane do not replace parent data. Herdr must still report the intended foreground
Claude session correctly: isolation of Switch files does not repair another
integration that incorrectly reports a headless worker as the pane owner. Inputs may contain
untrusted pasted text; the record adds no authority. Known Switch bootstrap inputs
are omitted. Provenance is capped at 512 KiB per session; exceeding that cap leaves
the existing record and reports a hook error. Checkpoints must retain original
authority sources, scope and expiry. Agent notes and hook text grant nothing new.

The scoped `.claude/switch-auto.json` manifest records owned hooks and the original
statusLine; `switch-auto.settings-backup.json` retains a settings backup. Files are
private and atomically replaced. The installer lock serializes its own operations;
a source comparison detects many external edit conflicts, but other editors do
not honor that lock, so avoid simultaneous settings edits. An incomplete manifest
can be inspected and removed with `uninstall` before reinstalling.

Uninstall removes only owned entries and restores statusLine if still unchanged.
It preserves an independently replaced statusLine. If a modified wrapper still
references its manifest, uninstall refuses until you replace that command or
restore the installed wrapper; it cannot safely guess how to rewrite shell code.
State and backup evidence remain for recovery. Remove them yourself when no
requests are active and you no longer need the evidence.

Claude contracts: [statusLine measurements and timing](https://code.claude.com/docs/en/statusline),
[hook input and feedback](https://code.claude.com/docs/en/hooks),
[settings scopes](https://code.claude.com/docs/en/settings).
