# Automatic Link Checker

This repository contains an automatic link checker that runs twice a week (Monday and Friday at 5:00 AM) to verify that all links in the markdown files are working properly.

## What the Link Checker Does

1. Checks all links in markdown files for:
   - Broken links (404, 500, etc.)
   - Insecure links (HTTP instead of HTTPS)

2. Creates GitHub issues for problematic links, including:
   - The problematic URL
   - The file where the link was found
   - The issue type (broken or insecure)

3. Avoids creating duplicate issues for links that were already reviewed within the last 60 days.

## How Issues Are Handled

When an issue is created:

1. A maintainer should review the problematic link.
2. Action can be taken to:
   - Fix the link (by updating to a working URL or switching from HTTP to HTTPS)
   - Remove the link if it's no longer relevant
   - Keep the link as-is if appropriate (e.g., historical reference)

3. After taking action, close the issue.

4. If a link was fixed or intentionally kept, it won't be flagged again for at least 60 days.

## Manual Triggers

Maintainers can manually trigger the link check from the Actions tab in the GitHub repository.

## Technical Details

The link checker is implemented as a GitHub Action workflow using Python. The workflow configuration is in `.github/workflows/link-checker.yml` and the script is in `.github/scripts/link_checker.py`.

The script maintains a cache file (`.link_check_cache.json`) to track the status of previously checked links and avoid creating duplicate issues.
