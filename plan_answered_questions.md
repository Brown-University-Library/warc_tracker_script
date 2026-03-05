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