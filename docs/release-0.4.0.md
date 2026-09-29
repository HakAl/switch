# Switch 0.4.0

Run `switch_auto.py install` without a limit to use 25% of the reported context
window. Reinstalling without a limit keeps the installed threshold. Percent
limits require a reported window size; use a token limit such as `250k` if that
measurement is unavailable. The threshold requests preparation; it is not an
exact ceiling or a guarantee that useful work has finished.

Fresh installation adds only missing scoped Switch permissions and records which
entries it owns. Uninstall removes those entries and preserves pre-existing and
unrelated later grants. Malformed allow entries refuse installation; malformed
permission containers during cleanup preserve the ownership manifest for repair.
Updating an existing installation only changes the threshold and does not add
grants. To adopt automatic permission setup, uninstall and install again after
finishing pending requests; manually added grants remain user-owned.

Each fresh install backs up existing settings byte for byte under a unique name.
Standard JSON formatting, key order (including existing statusLine objects),
indentation and LF/CRLF line endings are preserved. Unsupported formatting is
normalized with a notice; `--dry-run` previews that notice. Uninstall also saves
an exact backup when it must normalize later edits. Backups and runtime state
remain private local files after uninstall.

## Verification

- All 158 tests pass on Python 3.9.6 and 3.14.7, including the statusLine key-order
  regression and the prior formatting/permission reproductions.
- Fresh-clone installation checks pass on both interpreters: no-argument default,
  retained installed limit, exact backups, added-grant ownership/removal,
  versions/help, dry-run, status, uninstall and all nine hook commands in both
  manual and companion configurations.
- The disposable live test on Herdr 0.7.5 / Claude Code 2.1.284 (Opus 5.5, auto
  mode) stopped at a classifier denial of preflight, despite its scoped
  launch-time rule. No request, clear, bootstrap or acknowledgment occurred.
  The four installer-added rules were present but request/ack execution was not
  reached; this is not a completed live reset validation.
- Launch settings stayed unchanged; the test was not retried and permissions were
  not widened. Raw evidence remains private. See [validation](validation.md).

Percentage-triggered end-to-end reset remains unverified. Historical
`docs/install-check.txt` remains the dated 0.2.0 transcript, not fresh output.

## Upgrade

Finish pending requests before updating installed scripts. Preserve state and
claims, retain stable script/interpreter paths, then start fresh Claude sessions.
Existing installed limits are retained; this release does not automatically
change them to 25%. Repeat custom `--state-dir` when updating a custom-root
installation. Keep task and original-authority read permissions configured.

Engine and companion both report 0.4.0. The standalone CLI and automatic
companion are included; the plugin prototype is not included. No reset safety
checks, deadlines, automatic cancellation or retry policies are changed.
