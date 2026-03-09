# Ideas for making the denominator more accurate / expected

I reviewed:
- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`

## Short answer

Yes, your idea of an early filesystem check is a reasonable and fairly simple option.

I think the main question is not whether it can work, but **where** the count should become authoritative:

- at **planning time**
- at **download-start time**
- or only in the **wording** of the status text

My view is that the simplest and cleanest option is:

- make the denominator mean **files that actually still require download work right now**
- compute that before writing the initial `downloading-in-progress` status

That would make your `7` become `6` before the user sees the download-progress denominator.

## The current mismatch

Right now, the denominator comes from the merged `planned_downloads` list.

That list can contain:

- retry candidates that really need work
- rediscovered files that no longer need work because the destination file already exists

Later, the download loop notices the existing file and skips it.

So the current denominator is really:

- **planned candidates**

not:

- **actual downloads still needed**

That is why the visible count can feel off.

## Simple possibilities

### Option 1: filter the planned-download list before writing download-start status

This is the most straightforward fix.

Idea:

- after building and merging `planned_downloads`
- do one pass over that list
- remove any item whose destination WARC already exists on disk
- use the filtered list for:
  - `download planning complete`
  - `downloading in progress`
  - the actual download loop

### Why this is attractive

- it keeps one consistent meaning of count
- the denominator reflects real remaining work
- the final success count is less surprising
- it reduces no-op entries flowing into the download loop

### Why this could be slightly tricky

The main subtlety is semantic:

- if you remove existing files from `planned_downloads`, then `download planning complete` will no longer mean "all discovered + retry-derived candidates"
- it will mean "all candidates that still need download work after a fresh on-disk existence check"

I think that is probably the better meaning for the spreadsheet, but it is a behavior change.

### My opinion

This is probably the best option.

## Option 2: keep `planned_downloads` as-is, but do an immediate pre-download pruning step

This is very close to the option you proposed.

Idea:

- keep current planning logic unchanged
- write `download planning complete` based on raw planned candidates if desired
- before writing `downloading-in-progress`, do a quick filesystem recheck
- build `active_downloads` from only the entries whose destination does not already exist
- use `active_downloads` for the denominator and for the actual loop

So the statuses might become:

- `download planning complete -- 7 files planned`
- `downloading-in-progress -- 0% (0/6 files)`

### Why this is attractive

- it is a smaller conceptual change than redefining all planning counts
- it preserves a distinction between:
  - planning candidates
  - actual work queue
- it directly addresses your concern

### Why this could feel odd

The user may still see:

- `7 files planned`
- then immediately `0/6 files`

That is more defensible than the current behavior, but still slightly surprising unless the detail text explains why.

For example, you might want wording like:

- `0% (0/6 files needing download)`

or:

- `0% (0/6 files; 1 already present)`

### My opinion

This is a very reasonable low-risk option if you want to preserve the existing planning concept.

## Option 3: keep the counts, but improve the wording

Idea:

- do not change planning or loop behavior
- change the status wording so the denominator is explicitly understood as planned candidates

Examples:

- `downloading-in-progress -- 0% (0/7 planned items)`
- final: `6 downloads completed successfully; 1 already present`

### Why this is attractive

- smallest code/behavior change
- avoids rethinking the orchestration flow
- preserves current internal semantics

### Why I think it is weaker

It is accurate, but probably less intuitive for an operator.

Most people will read `(x/y files)` as:

- files that still needed downloading

not:

- entries that were once considered for work

So this fixes confusion mostly by explanation, not by making the number itself match expectation.

### My opinion

This is acceptable, but not my preferred fix.

## Option 4: count downloaded-or-already-present as completed progress

Idea:

- keep the denominator at 7
- when the loop sees an already-existing file, count it as completed progress
- then the final message would also need to acknowledge that one item was already present

For example:

- start: `0% (0/7 files)`
- after skip-existing + 6 downloads: effectively `7/7 complete`
- final: `6 downloaded, 1 already present`

### Why this is attractive

- it preserves the full planned-candidate denominator
- progress becomes internally consistent

### Why it is probably not ideal here

It blurs the meaning of `completed`:

- some completions are actual downloads
- some are no-op existing files

That can be valid, but I think it is less aligned with the current wording `file downloads completed successfully`.

### My opinion

Reasonable, but not as clean as shrinking the active denominator.

## What problems could an early filesystem recheck introduce?

Your idea is good, but there are a few things to watch.

### 1. Meaning drift between planning and download-start

If one status says `7 planned` and the next says `6 files`, the operator may ask why the count changed.

That is solvable, but the wording should be deliberate.

### 2. Existence is a weaker check than full correctness

The project plan says a file may still need work if:

- the WARC is missing
- size verification fails
- fixity sidecars are missing or invalid

So if the early recheck only asks `does the WARC path exist?`, then it may undercount work in cases where:

- the WARC exists but fixity is missing
- the WARC exists but is bad/incomplete in a way the current existence check would miss

This is the biggest conceptual caveat.

If you want the denominator to mean **remaining work**, the recheck should ideally use the same notion of "needs work" that the planner is supposed to use, not just plain file existence.

### 3. Slight duplication of decision logic

If you add a quick pre-download filter in one place but keep the download loop doing its own existence skip, you now have two gates.

That is not terrible, but it is better if both rely on one helper so the rule is defined once.

### 4. Small race-window concerns

In the current sequential flow, this is probably minor.

But conceptually, between:

- the pre-download recheck
- and the actual download attempt

the filesystem could change.

So the loop should probably still keep its defensive skip check anyway.

That means the recheck improves the denominator, but does not eliminate the need for the loop-level guard.

## The simplest design I would recommend

I would recommend a small helper with a meaning like:

- `planned item still requires download/fixity work now`

Then use that helper in one place just before writing `downloading-in-progress`.

Concretely:

1. Build the broader merged planned list as you do now.
2. Derive an `active_downloads` list from it using a helper.
3. Write the download-start denominator from `len(active_downloads)`.
4. Run the actual loop over `active_downloads`.
5. Keep the loop's defensive existence check anyway.

That gives you the main improvement you want without a large redesign.

## If you want the absolute minimum change

Then I would do this:

- keep planning as-is
- add a quick pre-download filter for already-existing destinations
- use the filtered list for the download-start denominator and loop
- leave `download planning complete` alone for now

That would likely turn your specific case into:

- planning: `7 files planned`
- download start: `0% (0/6 files)`
- final: `6 file downloads completed successfully`

That is already much easier to understand.

## If you want the cleanest operator-facing behavior

Then I would go one step further:

- redefine the spreadsheet-facing count to mean **files that still require work**
- use that same count consistently for planning, download start, and progress

That is slightly more invasive conceptually, but it gives the most natural user experience.

## My recommendation

My ranking would be:

1. **Best balance:** pre-download filtering into an `active_downloads` list, then use that denominator for `downloading-in-progress` and the loop.
2. **Cleanest semantics:** redefine planning counts too, so all spreadsheet-visible counts mean remaining work.
3. **Lowest effort:** leave logic alone and improve wording.

## Bottom line

- Your early filesystem-check idea is sound.
- The biggest thing to watch is that `exists()` is not always the same as `needs no more work`.
- A simple pre-download filtering step is probably the best low-risk improvement.
- If done carefully, it should make the denominator feel much more expected without introducing major new problems.