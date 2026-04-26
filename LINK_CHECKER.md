# Automatic Link Checker

This repository contains an automatic link checker that runs twice a week (Monday and Friday at 5:00 AM UTC) to verify that all links in the markdown files are working properly.

## What the Link Checker Does

1. Checks all links in markdown files for:
   - **Broken links** (404, 500, connection errors, SSL errors, etc.)
   - **Insecure links** (HTTP instead of HTTPS)
   - **Spam / blacklisted links** (domains listed in the [URLhaus](https://urlhaus.abuse.ch/) malware/spam database)

2. Generates a `LINK_CHECKER_REPORT.md` file summarising all problematic links found, including:
   - The URL
   - The file where the link appears
   - The type of issue (broken, insecure, or spam/blacklisted)

3. Opens (or updates) a pull request on the `automated/link-checker-report` branch so maintainers can review the findings.

4. Avoids rechecking links (and spamming the URLhaus API) for 60 days once they have been reviewed.

## How Issues Are Handled

When a PR is raised:

1. A maintainer reviews the `LINK_CHECKER_REPORT.md` in the PR.
2. For each problematic link, either:
   - Fix the link (update the URL or switch from HTTP to HTTPS)
   - Remove the link if it is no longer relevant
   - Keep the link if appropriate (e.g. historical reference)
3. Merge or close the PR once all issues are addressed.

## Manual Triggers

Maintainers can manually trigger the link check from the **Actions** tab in the GitHub repository by selecting the *Broken Link Checker* workflow and clicking **Run workflow**.

## Technical Details

The link checker is implemented as a GitHub Action workflow using Python:

- Workflow configuration: `.github/workflows/link-checker.yml`
- Script: `.github/scripts/link_checker.py`
- Cache file: `.github/scripts/link_check_cache.json` (committed back to the default branch after each run)

The cache tracks previously checked links and URLhaus lookups to avoid duplicate work.

