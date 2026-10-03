# Switch 0.4.1

Acknowledgment no longer loses proof of bootstrap submission when an ordinary
follow-up prompt arrives. Switch retains that evidence across turns and repeated
starts of the same session. Ack also accepts the worker's saved submission
confirmation, supporting recovery from older hooks that erased live telemetry.
Request/session identity, terminal identity, checkpoint and permission-mode
checks remain in place. Unobserved or mismatched bootstraps remain ineligible.

The bootstrap now presents one exact ack command in a separate code block and
requires it to run alone in its own Bash call. Checksum verification belongs in
a separate call. The existing installer already supplies the matching scoped ack
allow rule; this release does not add or widen permission rules.

After timeout, a valid manual ack writes `ack.json` without restarting the helper
or rewriting its finished `cleared_not_resumed` outcome. Inspect both records
during recovery. Changing permission mode can still cause a separate refusal.
No automatic denial retry or deadline extension was added.

## Verification

Verification pending for this candidate. Historical `docs/install-check.txt`
remains the dated 0.2.0 transcript, not output from this release.

## Upgrade

Finish pending requests before updating installed scripts. Preserve state and
claims, keep script/interpreter paths stable, and start fresh Claude sessions
afterward. Existing installed thresholds and permissions remain unchanged.
No reinstall or state migration is required for this fix. Existing saved
submission confirmations can support manual recovery after current identity,
checkpoint, authority and permission checks.

Engine and companion both report 0.4.1. The standalone CLI and automatic
companion are included; the plugin prototype is not included.
