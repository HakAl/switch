# Switch 0.3.0

A cancelled reset no longer prevents an explicit retry when Switch can prove
that no clear was attempted. Use `request --retry-of FAILED_REQUEST_ID` after
fresh preparation. Status reports eligibility and the current request owner.
Uncertain sends remain ineligible; no automatic retry loop was added.

Retry preserves the failed receipt, creates a fresh request and checkpoint, and
atomically transfers the claim under locks. A helper cannot execute an unowned
request. `ack` still only acknowledges continuation.

The README is about 80% shorter. Detailed setup, permissions, CLI usage and
recovery information are preserved in the [reference](reference.md).

## Verification

- 109 tests pass on Python 3.9.6 and 3.14.7, including detached cancellation/retry,
  concurrent retries, lost claim publication, stale ownership, and uncertain clear.
- Live explicit retry passed on Herdr 0.7.5 and Claude Code 2.1.281 (Opus 5.5) in auto mode:
  cancelled first attempt, resumed successor, matching acknowledgment, expected
  result, and one recorded clear intent and one bootstrap intent across both requests.
  The pasted retry instruction required confirmation through normal keyboard input.
- Isolated installation, permissions, status, uninstall and hook generation pass.
- Public files are allowlisted and scanned for local paths, live identifiers and
  credential patterns. Private development history and runtime captures are excluded.

See [validation](validation.md) for the test setup and its limits. Threshold-triggered
resetting in auto mode remains unverified by this release's explicit-retry test.

## Upgrade

Finish pending requests before updating the scripts. Start fresh Claude sessions
to load the revised hook instructions. The state layout is unchanged; existing
finished no-clear requests can qualify for retry after current identity and
preparation checks. Preserve state and claims for recovery.
