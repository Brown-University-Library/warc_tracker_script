# warc-tracker-script

## Purpose

This is an under-development script to track WARC files downloaded (for backup purposes) from the Internet Archive.

(Eventual) Features:

- If given a collection-id or a list of collection-ids, it will:
  - Query the Internet Archive API to get a list of WARC files for those collections.
  - Query the existing tracker google-doc spreadsheet to see which WARC files have already been downloaded.
  - Download the WARC files that haven't already been downloaded.
  - Update the google-doc spreadsheet to add any newly downloaded WARC files.
  - Update the google-doc spreadsheet to indicate the last-checked date for each WARC file.

- If run without a collection-id or collection-ids, it will:
  - Query the existing tracker google-doc spreadsheet to see which WARC files have already been downloaded.
  - Determine collections to check via certain columns like "Active"
  - Check that collection via it's collection-id -- as described above.

---
