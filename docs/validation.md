# Validation

## Automated coverage

The v0.4.0 suite has 158 tests, passing on macOS with Python 3.9.6 and 3.14.7.
Tests use fake Herdr, hook input, clocks and a detached subprocess with a fake
executable. They do not read or send to live panes. Run from the checkout:

```sh
python3 -B -m unittest discover -s tests -v
```

Coverage includes input parsing, missing or modified checkpoints, identity changes,
active tools and workers, duplicate claims, deadline exhaustion, transient telemetry,
uncertain sends, wrong acknowledgments, permission-mode changes, abandoned helpers,
session isolation, malformed context samples, threshold feedback, scoped installation
and restoration of existing settings. New regressions cover denied tools without
completion events, missing or mismatched caller panes, and live-session mismatch.
The v0.4.0 installation check is summarized below. The [v0.2 release check](release-0.2.0.md) preserves the earlier installation
transcript and its 98-test baseline.

## Release 0.4.0, September 28, 2026

**Automated and installation checks passed:** all 158 tests on Python 3.9.6 and
3.14.7. The 13 tests added since 0.3.2 cover the default limit, no-argument CLI,
retained installed limit, permission ownership and malformed inputs, exact unique
backups, supported formatting/CRLF, normalization notices, and existing statusLine
key-order restoration. The previous review reproductions were rerun independently.

A fresh local public clone passed version/help, documented no-limit install
preview, install, status and uninstall on both interpreters. Cases used absent
settings and standard-formatted existing settings with a statusLine and permission.
The installer added its four missing scoped rules without manual grant merging,
preserved the initial file in an exact backup, retained an explicitly changed
40% threshold on no-argument reinstall, and removed only its grants on uninstall.
The existing-settings case returned byte for byte to its original state. All nine
hook commands were invoked successfully with synthetic inputs in both manual and
companion setups. These tests used isolated project, state and config directories.

**Live reset check incomplete:** a disposable Herdr 0.7.5 / Claude Code 2.1.284
session (Opus 5.5, auto permission mode, Python 3.14.7) used the fresh default 25%
installation and its four automatically added permission rules. Separate scoped
permissions covered fixture files and preflight. The exact preflight Bash command
was denied by the auto classifier as Tmux Self Drive, despite the launch-time
rule. The test stopped there: no request was scheduled, no clear/bootstrap/ack
occurred and no result marker was written. The installed request/ack grants were
not exercised. Settings remained byte-identical to the launch snapshot, and no
permission widening, alternate execution route or retry followed the denial.
The disposable workspace was closed; credentials were not copied.

This was an explicit manual-trigger attempt, not a percentage-threshold test.
The shell's update prompt initially consumed the launch command before Claude
started; it was launched normally once the shell prompt was ready, without a
shell update. Live results from older releases below are historical evidence,
not certification of this candidate or its new automatic permission setup.
No production pane was reset. Plugin, new-platform and crash behavior were not
retested. Raw launch settings, events and receipts stay outside public history;
only this sanitized summary is published. [install-check.txt](install-check.txt)
remains explicitly dated 0.2.0.

## Release 0.3.2, September 27, 2026

**Automated checks passed:** all 145 tests on Python 3.9.6 and 3.14.7, including
30 tests added since 0.3.1. New coverage includes structured TaskStop and Agent
completion, legacy transcript reconciliation, equal-timestamp resume ordering,
missing/failed/mismatched terminal evidence, parent/child isolation, denied tools,
permission latches and live/unknown workers remaining blocking.

A fresh local clone of the public candidate passed version/help, documented
installation dry-run, installation, required-permission merging, status and
uninstall on both interpreters. All nine generated lifecycle hook commands were
also invoked successfully with synthetic inputs, for both the installed companion
and manual setup. Uninstall preserved permissions. These isolated checks did not
copy authentication or alter real user settings. Engine and companion report 0.3.2.

**Live reset check incomplete:** a disposable Herdr 0.7.5 / Claude Code 2.1.283
session used Python 3.14.7, Opus 5.5, a Haiku 4.5 test worker and auto permission
mode. The intended flow was to stop one disposable background worker, verify its
wait process ended, then reset, acknowledge and write a result marker. Before
TaskStop, the parent issued an extra process-polling Bash command that the auto
classifier denied. The test stopped at that denial. The worker finished normally;
no TaskStop, reset request, clear, bootstrap, acknowledgment or result marker
occurred. Launch settings remained unchanged and the disposable pane was closed.
No permission widening or retry was performed.

This release therefore has unit coverage for stopped-worker reset behavior but
no completed live end-to-end reset on this exact candidate. Earlier release live
results below are historical evidence, not a substitute. Equal-timestamp resume
cases use deterministic transcript fixtures and fake transport. No fatal harness
crash or real interactive permission dialog was induced. Threshold-triggered
reset and plugin behavior were not exercised.

The public lifecycle fixture derives from an isolated measured sequence but uses
synthetic identities and shifted timestamps; event ordering, time intervals and
needed result structure are retained. It contains no captured prompt, command,
file content, path or live identity. Private diagnoses and raw evidence remain
outside public Git history. [install-check.txt](install-check.txt) is explicitly
retained as the dated 0.2.0 installation transcript.

## Release 0.3.1, September 25, 2026

**Passed:** a disposable standalone reset on Herdr 0.7.5, Claude Code 2.1.282,
Opus 5.5, Python 3.14.7, with the full tool set in auto permission mode.

A fixture hook deliberately denied a harmless Bash call after PreToolUse; no
PostToolUse or PostToolUseFailure followed for that call. The agent then ran
preflight and request from its own pane. Stop cleared the stale foreground entry,
and the helper completed one clear and one bootstrap. The new session re-read
original authority, acknowledged the matching checkpoint hash, and wrote the
expected result. Both request and acknowledgment recorded auto mode.

A separate disposable shell pane attempted preflight and request against the live
test session. Both returned caller-pane refusal; neither created a request or
claim. The target session then completed its own reset.

Launch settings were captured before startup and unchanged afterward: scoped
preflight/request/status/ack commands, fixture file reads/writes and the harmless
probe command. Workspace trust was accepted before testing; no tool approval or
permission change was needed during the reset. The fixture explicitly authorized
the expected denial and instructed the replacement to run ack by itself. This is
one controlled manual-trigger run, not threshold or plugin validation, and does
not establish reliability across other models or permission configurations.

The exported tree also passed version/help, isolated installation dry-run,
installation, required-permission merging, status, uninstall preserving grants,
and all nine hook events. User settings and credentials were not copied or edited.
[install-check.txt](install-check.txt) remains the dated v0.2 transcript; it is not
output from this release. Raw live evidence remains private; these are
maintainer-reported results.

## Live explicit retry, September 23, 2026

**Passed:** Herdr 0.7.5, Claude Code 2.1.281, Opus 5.5, auto permission mode,
in a disposable workspace with the automatic companion installed and scoped
request/ack permissions configured.

The driver scheduled a request after the initial turn stopped, then sent a real
user prompt. The helper finished `not_cleared` with no clear attempt. After an
explicit retry instruction and fresh checkpoint validation, the agent scheduled
`request --retry-of` and ended its turn. The successor finished `resumed` in a
new session, acknowledged the matching checkpoint hash, and wrote the expected
test result. The cancelled receipt was unchanged. The two receipts contain one
clear intent and one bootstrap intent; auto permission mode was preserved.

Herdr's pasted retry instruction was initially treated as quoted text by Claude;
the driver confirmed the already-authorized retry using normal keyboard input.
This tests explicit retry with automatic hooks installed, not threshold-triggered
resetting. No real task session was reset. Private receipts and captures are not
published; this is a maintainer-reported live result.

The v0.3 fresh public-file installation check also passed: version commands,
project installation dry-run, install, merging required permissions, status,
uninstall preserving permissions, and generation of all nine lifecycle hooks.
The test used isolated project/state/config directories and left user settings
unchanged. The automated suite includes a reproducible detached-process
cancellation/retry test with fake Herdr, plus race and crash-point coverage.

## Live observations, September 20, 2026

Tested transport: Herdr 0.7.5 and Claude Code 2.1.278. These are the earliest
versions tested, not an assertion about compatibility with older or newer versions.

- **v0.2 manual trigger, auto permission mode: passed.** The dogfood request
  cleared, submitted its bootstrap and received acknowledgment. Fable 5.1 was
  reported before reset; model telemetry at acknowledgment was absent. Auto
  permission mode was recorded before reset and at acknowledgment. Saved checkpoint
  and bootstrap hashes matched. Submission took about 3.3 seconds from scheduling;
  acknowledgment arrived about 14.6 seconds later. The helper recorded `resumed`
  about 244 ms after the acknowledgment, explaining an immediately read intermediate
  `submitted` state. Launch-time allow rules were not captured, so the receipt
  cannot identify the rule or classifier decision that allowed execution.
- **Sonnet 5 auto mode without request/ack allow rules: denied.** The classifier
  rejected the request as `Tmux Self Drive` before any clear. Permission mode alone
  is insufficient evidence that this configuration can continue unattended.
- **v0.2 threshold-triggered end-to-end reset in auto permission mode: pending.**
  Unit tests cover the trigger, but they do not establish a live unattended reset.
  Earlier disposable tests of the pre-v0.2 implementation in manual permission
  mode exercised manual and threshold-triggered resets; they do not close this gap.

The public repository includes sanitized summaries, not private runtime receipts,
terminal captures, captured prompts or local process records. Live results above
are maintainer-reported observations; the unit suite is reproducible from this tree.
The v0.3 live retry above is separate from these earlier observations.

## Acknowledgment recovery release, October 3, 2026

All 167 tests pass on Python 3.9.6 and 3.14.7. Nine new regressions cover retained
bootstrap evidence across follow-up prompts and repeated starts, acknowledgment
using saved worker confirmation, invalid or absent evidence, existing identity
and checkpoint/permission checks, and the standalone generated command's match
to the installer's scoped rule. A late receipt does not rewrite a finished
request's historical outcome.

Fresh local clones passed version/help, isolated default installation dry-run,
install, required permissions, status, uninstall, and execution of all nine
manual and companion hooks on both interpreters. These checks used isolated
project/state/settings directories without copying authentication or changing
user settings. The dated 0.2.0 install transcript remains historical.

The disposable live attempt used Herdr 0.7.5, Claude Code 2.1.287, Opus 5.5 and
auto permission mode. An inherited PreToolUse hook blocked the request command
because its fixture used system temporary storage. No reset request was created,
and clear/bootstrap/ack were not reached. The test ended without retry, permission
changes or edits to the inherited hook; fixture settings remained byte-identical.
The workspace was closed. Raw output is private. This does not validate live
auto-mode ack execution, threshold triggering or denial recovery.

## Recovery and resource limits

An early disposable test confirmed clear but failed to resume because Claude
wrapped the bootstrap as pasted content. The helper reported `cleared_not_resumed`
and did not resend. The configured SessionStart continuation and exact wrapper
normalization were then added and regression-tested; a fresh request succeeded.

A disposable background Bash heartbeat survived `/clear` even while Herdr showed
done and lifecycle hooks showed no active tools. Thus those signals do not prove
quiescence. This does not establish survival, result delivery or cancellation
behavior for arbitrary external waits, foreground tools or all subagent types.
Finish or explicitly resolve useful active resources before requesting a reset.
