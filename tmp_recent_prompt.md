- review `warc_tracker_script/AGENTS.md` for coding-directives to follow.

- review `warc_tracker_script/PLAN__simplified_warc_backup_script.md` for an overview of the whole project.

- review ``warc_tracker_script/tmp_recent_prompt.md` to understand my last evaluation-of-wasapi-discovery question.

- review `warc_tracker_script/tmp_model_answer.md` to understand your last evaluation-of-wasapi-discovery answer.

- I'm thinking that if, after wasapi-discovery, we want a true  "evaluation" to determine what we actually need to download, that evaluation-step should not just check whether the file already exists -- but perform the other important checks such as size-verification, fixity-info, etc. That way, the "filtered" list is both accurate for reporting, and accurate for the deeper backup goal.

- Given this, redo your thorough implementation plan and save it to `warc_tracker_script/PLAN__next_single_step.md`, overwriting the previous file.

- save the text of this prompt to `warc_tracker_script/tmp_recent_prompt.md`, overwriting the previous file.
