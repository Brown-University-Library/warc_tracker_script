# Next Single Step: Filesystem-Reconciliation Retry Guarantee
 
 ## Context for Future Agents
 
 **Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.
 
 **Plan references**:
 
 - `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
 - `warc_tracker_script/PLAN__suggest_retry_guarantees.md`
 
 **Focus of this step**: implement the chosen **filesystem-reconciliation** approach so future runs retry failed downloads and also recover any files that are missing on disk but still represented in `state.json`.
 
 The intended behavior is:
 
 - load a collection's `state.json`
 - review all manifest entries under `files`
 - compare each entry's expected `warc_path` against the filesystem
 - if a manifest entry has a usable `source_url` and its WARC file is missing on disk, queue it for download
 - merge those reconciliation-driven retry candidates with normal WASAPI discovery candidates
 - deduplicate by filename before the existing sequential download loop runs
 
 This should be implemented with the smallest clear change in the existing sequential orchestration.
 
 ---
 ## Goal of This Step
 
 Add one reconciliation-based planning step to the current flow so the downloader no longer depends only on fresh WASAPI rediscovery to retry known missing files.
 
 Specifically:
 
 1. load the collection's local `state.json`
 2. inspect all manifest entries in `state['files']`
 3. identify entries that have both:
    - a usable `source_url`
    - a usable `warc_path` whose file is currently absent on disk
 4. convert those entries into planned download candidates
 5. merge them with discovery-based planned downloads
 6. deduplicate by filename
 7. let the existing sequential download/fixity loop process the merged set
 
 That is the whole feature for this step.
 
 ---
 ## Why This Is the Right Next Step
 
 1. **It matches the user's chosen approach**
    - the selected plan is Option 2 from `PLAN__suggest_retry_guarantees.md`
    - the core idea is filesystem reconciliation against manifest entries
 
 2. **It gives the desired guarantee**
    - failed downloads will be retried if their local WARC is still absent
    - missing files can be recovered even if they are no longer rediscovered by the current overlap window
 
 3. **It fits the master plan's source-of-truth model**
    - the local filesystem remains the source of truth for actual WARC presence
    - `state.json` remains the operational manifest and checkpoint store
 
 4. **It fits the current code shape**
    - `main.py` stays thin
    - `lib/orchestration.py` remains the place where candidate downloads are assembled
    - `run_planned_downloads()` can remain mostly unchanged because it already uses filesystem existence checks
 
 ---
 ## Specific Implementation Plan
 
 ### 1. Add a helper that builds reconciliation retry candidates from `state.json`
 
 In `lib/orchestration.py`, add a helper that scans the loaded collection state and returns `PlannedDownload` items for manifest entries that should be retried.
 
 The helper should:
 
 - read `state.get('files')`
 - ignore entries that are not dictionaries
 - require a non-empty filename key
 - require a usable `source_url`
 - require a usable `warc_path`
 - check whether `Path(warc_path).exists()`
 - if the WARC exists, do not queue it
 - if the WARC is missing, derive planned paths for that filename using `plan_collection_paths()` rather than trusting sidecar paths from state
 - return a list of `PlannedDownload` objects
 
 Important design choice:
 
 - use the manifest entry only to discover that a file is missing and recover its `source_url`
 - use `plan_collection_paths()` to rebuild the canonical local paths so the orchestration continues to rely on the current storage-layout rules
 
 ### 2. Add a helper that merges and deduplicates planned downloads by filename
 
 The current code already builds discovery-based `planned_downloads`.
 
 Add a small helper that merges:
 
 - reconciliation-based retry candidates from state
 - discovery-based candidates from WASAPI
 
 Deduplicate by filename.
 
 Recommended merge rule for this step:
 
 - prefer the discovery-based candidate when the same filename appears in both sources
 - otherwise keep whichever single candidate exists
 
 This keeps normal discovery authoritative when available, while still guaranteeing retries for missing files that are no longer rediscovered.
 
 ### 3. Integrate reconciliation before `run_planned_downloads()`
 
 In `process_collection_job()`:
 
 - keep the existing discovery flow
 - keep the existing checkpoint handling
 - keep the existing discovery-based planning
 - build reconciliation candidates from the loaded state
 - merge reconciliation candidates with discovery candidates
 - pass the merged list to `run_planned_downloads()`
 
 Keep the current sequential flow intact. The main change is to how `planned_downloads` is assembled.
 
 ### 4. Keep the existing filesystem-based skip behavior
 
 Do not redesign `run_planned_downloads()` in this step beyond what is strictly needed.
 
 The current behavior is already aligned with the chosen approach:
 
 - the downloader checks `destination_path.exists()` on disk
 - if the WARC exists locally, it skips download
 - if the WARC is absent, it attempts the download
 
 That means the new reconciliation candidates can flow through the existing loop without needing a separate retry execution path.
 
 ### 5. Add logging that distinguishes reconciliation candidates from discovery candidates
 
 Add or adjust logging so operators can see:
 
 - how many candidates came from state/disk reconciliation
 - how many came from fresh WASAPI discovery
 - how many remained after deduplication
 
 This is important because the new guarantee depends on more than just overlap-window rediscovery, and the logs should make that visible.
 
 ---
 ## Likely Code Touch Points
 
 - `warc_tracker_script/lib/orchestration.py`
   - add a helper to build reconciliation-based retry candidates from manifest entries
   - add a helper to merge and deduplicate planned downloads
   - update `process_collection_job()` to use the merged set
 - `warc_tracker_script/tests/test_orchestration.py`
   - add focused tests for reconciliation candidate creation and merged planning behavior
 - `warc_tracker_script/tests/test_collection_state.py`
   - only if existing state-focused tests need to be expanded for malformed or partial manifest-entry cases
 
 Keep `main.py`, `downloader.py`, and `local_state.py` unchanged unless a very small supporting edit is clearly needed.
 
 ---
 ## Minimum Test Coverage
 
 Add focused `unittest` coverage for:
 
 - manifest entry with missing local WARC and usable `source_url` => queued for retry
 - manifest entry with existing local WARC => not queued for retry
 - malformed manifest entry without usable `source_url` or `warc_path` => skipped safely
 - filename present in both reconciliation candidates and discovery candidates => deduplicated to one planned download
 - reconciliation-only missing file is passed into the existing sequential download flow
 
 The tests do not need to cover spreadsheet updates or Trio behavior for this step.
 
 ---
 ## Out of Scope for This Step
 
 - retry backoff or retry throttling based on `last_attempt_at`
 - verification of local file size against remote metadata
 - validation or regeneration of missing fixity sidecars for otherwise present WARC files
 - spreadsheet write/update behavior
 - Trio concurrency
 - lock/cron wrapper hardening
 
 ---
 ## Success Criteria
 
 - [ ] a manifest entry with a missing local WARC and usable `source_url` is retried in a future run even if WASAPI does not rediscover it
 - [ ] a manifest entry whose local WARC already exists is not redundantly re-downloaded
 - [ ] discovery-based planned downloads and reconciliation-based retry candidates are merged and deduplicated by filename
 - [ ] the current sequential production flow remains the main execution path
 - [ ] focused `unittest` coverage exists for reconciliation-driven retry behavior
 
 ---
 ## Likely Follow-Up After This Step
 
 1. decide whether missing fixity sidecars for present WARCs should also be reconciled automatically
 2. add optional retry throttling for repeatedly failing URLs
 3. improve spreadsheet reporting so logs and sheet status can distinguish discovery-driven downloads from reconciliation-driven retries
 
 ---
 ## Handoff Notes
 
 If you pick this up in a new session, re-read:
 
 - `warc_tracker_script/AGENTS.md`
 - `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
 - `warc_tracker_script/PLAN__suggest_retry_guarantees.md`
 - `warc_tracker_script/PLAN__next_single_step.md`
 
 Quick mental model:
 
 - this step is about **reconciling `state.json` against the filesystem**
 - `state.json` tells you what files the collection thinks it knows about
 - the filesystem tells you whether a WARC is actually present
 - if state knows about a file and disk does not have it, queue it for download
 - merge that queue with normal WASAPI discovery results and let the current sequential download loop handle the rest
