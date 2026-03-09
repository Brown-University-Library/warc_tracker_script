# Answer

Using the spreadsheet’s `Status-Main` field as an **in-process marker** is a reasonable idea, but I would treat it as a **secondary coordination signal**, not the primary lock.

## Short assessment

- **Good for visibility**: it tells you, in the operator-facing control surface, that a collection or run appears active.
- **Useful as a soft gate**: a local/manual run could inspect the field and decide whether to proceed, warn, or exit.
- **Not good enough as the sole lock**: the spreadsheet is explicitly framed in the project plan as **reporting/control, not correctness**, and that matters here.

So my recommendation is:

- keep a **host-local hard lock** such as `flock` for true overlap prevention
- optionally add a **spreadsheet status check** as a polite coordination layer for manual/local invocations

## Why the spreadsheet-status idea helps

This approach addresses one real weakness in a pure cron-wrapper `flock` design:

- `flock` protects only callers that use the wrapper
- a local/manual run can otherwise bypass that protection entirely

If a local run checks `Status-Main` first, it can notice that the cron job already marked a collection as something like:

- `discovery-in-progress`
- `downloading-in-progress`

and then decide not to interfere.

That is valuable because it extends coordination into the same operator-visible system you already plan to update.

## Main weakness of spreadsheet status as the lock

I would be cautious about relying on it alone.

### Problem 1: stale status

If a run crashes after setting `Status-Main` to an in-progress value, a later run may incorrectly think work is still active.

You can reduce this with timestamps or heartbeat-like updates, but once you do that, you are building a lightweight distributed lock protocol in a spreadsheet.

That is possible, but it is more fragile than a local OS lock.

### Problem 2: race window

Two invocations can both read the sheet before either writes the in-progress marker.

Without an atomic compare-and-set mechanism, both may proceed.

That means spreadsheet-only gating is better as:

- advisory
- operationally helpful

but weaker as a correctness guarantee.

### Problem 3: spreadsheet availability should not define correctness

Per the plan, the filesystem and `state.json` are the source of truth, while the spreadsheet is mainly reporting/control.

If the sheet is temporarily unavailable, you probably do not want your only overlap-prevention mechanism to disappear.

## Recommendation on your proposed approach

I think this is a **good addition**, with one adjustment:

- do **not** make `Status-Main` the only guard
- use it as a **soft interlock plus operator signal**

A good policy would be:

1. cron invocation acquires `flock`
2. cron run writes spreadsheet in-progress status
3. local/manual run checks spreadsheet status before doing work
4. if spreadsheet says a run is active, local run exits or requires an explicit override

That gives you both:

- hard protection against overlapping cron runs on one host
- human-visible protection against accidental manual interference

## Alternative 1: local lock file as the actual gate for both cron and manual runs

This is the cleanest alternative if your concern is: "allow cron to exist, but ensure a local run behaves properly."

The idea:

- put the lock in one shared wrapper or one small lock helper
- require **both** cron and manual/local runs to use the same lock path

Examples:

- cron uses `flock -n /tmp/warc_backup.lock ...`
- manual run uses the exact same wrapper command

Why this is strong:

- it is an actual OS-level mutual exclusion mechanism
- it avoids spreadsheet race/staleness problems
- it keeps the spreadsheet in its intended role: status/reporting

Main limitation:

- it only works cleanly when both invocations happen on the same host and honor the same wrapper

For this project, that still seems like the most practical MVP answer.

## Alternative 2: explicit run mode policy for local runs

Another approach is to add a small policy layer in the script, such as:

- default local behavior: refuse to run if spreadsheet status indicates active processing
- optional override flag: run anyway

For example, conceptually:

- normal local run: checks sheet, exits if `Status-Main` is in an active state
- override local run: `--force` or similar bypasses that check

Why this helps:

- it makes local behavior predictable
- it prevents accidental collisions
- it still allows an intentional operator override when the spreadsheet status is stale

Why I like this more than spreadsheet-only locking:

- the spreadsheet becomes a decision input, not the sole source of truth
- you can document the policy clearly
- stale status is recoverable by explicit operator intent

## Best-fit option for this project right now

Given the current plan, I think the best near-term design is:

- **Primary guard**: `flock` in the cron/manual wrapper
- **Secondary guard**: spreadsheet `Status-Main` check for manual/local runs
- **Operator escape hatch**: an explicit override for stale-status situations

That aligns well with the plan’s current architecture:

- lock/cron hardening remains simple
- spreadsheet stays a control/reporting surface
- local filesystem state remains the source of truth

## Practical bottom line

- **Your spreadsheet-status idea is good as a soft coordination mechanism.**
- **I would not rely on it alone for overlap prevention.**
- **The strongest practical MVP is `flock` for hard locking, plus a spreadsheet active-status check to decide whether a local run should proceed.**

If you want the shortest recommendation:

- use `flock` to guarantee no same-host overlap
- use `Status-Main` to let a local run detect that cron is already in progress
- allow an explicit override when the sheet status is stale
