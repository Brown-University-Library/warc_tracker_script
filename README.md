# warc-tracker-script

## gspread documentation
<https://docs.gspread.org/en/latest/>


## Purpose

This is an under-development script to track WARC files downloaded (for backup purposes) from the Internet Archive.

## Features (eventual)

- If given a collection-id or a list of collection-ids, it will, for each collection-id:
  - Query the existing tracker google-doc spreadsheet to see which WARC files have already been downloaded.
  - Query the Internet Archive API to get a list of WARC files for that collection.
  - Download the WARC files that haven't already been downloaded.
  - Update the google-doc spreadsheet to add any newly downloaded WARC files.
    - path will be listed
    - last-checked date will be listed

- If run without a collection-id or collection-ids, it will:
  - Determine collections to check via certain columns like "Active"
  - For each collection, do the above.

## Work-plan
- [ ] Determine whether to _start_ with a google-spreadsheet or an editable webpage to list and track collections and crawls.
    - Thinking: g-spreadsheet _is_ absolutely the way to go for production, but might require a solid investment of time to re-implement our ability to update google-docs programmatically from a brown account.
    - For now, we need to display a source of truth for active collections (maybe just reference the active google spreadsheets that H already uses?) -- so I may go with a tabulator.js page initially.
    - Result: 
        - going to try gsheet
        - this week researched tabulator.js and was impressed with tabulator.js
        - will spend Mon-Nov-10 working on the gsheet

---
