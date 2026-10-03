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

- All 167 tests pass on Python 3.9.6 and 3.14.7, including nine ack-recovery
  regressions. Coverage includes follow-up input before worker polling, legacy
  telemetry loss, repeated session starts, invalid or absent evidence, identity,
  checkpoint and permission-mode refusals, and the generated command's match to
  an actual temporary installation's allow rule.
- Fresh-clone installation checks pass on both interpreters: versions/help,
  default-limit dry-run, install, required permissions, status, uninstall, and
  execution of all nine hooks in both manual and companion configurations.
  User settings stayed unchanged and these checks created no reset requests.
- A disposable live attempt on Herdr 0.7.5 / Claude Code 2.1.287 (Opus 5.5, auto
  mode) was blocked by an inherited PreToolUse hook prohibiting agent-authored
  work in system temporary storage. No request, clear, bootstrap or ack occurred.
  The fixture was closed without retrying or changing permissions. This is not
  a successful live reset or a live validation of classifier behavior.
- The public file set matches its explicit allowlist. Private development
  history, incident identities, transcripts and raw captures are excluded.

The evidence-loss fix is covered by deterministic tests; this release does not
claim a new successful live end-to-end reset. See [validation](validation.md).
Historical `docs/install-check.txt` remains the dated 0.2.0 transcript, not
output from this release.

## Upgrade

Finish pending requests before updating installed scripts. Preserve state and
claims, keep script/interpreter paths stable, and start fresh Claude sessions
afterward. Existing installed thresholds and permissions remain unchanged.
No reinstall or state migration is required for this fix. Existing saved
submission confirmations can support manual recovery after current identity,
checkpoint, authority and permission checks.

Engine and companion both report 0.4.1. The standalone CLI and automatic
companion are included; the plugin prototype is not included.
