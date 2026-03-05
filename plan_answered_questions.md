## in-progress-marker question

I like the idea of the `**Option 2: "In Progress" marker**`, below.

Should that marker include the new lightweight-identifier?

**Answer:**

Yes. The in-progress marker should include the `run_id` (lightweight identifier). Here's why:

**Benefits:**
- **Traceability:** Links the spreadsheet status directly to specific log files and local state (e.g., `run-20250305-143000-a1b2.json`)
- **Debugging:** If a collection appears "stuck" in progress, staff can identify which run left the marker and check the corresponding logs
- **Audit correlation:** Enables quick cross-reference between the spreadsheet view and the actual execution context

**Suggested format:**
```
In Progress (run: 20250305-143000-a1b2)
```

This combines human-readable status with the concise identifier from line 400-405 of PLAN__warc_backup_script_v03.md.

---


## status-glance question

If I were to view the status spreadsheet -- how would I tell, from the spreadsheet, the status of the current-script running -- assuming there was a script running?

**Answer:**

Based on the plan, here is how to determine script status from the spreadsheet:

**Option 1: "Last WASAPI fetch" timestamp** (primary indicator)
- This field is updated when processing completes successfully for a collection
- If the timestamp is recent (within expected run interval), the script likely completed its last run
- If the timestamp is stale for a collection, either the script isn't processing that collection or it failed

**Option 2: "In Progress" marker** (if implemented)
- The plan mentions optionally writing "in progress" markers during processing (line 354 of PLAN__warc_backup_script_v03.md)
- This would explicitly indicate active processing for a specific collection

**Option 3: Staff observation via run-lock**
- The plan recommends using a file-based lock (`flock`) to prevent overlapping runs (line 479)
- This lock exists outside the spreadsheet, but a coordinating process could write a status cell

**Important caveat:** The plan emphasizes that the **local manifest/state is the source of truth**, while the spreadsheet is primarily a reporting/control plane that can lag slightly. For real-time status, you would need to check the local state directory's run-lock or run logs rather than relying solely on the spreadsheet.

---


## script-run-identifier

Might there be benefits for a script-run-identifier? If so, enumerate them. If not, explain why not. Thx.

**Answer:**

Yes, there are operational benefits to a lightweight **script-run-identifier**, though it is not strictly required for correctness.

**Benefits:**

- **Audit trail correlation** — The plan specifies a `runs/{timestamp}.json` log structure. A unique run ID ties together all log entries, sheet updates, and per-collection state changes from a specific invocation, making post-run debugging easier.
- **Sheet update tracing** — Multiple update batches may be written during a single run (flushing every N files). A run ID helps distinguish "updates from today's 9am run" from "yesterday's interrupted run."
- **Error context** — When failures occur (WASAPI pagination incomplete, download retries), embedding the run ID in logs helps trace failures back to specific execution context.
- **Recoverability analysis** — When reviewing `_state/runs/*.json` files later, a run ID makes it trivial to cross-reference with external logs (cron emails, monitoring alerts).

**Why it is not strictly necessary:**

- The script is **idempotent** and **checkpoint-driven** — correctness depends on watermark and filename dedupe, not run identity.
- A **timestamp** (ISO8601) already serves as a practical identifier for the per-run JSON log file.
- Overlapping runs are prevented by a **lock file**, not by run ID coordination.

**Recommendation:**

Use a **timestamp-based identifier** (e.g., `2025-03-05T14:30:00Z` or short hash `20250305-143000-a1b2`). Include it in:
- The per-run JSON filename and contents
- Log entries (structured logging)
- Optional metadata in sheet updates

This adds minimal complexity while supporting operational debugging without changing core checkpoint logic.

---


## "active" check

If one of the first things the script does is check to see if a collection is active, and, if it is, proceed -- what is preventing a re-run of the script, 30-seconds later from duplicating work underway?

---

**Answer:**

The plan prevents duplicate work through three layered mechanisms:

### 1. Run-level locking (prevents concurrent runs)

From the "Cron concerns" section (@PLAN__warc_backup_script_v02.md:470):
- Use a file lock (e.g., `flock`) so only one script instance runs at a time
- A re-run 30 seconds later would block or exit immediately if the previous run is still active

### 2. Per-filename manifest (prevents re-downloading)

From "Checkpointing" (@PLAN__warc_backup_script_v02.md:62-63):
- `per_filename_status` tracks every file: `status` (`downloaded`/`failed`/`missing`), `last_attempt_at`, `error_count`
- Before downloading, the script checks if the file already exists locally with matching size/fixity, or is marked downloaded in the manifest
- Files are deduplicated by filename—same filename = skip

### 3. Watermark + overlap window (prevents enumeration gaps)

From "Checkpoint semantics" (@PLAN__warc_backup_script_v02.md:54-77):
- The script records `enumeration_watermark_store_time_max`—the newest `store-time` from the last **complete** enumeration
- The query uses a **30-day lookback window**: `after_datetime = watermark - 30 days`
- This means the second run will re-query the same 30-day window but **skip already-downloaded files** via filename dedupe
- The watermark only advances after successful full pagination, so interrupted runs don't lose their place

**Key insight:** The "Active" check only determines *which collections to process*—it doesn't determine *what work to do*. The local manifest and watermark are the source of truth for "what's already done", not the spreadsheet's Active flag.