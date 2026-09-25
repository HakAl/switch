# Switch 0.3.1

Two fixes make resets more reliable and keep requests in their calling pane:

- Stop clears stale foreground tool entries left by denied or blocked calls that
  never emit completion events. Background workers remain tracked.
- `preflight` and `request` require inherited `HERDR_PANE_ID` to match `--pane`,
  and still verify that the supplied session is current in that pane. Missing or
  mismatched caller identity is refused before reading the checkpoint or claiming
  a session. This is a procedural guard, not OS-level authentication.

## Verification

- All 115 tests pass on Python 3.9.6 and 3.14.7.
- A full-tool-set live reset in auto mode passed after a deliberate tool denial:
  one clear, one bootstrap, matching acknowledgment and the expected result.
- Cross-pane preflight and request were refused without creating a request or claim.
- Isolated installation, permissions, status, uninstall and nine-hook checks pass.

See [validation](validation.md#release-031-september-25-2026) for the tested setup
and limits. This release's live check used a manual trigger; it did not exercise
the automatic threshold path.

## Upgrade

Finish pending requests, update the checkout, then start fresh Claude sessions.
Existing installed hooks use the updated scripts at their stable paths. Preserve
state and claims for recovery; there is no state migration or automatic retry.

Run requests from the session being reset. External scripts that previously
requested resets for another pane will now be refused; do not override the
inherited pane variable to restore that behavior. See the [reference](reference.md#agent-procedure).

This release contains the standalone CLI and automatic companion. The plugin
prototype is not included.
