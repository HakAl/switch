# Switch 0.3.2

Switch now resolves stale worker entries from structured completion evidence:

- Successful TaskStop for a local agent closes the matching worker generation
  even when no SubagentStop follows.
- Completed foreground Agent results must match an observed generation.
- Legacy entries can be reconciled from paired parent-transcript records.
  Resume ordering uses transcript position as well as time, so equal timestamps
  cannot let an earlier stop erase a resumed worker.
- Refusals identify remaining workers, including when lifecycle telemetry is stale.

Live and unknown workers still block reset. The 300-second default and existing
freshness, permission, input, identity and duplicate-request safeguards remain.
No automatic cancellation or retry is added.

## Verification

Pending exported-tree, fresh-clone and disposable live-flow checks. Results will
be filled in before the final local candidate is approved for publication.

The new public fixture derives from measured hook events but substitutes synthetic
identifiers and shifted timestamps. Private diagnoses, raw captures and review
reports are excluded. See [validation](validation.md) for evidence and limits.

## Upgrade

Finish pending requests before updating the installed scripts. Keep the scripts
and interpreter at their installed paths, preserve existing state and claims,
and start fresh Claude sessions afterward. No state migration is required.
Missing or unsupported terminal evidence continues to block reset; do not erase
claims or worker state to force progress.

This release contains the standalone CLI and automatic companion, not the plugin
prototype. Engine and companion both report 0.3.2.
