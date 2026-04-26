#!/usr/bin/env python3
"""
Link checker for markdown files in the AwesomeResources repository.
Checks for broken links, insecure links (HTTP), and spam/blacklisted URLs.
Creates a pull request containing a LINK_CHECKER_REPORT.md summary of all
problematic links found.
"""

import os
import re
import json
import datetime
import requests
from bs4 import BeautifulSoup
from github import Github, GithubException, Auth
from urllib.parse import urlparse

# Constants
CACHE_FILE = '.github/scripts/link_check_cache.json'
REPORT_BRANCH = 'automated/link-checker-report'
REPORT_FILE = 'LINK_CHECKER_REPORT.md'
MARKDOWN_EXTENSIONS = ['.md', '.markdown']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
TIMEOUT = 30          # seconds for HTTP requests
RETRY_COUNT = 2       # retries per link
REVIEW_PERIOD_DAYS = 60  # don't recheck links reviewed within this period
ERROR_CODES = [404, 500, 502, 503, 504]
URLHAUS_HOST_API = 'https://urlhaus-api.abuse.ch/v1/host/'
SKIP_DOMAINS = {'localhost', '127.0.0.1', 'example.com', 'example.org'}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def load_cache():
    """Load the cache of previously checked links."""
    try:
        with open(CACHE_FILE, 'r') as fh:
            data = json.load(fh)
            print(f"Loaded cache with {len(data)} entries")
            return data
    except FileNotFoundError:
        print(f"Cache file '{CACHE_FILE}' not found, creating new cache")
        return {}
    except json.JSONDecodeError:
        print("Error parsing cache file, creating new cache")
        return {}


def save_cache(cache):
    """Persist the cache to disk."""
    try:
        with open(CACHE_FILE, 'w') as fh:
            json.dump(cache, fh, indent=2)
        print(f"Saved cache with {len(cache)} entries")
    except Exception as exc:
        print(f"Error saving cache: {exc}")


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------

def extract_links_from_markdown(file_path):
    """Return a deduplicated list of HTTP/HTTPS URLs found in a markdown file."""
    with open(file_path, 'r', encoding='utf-8') as fh:
        content = fh.read()

    # Inline markdown links: [text](url)
    markdown_links = re.findall(r'\[.+?\]\((https?://[^\s)]+)\)', content)

    # HTML anchor tags
    html_links = []
    soup = BeautifulSoup(content, 'html.parser')
    for tag in soup.find_all('a', href=True):
        if tag['href'].startswith(('http://', 'https://')):
            html_links.append(tag['href'])

    return list(set(markdown_links + html_links))


# ---------------------------------------------------------------------------
# Link checking
# ---------------------------------------------------------------------------

def check_link(url):
    """
    Check a URL for availability.

    Returns:
        (is_broken: bool, is_insecure: bool, status_code: str|int)
    """
    parsed = urlparse(url)
    is_insecure = parsed.scheme == 'http'

    if parsed.netloc in SKIP_DOMAINS:
        return False, is_insecure, 200

    status_code = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            # Try HEAD first (cheaper)
            try:
                resp = requests.head(url, headers=HEADERS, timeout=TIMEOUT,
                                     allow_redirects=True)
                if resp.status_code < 400:
                    return False, is_insecure, resp.status_code
            except requests.exceptions.RequestException:
                pass  # Some servers don't support HEAD

            # Fall back to streaming GET
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                                allow_redirects=True, stream=True)
            for _ in resp.iter_content(chunk_size=1024):
                break
            resp.close()

            is_broken = resp.status_code in ERROR_CODES
            return is_broken, is_insecure, resp.status_code

        except requests.exceptions.Timeout:
            print(f"Timeout for {url} (attempt {attempt + 1}/{RETRY_COUNT + 1})")
            status_code = "Timeout"

        except requests.exceptions.SSLError:
            print(f"SSL error for {url}")
            return True, is_insecure, "SSL Error"

        except requests.exceptions.ConnectionError:
            print(f"Connection error for {url}")
            return True, is_insecure, "Connection Error"

        except Exception as exc:
            print(f"Unexpected error checking {url}: {exc}")
            status_code = str(exc)[:50]

    return True, is_insecure, status_code


def check_spam_blacklist(url, cache):
    """
    Check whether the URL's hostname is listed in the URLhaus blacklist.

    Results are cached inside the shared cache dict under 'urlhaus:<host>'
    keys to avoid hammering the API on repeated runs.

    Returns:
        (is_blacklisted: bool, threat: str|None)
    """
    host = urlparse(url).netloc
    if not host:
        return False, None

    cache_key = f'urlhaus:{host}'
    if cache_key in cache:
        entry = cache[cache_key]
        last_checked = datetime.datetime.fromisoformat(entry['last_checked'])
        if (datetime.datetime.now() - last_checked).days < REVIEW_PERIOD_DAYS:
            return entry['is_blacklisted'], entry.get('threat')

    try:
        resp = requests.post(URLHAUS_HOST_API, data={'host': host}, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            is_blacklisted = data.get('query_status') == 'is_listed'
            threat = None
            if is_blacklisted and data.get('urls'):
                threat = data['urls'][0].get('threat', 'blacklisted')
            cache[cache_key] = {
                'last_checked': datetime.datetime.now().isoformat(),
                'is_blacklisted': is_blacklisted,
                'threat': threat,
            }
            return is_blacklisted, threat
    except Exception as exc:
        print(f"Error querying URLhaus for {host}: {exc}")

    return False, None


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results):
    """
    Build a markdown report from the collected results.

    Args:
        results: dict with keys 'broken', 'insecure', 'spam', each a list
                 of dicts with at least 'url' and 'file' keys.

    Returns:
        str: markdown content
    """
    today = datetime.date.today().isoformat()
    broken = results.get('broken', [])
    insecure = results.get('insecure', [])
    spam = results.get('spam', [])
    total = len(broken) + len(insecure) + len(spam)

    lines = [
        "# Link Checker Report",
        "",
        f"_Last updated: {today}_",
        "",
        "This report is automatically maintained by the "
        "[Link Checker workflow](.github/workflows/link-checker.yml). "
        "Please review and fix any issues listed below.",
        "",
    ]

    if total == 0:
        lines.append("✅ **All links are healthy!** No issues found.")
    else:
        lines.append(f"**{total} issue(s) found** requiring attention.")
        lines.append("")

        if broken:
            lines += [
                f"## ❌ Broken Links ({len(broken)})",
                "",
                "| URL | File | Status |",
                "|-----|------|--------|",
            ]
            for item in broken:
                lines.append(
                    f"| `{item['url']}` | `{item['file']}` | {item['status']} |"
                )
            lines.append("")

        if insecure:
            lines += [
                f"## ⚠️ Insecure Links — HTTP instead of HTTPS ({len(insecure)})",
                "",
                "| URL | File |",
                "|-----|------|",
            ]
            for item in insecure:
                lines.append(f"| `{item['url']}` | `{item['file']}` |")
            lines.append("")

        if spam:
            lines += [
                f"## 🚨 Potentially Spam / Blacklisted Links ({len(spam)})",
                "",
                "| URL | File | Threat |",
                "|-----|------|--------|",
            ]
            for item in spam:
                lines.append(
                    f"| `{item['url']}` | `{item['file']}` | {item.get('threat', 'blacklisted')} |"
                )
            lines.append("")

    lines += [
        "---",
        "*This report was automatically created by the "
        "[Link Checker GitHub Action](.github/workflows/link-checker.yml).*",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# PR creation / update
# ---------------------------------------------------------------------------

def create_or_update_pr(github_client, repo_name, report_content, has_issues):
    """
    Push the report to the report branch and create or update a PR.

    The report branch is reset to the tip of the default branch on every run
    so the PR always shows a clean, single-commit diff.
    """
    repo = github_client.get_repo(repo_name)
    default_branch = repo.default_branch
    base_sha = repo.get_branch(default_branch).commit.sha

    # Reset (or create) the report branch to the current default branch tip
    try:
        ref = repo.get_git_ref(f'heads/{REPORT_BRANCH}')
        ref.edit(base_sha, force=True)
        print(f"Reset branch '{REPORT_BRANCH}' to '{default_branch}'")
    except GithubException:
        repo.create_git_ref(f'refs/heads/{REPORT_BRANCH}', base_sha)
        print(f"Created branch '{REPORT_BRANCH}'")

    # Create or update the report file on the report branch
    try:
        existing = repo.get_contents(REPORT_FILE, ref=REPORT_BRANCH)
        repo.update_file(
            REPORT_FILE,
            f"Update link checker report [{datetime.date.today()}]",
            report_content,
            existing.sha,
            branch=REPORT_BRANCH,
        )
    except GithubException:
        repo.create_file(
            REPORT_FILE,
            f"Add link checker report [{datetime.date.today()}]",
            report_content,
            branch=REPORT_BRANCH,
        )

    # Build PR title and body
    pr_title = f"🔗 Link Checker Report — {datetime.date.today()}"
    if has_issues:
        pr_body = (
            "The automated link checker found issues in the repository. "
            "Please review `LINK_CHECKER_REPORT.md` and fix any broken, "
            "insecure, or blacklisted links.\n\n"
            "This PR is automatically updated on each checker run."
        )
    else:
        pr_body = (
            "✅ The automated link checker found no issues — all links are healthy.\n\n"
            "This PR is automatically updated on each checker run."
        )

    # Update existing open PR or create a new one
    owner = repo.owner.login
    existing_pr = next(iter(repo.get_pulls(
        head=f'{owner}:{REPORT_BRANCH}',
        base=default_branch,
        state='open',
    )), None)
    if existing_pr:
        pr = existing_pr
        pr.edit(title=pr_title, body=pr_body)
        print(f"Updated existing PR #{pr.number}: {pr.html_url}")
        return pr.number
    else:
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=REPORT_BRANCH,
            base=default_branch,
        )
        print(f"Created new PR #{pr.number}: {pr.html_url}")
        return pr.number


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Initialise GitHub client using the built-in GITHUB_TOKEN
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        print("Error: GITHUB_TOKEN environment variable is not set")
        exit(1)

    github_client = Github(auth=Auth.Token(github_token))

    repo_name = os.getenv('GITHUB_REPOSITORY')
    if not repo_name:
        print("Error: GITHUB_REPOSITORY environment variable is not set")
        exit(1)
    print(f"Running link checker for repository: {repo_name}")

    cache = load_cache()
    current_date = datetime.datetime.now().isoformat()

    # Discover all markdown files (skip .git directory)
    markdown_files = [
        os.path.join(root, fname)
        for root, _, files in os.walk('.')
        for fname in files
        if os.path.splitext(fname)[1].lower() in MARKDOWN_EXTENSIONS
        and not root.startswith('./.git')
    ]

    results = {'broken': [], 'insecure': [], 'spam': []}

    for file_path in markdown_files:
        print(f"Checking links in {file_path}...")
        for link in extract_links_from_markdown(file_path):

            # Skip recently reviewed links that are known-good
            if link in cache:
                entry = cache[link]
                last_checked = datetime.datetime.fromisoformat(
                    entry['last_checked']
                )
                days_since = (datetime.datetime.now() - last_checked).days
                if (days_since < REVIEW_PERIOD_DAYS
                        and entry.get('reviewed')
                        and not entry.get('issue_open')):
                    print(f"  Skipping recently reviewed: {link}")
                    continue

            is_broken, is_insecure, status_code = check_link(link)

            # Spam / blacklist check (skip for already-broken links)
            is_spam, threat = False, None
            if not is_broken:
                is_spam, threat = check_spam_blacklist(link, cache)

            # Update cache entry
            cache.setdefault(link, {
                'last_checked': current_date,
                'reviewed': False,
                'issue_open': False,
                'issue_number': None,
            })
            cache[link]['last_checked'] = current_date

            # Collect results
            if is_broken:
                results['broken'].append(
                    {'url': link, 'file': file_path, 'status': status_code}
                )
                print(f"  BROKEN: {link} ({status_code})")
            elif is_insecure:
                results['insecure'].append({'url': link, 'file': file_path})
                print(f"  INSECURE: {link}")

            if is_spam:
                results['spam'].append(
                    {'url': link, 'file': file_path, 'threat': threat}
                )
                print(f"  SPAM/BLACKLISTED: {link} ({threat})")

    total_issues = sum(len(v) for v in results.values())
    print(f"\nLink check complete. Found {total_issues} issue(s).")

    # Generate report and publish PR
    report_content = generate_report(results)
    pr_number = create_or_update_pr(
        github_client, repo_name, report_content, has_issues=total_issues > 0
    )
    print(f"Report PR: #{pr_number}")

    # Persist cache (workflow commits this file back to the default branch)
    save_cache(cache)


if __name__ == "__main__":
    main()

