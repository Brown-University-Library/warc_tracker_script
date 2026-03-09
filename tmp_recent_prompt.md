- re the plan at `warc_tracker_script/PLAN__next_single_step.md`, re the section:

"""
### 4. Decide the interaction with manifest persistence

This is the most important design choice in the step.

Evaluate the two concrete options against existing code and tests:

- **Option A:** persist the broader planned list, then filter to `active_downloads` only for reporting and loop execution
- **Option B:** filter first, then persist only `active_downloads` as planned-download manifest entries
"""

I'm thinking Option-B is the way I want to go. My thought is:
- we perform initial discovery on the WASAPI
- we correct that file a file-system check, so that the new list of files-to-be-downloaded isn't just a "filter" -- it's truly accurate.
- we can log the _initial_ discovery info for partial persistence -- but I'm not seeing the need to keep it in state.json

Please do tell me if I'm overlooking important factors.

- Save your response to `warc_tracker_script/tmp_model_answer.md`, overwriting the previous file. 

- save the text of this prompt to `warc_tracker_script/tmp_recent_prompt.md`, overwriting the previous file.
