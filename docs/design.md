# Switch design

Switch uses a checkpoint and a bounded detached helper to reset a Claude Code
session in its existing Herdr terminal, then verify continuation. There is no
scheduler, resident service or model launcher.

## Preparation and request

The agent finishes useful tools, collects workers and resolves background waits
before writing the checkpoint. The checkpoint records task, role, absolute
worktree, relevant refs, completed and unfinished work, a concrete next action,
instruction and original authority-source paths, and an explicit empty resource
inventory. Untracked external jobs remain the initiating agent's responsibility.
Herdr idle and a Stop event cannot prove those jobs have finished.

`preflight` and `request` first require inherited `HERDR_PANE_ID` to match the
requested pane, then check its live session identity. This is a procedural guard,
not OS-level authentication: arbitrary local code can alter its environment.

`preflight` checks setup without sending. `request` copies and hashes the bounded
checkpoint into private storage, claims the old session, starts the helper and
returns. The agent then ends its turn immediately. New user input after scheduling
invalidates the pending request. A claim persists even if no clear is sent; there
is no automatic retry. An explicit `request --retry-of` may transfer that claim
only from a finished `not_cleared` attempt with complete evidence that no clear
or resume was attempted, and the same live pane/session/terminal identity.

Retry holds the claim, pane and predecessor-worker locks while validating and
publishing a fresh checkpoint and request. The atomic claim replacement commits
ownership; the old receipt remains unchanged. Helpers verify ownership before
starting, so a request orphaned before publication cannot send. Status reports
the current owner and advisory eligibility; scheduling rechecks it. Uncertain
sends and interrupted helpers remain ineligible. A per-pane advisory lock
prevents concurrent helpers.

## Confirming the reset

The helper requires a subsequent Stop, no tracked tools or workers, fresh lifecycle
telemetry, an idle/done Herdr row, and a readable empty prompt. It examines the
whole bordered input box, including continuation lines, and ignores only actual
SGR 2 dim suggestions. It refuses unfamiliar layouts, dialogs and scrolled views.
Visible reads require scroll offset zero both before and after capture.

Stop clears foreground tool entries, including calls denied without a completion
event. Background workers remain tracked until their own completion events; Stop
does not establish that external jobs have finished.

Before each send it rechecks pane, terminal, expected session and readiness, then
records intent. Herdr has no atomic session-compare-and-send operation, so exclusive
pane ownership remains required. It sends `/clear` once, confirms a changed Herdr
session together with that session's SessionStart source `clear`, sends one
bootstrap, observes its submission, and waits for explicit `ack`.

For the clear, a per-pane pending pointer links the request to a conditional
SessionStart continuation. Eligible candidate sessions receive context once;
only the helper consumes the pointer after confirming the actual replacement.
Nested session starts cannot consume it. The context requires the matching
bootstrap before action and grants no authority. The fresh agent reads the
checkpoint, instructions and original authority sources before acknowledging.
Claude's observed pasted-content wrapper is normalized only as an exact paired
envelope; submission is confirmed against the full saved bootstrap hash.

## Session isolation and bounded waits

Lifecycle records are `panes/PANE/SESSION.json`, serialized under a pane lock.
All readers name an expected session. Nested processes update their own files;
legacy pane snapshots cannot satisfy current evidence. Herdr still must report
the intended foreground session correctly.

Idle, clear and ack waits have finite budgets. Clear confirmation and replacement
readiness get separate `clear-deadline` intervals. Each Herdr call is capped by
five seconds and the remaining phase budget. Transient missing reads consume
that budget; known identity changes refuse. The independent 120-second lifecycle
freshness guard still applies. An uncertain send is observed, never resent.

Request records distinguish `resumed`, `not_cleared`, `clear_uncertain`,
`cleared_not_resumed` and `interrupted_uncertain`. Kernel locks establish helper
liveness; a reused PID does not. SIGKILL or power loss cannot guarantee a final
write, so status reports abandoned helpers as uncertain rather than successful.
Acknowledgment proves a receipt was supplied, not task completion or comprehension.

## Optional threshold companion

The companion installs project or user hooks and wraps a command statusLine,
without changing permissions. It uses current input plus cache-read and cache-write
tokens, or a percentage of the actual reported window. Cumulative billing and
output counts do not determine occupancy. Samples are per session; unchanged
redraws do not refresh age, and malformed attributable updates replace old samples
with unknown values. Samples older than 60 seconds cannot trigger preparation.

A completion hook requests preparation once; Stop can continue the turn once when
needed. The actual request still follows the preparation and readiness rules above.
The exact supplied request's PreToolUse marks an attempt even if permission is later
denied. Replacement sessions stay disarmed until acknowledgment followed by a fresh
below-limit sample. A bootstrap over the threshold cannot cause a reset loop.

See [automatic setup](auto.md), [validation](validation.md), and the
[recovery procedure](reference.md#results-and-recovery).
