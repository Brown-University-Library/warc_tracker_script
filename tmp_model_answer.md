# Option B for manifest persistence: likely the better fit

I reviewed your proposed direction against the current plan and the project’s state/reporting model.

## Short answer

I think **Option B is probably the right choice** for the behavior you want.

That is:

- do discovery and merge planning as usual
- do the filesystem-based correction step
- treat the corrected list as the true list of files that still require download work now
- persist that corrected list as the planned-download manifest surface for this run

I agree with your instinct that the broader pre-correction list does **not** obviously belong in `state.json`.

## Why Option B fits your stated goal better

Your stated goal is not just:

- add a cosmetic filter before status writing

It is more like:

- discovery gives an initial candidate set
- local filesystem reality corrects that candidate set
- the corrected set becomes authoritative for what this run actually intends to download

If that is the intended meaning, then Option B is the cleaner model because:

- spreadsheet counts match the same list the loop will use
- durable planned-download state matches the same list the loop will use
- there is less semantic drift between discovery, reporting, and execution

So from a conceptual cleanliness standpoint, I think your reasoning is strong.

## What I think you are *not* overlooking

I think this part of your reasoning is solid:

- the initial WASAPI discovery result is useful operational input
- but that does not automatically mean it deserves durable manifest persistence in `state.json`

That is especially true in this project because the plan already treats:

- the filesystem and `state.json` as the source of truth for actual backup state
- the spreadsheet as reporting/control

If a discovered candidate is immediately disproved by the current filesystem check, persisting it as a planned file can create noise rather than value.

## The main factors to watch

I do think there are a few important factors to keep in mind.

### 1. Decide whether "filesystem-corrected" really means only `warc_path.exists()`

This is the biggest issue.

If Option B means:

- remove an item from the authoritative list whenever the destination WARC already exists

then you are implicitly saying that, for this step, **existing WARC means no remaining work**.

That may be fine if it matches the current production loop behavior.

But the project plan’s broader ideal says a file may still need work when:

- the WARC is missing
- size verification fails
- fixity sidecars are missing or invalid

So the key question is:

- do you want Option B to reflect the **current implementation rule**
- or the **full intended long-term rule**

My recommendation:

- for this step, make Option B match the **current real skip rule** in production
- if the current loop skips on WARC existence alone, then let the new authoritative list use that same rule
- do not expand this step to full fixity validation unless the current code already does that

That keeps the change small and honest.

### 2. Keep discovery information in logs if it is operationally useful

I agree that the broader discovery list does not necessarily need to live in `state.json`.

But it may still be worth logging summary information such as:

- raw discovered/merged candidate count
- corrected active-download count
- how many were excluded because they were already present

That gives you lightweight observability without polluting durable state.

I think this matches your instinct well:

- keep initial discovery info for partial persistence in logs
- avoid storing it as if it were authoritative download intent

### 3. Be careful not to lose retry-relevant information accidentally

This is the main practical caution I would raise.

If a file appears in the broader merged list because of reconciliation or retry logic, and then gets dropped from the authoritative active list because the WARC exists, ask:

- is there any current recovery behavior that relied on seeing that broader planned entry in `state.json`?

My guess is that the answer may be **no**, or at least **not much**, because once the WARC exists the file probably should not remain a planned-download item.

But this is still worth checking in code/tests before changing persistence semantics.

The main thing to confirm is that you are not accidentally removing some durable signal that current reconciliation logic expects on a later run.

### 4. Keep the loop-level defensive check anyway

Even with Option B, I would still keep the current loop-level `exists()` guard if it already exists.

Reason:

- the pre-loop correction makes the count accurate
- the loop-level check still protects against timing windows or unexpected local changes

So Option B should make the corrected list authoritative for planning/reporting/execution, but it should not eliminate cheap defensive checks.

## My recommendation on the design choice

I would recommend this concrete interpretation of Option B:

1. build the merged candidate list as today
2. derive one authoritative `active_downloads` list using the same rule the loop currently uses to decide "already present; skip"
3. persist planned-download manifest entries only for `active_downloads`
4. write spreadsheet planning/progress counts from `active_downloads`
5. log the raw merged count and the excluded count for visibility
6. keep the loop’s defensive existence check as a backstop

That gives you:

- cleaner durable state
- cleaner spreadsheet semantics
- less no-op work in the loop
- enough observability to understand what happened

## What would make me hesitate about Option B

I would only hesitate if code review shows one of these:

- current tests rely on pre-download manifest persistence for files that later get skipped as already present
- reconciliation logic depends on those broader planned entries remaining in `state.json`
- current reporting intentionally distinguishes between "discovered" and "needs download" and you want to preserve both concepts durably

If none of those are true, then I think Option B is the better fit.

## Bottom line

- I think Option B is likely the right direction.
- Your core idea is sound: after the filesystem correction step, the list should stop being a mere filter and become the authoritative download-intent list.
- I agree that the broader pre-correction discovery list does not obviously need to be persisted in `state.json`.
- The main thing to verify before implementation is whether current reconciliation/retry semantics depend on that broader planned persistence.
- If they do not, I would choose Option B and keep the broader discovery information only in logs/summary metrics.