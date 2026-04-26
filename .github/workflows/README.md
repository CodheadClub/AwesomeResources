# Link Checker GitHub Action

This GitHub Action automatically checks markdown files in the repository for broken, insecure, and blacklisted links.

## How It Works

1. The action runs on a schedule: every Monday and Friday at 5:00 AM UTC.
2. It scans all markdown files in the repository for links.
3. Each link is checked for:
   - **Broken** status (404, 500, connection errors, etc.)
   - **Insecure** protocol (HTTP instead of HTTPS)
   - **Spam / blacklisted** hostname (via the [URLhaus](https://urlhaus.abuse.ch/) API)
4. A `LINK_CHECKER_REPORT.md` file is generated and pushed to the `automated/link-checker-report` branch.
5. A pull request is opened (or updated) for maintainers to review.

## Cache File

The action uses `.github/scripts/link_check_cache.json` to track previously checked links and URLhaus lookups. Results are reused for 60 days to avoid duplicate work.

## Manual Triggering

You can also manually trigger the link check by going to the **Actions** tab in the repository and selecting the *Broken Link Checker* workflow.

## Dependencies

The action uses Python with the following packages:
- `requests`
- `beautifulsoup4`
- `PyGithub`

These are automatically installed by the workflow.

