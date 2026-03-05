## in-progress-marker question

I like the idea of the `**Option 2: "In Progress" marker**`, below.

Should that marker include the new lightweight-identifier?

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
