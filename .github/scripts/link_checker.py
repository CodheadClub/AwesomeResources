#!/usr/bin/env python3
"""
Link checker for markdown files in the AwesomeResources repository.
This script checks for broken links (404, 500, etc.) and insecure links (http instead of https).
It creates GitHub issues for problematic links and avoids duplicating issues for links that were already reviewed.
"""

import os
import re
import json
import datetime
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from github import Github
from urllib.parse import urlparse

# Constants
REPO_NAME = os.getenv('GITHUB_REPOSITORY', 'owner/AwesomeResources')
CACHE_FILE = '.link_check_cache.json'
MARKDOWN_EXTENSIONS = ['.md', '.markdown']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
TIMEOUT = 30  # timeout in seconds for HTTP requests
RETRY_COUNT = 2  # number of retries for each link
REVIEW_PERIOD_DAYS = 60  # don't re-check links reviewed within this period

# Error codes to check for
ERROR_CODES = [404, 500, 502, 503, 504]


def load_cache():
    """Load the cache of previously checked links and their issues."""
    try:
        with open(CACHE_FILE, 'r') as file:
            data = json.load(file)
            print(f"Successfully loaded cache with {len(data)} entries")
            return data
    except FileNotFoundError:
        print(f"Cache file '{CACHE_FILE}' not found, creating new cache")
        return {}
    except json.JSONDecodeError:
        print(f"Error parsing cache file, creating new cache")
        return {}


def save_cache(cache):
    """Save the cache of checked links and their issues."""
    try:
        with open(CACHE_FILE, 'w') as file:
            json.dump(cache, file)
        print(f"Successfully saved cache with {len(cache)} entries")
    except Exception as e:
        print(f"Error saving cache file: {e}")


def extract_links_from_markdown(file_path):
    """Extract links from a markdown file."""
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Find all markdown links
    markdown_links = re.findall(r'\[.+?\]\((https?:\/\/[^\s\)]+)\)', content)
    
    # Find HTML links
    html_links = []
    soup = BeautifulSoup(content, 'html.parser')
    for a in soup.find_all('a', href=True):
        if a['href'].startswith(('http://', 'https://')):
            html_links.append(a['href'])
    
    # Combine all links and remove duplicates
    links = list(set(markdown_links + html_links))
    return links


def check_link(url):
    """Check a link for issues. Returns a tuple (is_broken, is_insecure, status_code)."""
    parsed_url = urlparse(url)
    is_insecure = parsed_url.scheme == 'http'
    
    # Skip checking certain special domains that shouldn't be validated
    # as they may trigger false positives or security alerts
    skip_domains = ['localhost', '127.0.0.1', 'example.com', 'example.org']
    if parsed_url.netloc in skip_domains:
        return (False, is_insecure, 200)
    
    # Try to fetch the URL with multiple retries
    status_code = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            # Try HEAD first (faster, less bandwidth)
            try:
                response = requests.head(
                    url, 
                    headers=HEADERS, 
                    timeout=TIMEOUT, 
                    allow_redirects=True
                )
                
                # If HEAD works, we're good
                if response.status_code < 400:
                    return (False, is_insecure, response.status_code)
                
            except requests.exceptions.RequestException:
                # Some servers don't support HEAD, that's fine
                pass
                
            # Fallback to GET with stream=True to avoid downloading large files
            response = requests.get(
                url, 
                headers=HEADERS, 
                timeout=TIMEOUT, 
                allow_redirects=True, 
                stream=True
            )
            
            # Just read a small part to verify connection works
            for chunk in response.iter_content(chunk_size=1024):
                break
                
            response.close()  # Close the connection
                
            is_broken = response.status_code in ERROR_CODES
            return (is_broken, is_insecure, response.status_code)
            
        except requests.exceptions.Timeout:
            print(f"Timeout for {url}, attempt {attempt+1}/{RETRY_COUNT+1}")
            status_code = "Timeout"
            # Try again if we have retries left
            
        except requests.exceptions.SSLError:
            print(f"SSL Error for {url}")
            return (True, is_insecure, "SSL Error")
            
        except requests.exceptions.ConnectionError:
            print(f"Connection Error for {url}")
            return (True, is_insecure, "Connection Error")
            
        except Exception as e:
            print(f"Error checking {url}: {str(e)}")
            status_code = str(e)[:50]  # Truncate long error messages
            # Try again if we have retries left
    
    # If we get here, all retries failed
    return (True, is_insecure, status_code)


def create_github_issue(github_client, repo_name, link, issue_type, file_path, status_code=None):
    """Create a GitHub issue for a problematic link."""
    repo = github_client.get_repo(repo_name)
    
    if issue_type == "broken":
        status_info = f" (Status: {status_code})" if status_code else " (Connection failed)"
        title = f"Broken link found: {link[:50]}..."
        body = f"## Broken Link Found\n\n"
        body += f"- **URL**: {link}\n"
        body += f"- **Status**: {status_code if status_code else 'Connection error'}\n"
        body += f"- **File**: {file_path}\n\n"
        body += "Please review this link and either fix it, remove it, or mark it as intentionally kept."
    else:
        title = f"Insecure link found: {link[:50]}..."
        body = f"## Insecure Link Found\n\n"
        body += f"- **URL**: {link}\n"
        body += f"- **File**: {file_path}\n\n"
        body += "This link uses HTTP instead of HTTPS. Please consider updating it to use HTTPS if available."
    
    body += "\n\n---\n*This issue was automatically created by the Link Checker GitHub Action.*"
    
    issue = repo.create_issue(title=title, body=body)
    return issue.number


def main():    # Initialize GitHub client
    github_token = os.getenv('GITHUB_TOKEN')  # The workflow passes CHECKER_TOKEN as GITHUB_TOKEN
    if not github_token:
        print("Error: GITHUB_TOKEN environment variable is not set (should be passed from CHECKER_TOKEN)")
        exit(1)  # Exit with error code
    
    github_client = Github(github_token)
    
    # Get repository name from environment or use default
    repo_name = os.getenv('GITHUB_REPOSITORY', REPO_NAME)
    print(f"Running link checker for repository: {repo_name}")
    
    # Load the cache of previously checked links
    cache = load_cache()
    print(f"Loaded cache with {len(cache)} previously checked links")
    
    # Get the current date for comparing with the review period
    current_date = datetime.datetime.now().isoformat()
    
    # Get all markdown files
    markdown_files = []
    for root, _, files in os.walk('.'):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in MARKDOWN_EXTENSIONS and not root.startswith('./.git'):
                markdown_files.append(os.path.join(root, file))
    
    # Check links in each file
    problematic_links = 0
    
    for file_path in markdown_files:
        print(f"Checking links in {file_path}...")
        links = extract_links_from_markdown(file_path)
        
        for link in links:
            # Skip if link was recently reviewed (within REVIEW_PERIOD_DAYS)
            if link in cache:
                last_checked = datetime.datetime.fromisoformat(cache[link]['last_checked'])
                days_since_check = (datetime.datetime.now() - last_checked).days
                
                if (days_since_check < REVIEW_PERIOD_DAYS and 
                    cache[link]['reviewed'] and 
                    not cache[link]['issue_open']):
                    print(f"Skipping recently reviewed link: {link}")
                    continue
            
            # Check the link
            is_broken, is_insecure, status_code = check_link(link)
            
            # Update cache entry
            if link not in cache:
                cache[link] = {
                    'last_checked': current_date,
                    'reviewed': False,
                    'issue_open': False,
                    'issue_number': None
                }
            else:
                cache[link]['last_checked'] = current_date
              # Handle broken link
            if is_broken:
                if not cache[link]['issue_open']:
                    issue_number = create_github_issue(
                        github_client, repo_name, link, "broken", file_path, status_code
                    )
                    cache[link]['issue_number'] = issue_number
                    cache[link]['issue_open'] = True
                    cache[link]['reviewed'] = False
                    print(f"Created issue #{issue_number} for broken link: {link}")
                    problematic_links += 1
                else:
                    print(f"Issue already open for broken link: {link}")
              # Handle insecure link (only if not broken)
            elif is_insecure:
                if not cache[link]['issue_open']:
                    issue_number = create_github_issue(
                        github_client, repo_name, link, "insecure", file_path
                    )
                    cache[link]['issue_number'] = issue_number
                    cache[link]['issue_open'] = True
                    cache[link]['reviewed'] = False
                    print(f"Created issue #{issue_number} for insecure link: {link}")
                    problematic_links += 1
                else:
                    print(f"Issue already open for insecure link: {link}")
            
            # Mark as checked if no issues found
            else:
                if cache[link]['issue_open']:
                    # Check if the issue was closed
                    try:
                        repo = github_client.get_repo(repo_name)
                        issue = repo.get_issue(cache[link]['issue_number'])
                        if issue.state == 'closed':
                            cache[link]['issue_open'] = False
                            cache[link]['reviewed'] = True
                            print(f"Issue #{issue.number} for {link} was closed. Link marked as reviewed.")
                    except Exception as e:
                        print(f"Error checking issue status: {e}")
    
    # Save the updated cache
    save_cache(cache)
    
    print(f"Link check completed. Found {problematic_links} problematic links.")


if __name__ == "__main__":
    main()
