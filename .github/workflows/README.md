# Link Checker GitHub Action

This GitHub Action automatically checks markdown files in the repository for broken and insecure links.

## How It Works

1. The action runs on a schedule: every Monday and Friday at 5:00 AM UTC.
2. It scans all markdown files in the repository for links.
3. Each link is checked for:
   - Broken status (404, 500, etc. error codes)
   - Insecure protocol (HTTP instead of HTTPS)
4. For problematic links, a GitHub issue is created automatically.
5. To prevent duplicate issues, the action maintains a cache of previously checked links.
6. Links that have been reviewed (issue closed) within the last 60 days won't generate new issues.

## Cache File

The action uses a `.link_check_cache.json` file to keep track of checked links and their review status.

## Manual Triggering

You can also manually trigger the link check by going to the "Actions" tab in the repository and selecting "Broken Link Checker" workflow.

## Dependencies

The action uses Python with the following packages:
- requests
- markdown
- beautifulsoup4
- PyGithub

These are automatically installed by the workflow.
