# Validation

## Automated coverage

The v0.3 suite has 109 tests, passing on macOS with Python 3.9.6 and 3.14.7.
Tests use fake Herdr, hook input, clocks and a detached subprocess with a fake
executable. They do not read or send to live panes. Run from the checkout:

```sh
python3 -B -m unittest discover -s tests -v
```

Coverage includes input parsing, missing or modified checkpoints, identity changes,
active tools and workers, duplicate claims, deadline exhaustion, transient telemetry,
uncertain sends, wrong acknowledgments, permission-mode changes, abandoned helpers,
session isolation, malformed context samples, threshold feedback, scoped installation
and restoration of existing settings. The v0.3 installation check is summarized
below. The [v0.2 release check](release-0.2.0.md) preserves the earlier installation
transcript and its 98-test baseline.

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
