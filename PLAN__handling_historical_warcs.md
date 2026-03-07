# Plan: handling historical WARCs

## Context

The script's purpose is to maintain a local backup of Archive-It WARC files for active collections.

The current production discovery rule uses:

- `store-time` only
- a 30-day overlap window
- `now - 30 days` as the first-run reference when no checkpoint exists

That behavior is appropriate for ongoing incremental discovery, but it does not guarantee a complete local backup when a collection has older WARC files and nothing new has been stored recently.

This document outlines three options for handling historical WARC coverage.

---

## Option 1: full backfill on first run

### Summary
When a collection has no existing local checkpoint, treat that collection as needing a one-time historical backfill rather than a recent-only incremental scan.

### Behavior
- If `enumeration_checkpoint_store_time_max` is missing or `null`, do not use `now - 30 days`.
- Instead, perform discovery without an effective historical cutoff, or use a deliberately early fixed cutoff.
- Enumerate all available WASAPI WARC records for the collection.
- Download any files not already present locally.
- After successful enumeration, save the maximum observed `store-time` as the checkpoint.
- On later runs, revert to the normal 30-day overlap-window behavior.

### Pros
- Best matches the stated goal of building a local backup.
- Simple operational model: first run backfills, later runs maintain incrementally.
- Requires little operator decision-making once implemented.
- Keeps the existing checkpoint design intact after initialization.

### Cons
- First run for a large collection may be slow and heavy.
- May create a large sudden download burst.
- If interrupted, the collection may need another large enumeration pass before settling into normal incremental mode.

### Best fit
Use this if the desired default behavior is: active collections should eventually become fully backed up locally without requiring a separate bootstrap workflow.

---

## Option 2: explicit bootstrap mode for historical backfill

### Summary
Keep the current recent-window behavior as the default scheduled mode, but add an explicit bootstrap/backfill mode that operators run when initializing a collection or recovering gaps.

### Behavior
- Default scheduled runs continue using the 30-day overlap-window approach.
- Add a configuration switch or CLI mode such as `full-backfill` or `bootstrap-historical`.
- In bootstrap mode, enumerate all available WASAPI records for the selected collection(s).
- Download missing historical WARC files and write the checkpoint afterward.
- Once bootstrap is complete, normal scheduled runs continue incrementally.

### Pros
- Separates heavy historical catch-up from lightweight recurring cron runs.
- Makes operator intent explicit.
- Reduces the risk that a normal scheduled run unexpectedly starts a very large download.
- Easier to stage or test on a few collections before broader use.

### Cons
- Adds an operational branch to the workflow.
- Requires the operator to remember to run bootstrap mode for new collections.
- A collection may remain only partially backed up if bootstrap is never invoked.

### Best fit
Use this if the desired default behavior is: cron runs should remain predictable and bounded, while historical catch-up is a deliberate administrative action.

---

## Option 3: bounded rolling backfill plus normal incremental discovery

### Summary
Add a second, slower-moving historical recovery mechanism that gradually backfills older WARC records over time while preserving the current recent-window incremental flow.

### Behavior
- Keep the normal 30-day overlap-window discovery for recent files.
- Track an additional historical-backfill cursor or phase in local state.
- On each run, also query an older slice of time or an older page range.
- Download missing files discovered in that historical slice.
- Advance the historical cursor gradually until the collection is fully covered.
- Continue recent incremental discovery in parallel with this slower backfill process.

### Pros
- Avoids a massive first-run download spike.
- Allows backup coverage to improve steadily over time.
- Preserves the operational predictability of recent incremental discovery.

### Cons
- Most complex option.
- Requires more state management and more careful reasoning about correctness.
- Harder to explain and test.
- More opportunity for edge cases around overlapping windows and cursor advancement.

### Best fit
Use this if the desired default behavior is: keep cron runs bounded while still moving toward eventual full historical backup coverage without requiring a separate manual bootstrap step.

---

## Recommendation

If the script's primary mission is truly to maintain a local backup of Archive-It WARCs, the clearest option is:

- Option 1, if you want the production behavior itself to guarantee eventual full local backup for every active collection.
- Option 2, if you want to preserve a lightweight cron profile and treat historical recovery as a separate explicit operation.

Option 3 is viable, but it appears more complex than necessary for the current stage of the project.
