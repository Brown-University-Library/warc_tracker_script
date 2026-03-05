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
