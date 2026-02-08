# warc-tracker-script

## Decisions made

### store-time and lookback

One of the first steps will be to determine what files to download. I'll know, from a tracking-spreadsheet, which Collections are still "Active" and some sort of date associate with them. Some common dates associated with WARC files:
crawl-start-time, crawl-time, and store-time. The store-time can be many days after the crawl-start-time. My plan is to focus exclusively on store-time. I'm assuming the digital-preservation team has their own interface for tracking crawls. The purpose of this script, and its associated tracking-spreadsheet, is to track the backup process. 

Therefore, I'll use logic something like:
- For an active Collection, look at the last-stored-time of a backed-up WARC file.
- Look for _new_ WARC files to back up after the last-stored-time -- minus one-month.

Why the one-month lookback?

Here's an example...

Let's say I need to backup three WARC files with stored-dates (I'll use dates instead of timestamps for the example):
- Feb-02
- Feb-04
- Feb-06

Let's say they're all being downloaded, but some network-issue prevents the Feb-04 file from being backed up. If I just save Feb-06 as my last-stored-time -- the next time I run my script I won't try to re-download the Feb-04 file. 

But if I say: Look for new files downloaded since Feb-06 with a one-month lookback -- that would catch the missing Feb-04 file.

---

