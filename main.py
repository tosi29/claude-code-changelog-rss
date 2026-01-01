import os
import re
import requests
import sys
from datetime import datetime
from feedgen.feed import FeedGenerator

# Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_OWNER = "anthropics"
REPO_NAME = "claude-code"
FILE_PATH = "CHANGELOG.md"
BRANCH = "main"

def fetch_changelog_blame():
    """Fetches the blame information for CHANGELOG.md using GitHub GraphQL API."""
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        sys.exit(1)

    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    
    query = """
    query($owner: String!, $name: String!, $expression: String!) {
      repository(owner: $owner, name: $name) {
        object(expression: $expression) {
          ... on Blob {
            text
          }
        }
      }
    }
    """
    
    # First, fetch the raw text content to parse versions locally
    # We will use the REST API logic or just assume we have the text for now.
    # Actually, the GraphQL query above only gets text. We need Blame.
    # Blame query is more complex and might be paginated.
    # Let's verify if we can get blame for the whole file.
    
    blame_query = """
    query($owner: String!, $name: String!, $branch: String!, $path: String!) {
      repository(owner: $owner, name: $name) {
        ref(qualifiedName: $branch) {
          target {
            ... on Commit {
              blame(path: $path) {
                ranges {
                  startingLine
                  endingLine
                  commit {
                    committedDate
                    oid
                  }
                }
              }
            }
          }
        }
        object(expression: "main:CHANGELOG.md") {
          ... on Blob {
            text
          }
        }
      }
    }
    """
    
    variables = {
        "owner": REPO_OWNER,
        "name": REPO_NAME,
        "branch": BRANCH,
        "path": FILE_PATH
    }

    response = requests.post(url, json={"query": blame_query, "variables": variables}, headers=headers)
    
    if response.status_code != 200:
        print(f"Error fetching data: {response.status_code}")
        print(response.text)
        sys.exit(1)

    data = response.json()
    if "errors" in data:
        print("GraphQL Errors:", data["errors"])
        sys.exit(1)

    return data["data"]["repository"]

def parse_changelog(repo_data):
    """Parses the changelog text and associates dates from blame ranges."""
    
    # Get raw text
    text = repo_data["object"]["text"]
    lines = text.splitlines()
    
    # Get blame ranges
    # blame ranges are 1-based line numbers.
    blame_ranges = repo_data["ref"]["target"]["blame"]["ranges"]
    
    # Map line number (0-based) to data
    line_data_map = {}
    for r in blame_ranges:
        # startingLine is 1-based
        start = r["startingLine"] - 1 
        end = r["endingLine"] # exclusive in python slice? range is inclusive in GraphQL
        date_str = r["commit"]["committedDate"]
        commit_oid = r["commit"]["oid"]
        
        for i in range(start, end):
            line_data_map[i] = {"date": date_str, "oid": commit_oid}

    versions = []
    
    # Regex to find version headers like "## 2.0.74" or "# Changelog" (ignore top level?)
    # The file starts with "# Changelog" usually. Versions are "## X.Y.Z"
    
    current_version = None
    current_desc = []
    current_date = None
    current_oid = None
    
    for i, line in enumerate(lines):
        version_match = re.match(r"^##\s+(\d+\.\d+\.\d+)", line)
        
        if version_match:
            # Save previous version if exists
            if current_version:
                versions.append({
                    "version": current_version,
                    "date": current_date,
                    "oid": current_oid,
                    "description": "\n".join(current_desc).strip()
                })
            
            # Start new version
            current_version = version_match.group(1)
            current_desc = []
            
            # Use the commit data of the header line
            line_info = line_data_map.get(i)
            if line_info:
                current_date = line_info["date"]
                current_oid = line_info["oid"]
            else:
                current_date = None
                current_oid = None
            
        elif current_version:
            current_desc.append(line)
            
    # Add the last one
    if current_version:
        versions.append({
            "version": current_version,
            "date": current_date,
            "oid": current_oid,
            "description": "\n".join(current_desc).strip()
        })
        
    return versions

def generate_rss(versions):
    fg = FeedGenerator()
    fg.title('Claude Code Changelog (Unofficial)')
    fg.link(href=f'https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{BRANCH}/{FILE_PATH}', rel='alternate')
    fg.description('Unofficial RSS feed for Claude Code changelog, parsed from CHANGELOG.md')
    fg.language('en')
    
    # Add items
    for v in versions:
        fe = fg.add_entry()
        fe.title(f"v{v['version']}")
        
        # Link to the specific commit blob
        if v['oid']:
            link_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{v['oid']}/{FILE_PATH}"
        else:
            # Fallback if no OID found
            link_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/v{v['version']}"
            
        fe.link(href=link_url)
        fe.description(v['description'])
        
        # Set GUID to be unique and a permalink
        fe.guid(link_url, permalink=True)
        
        if v['date']:
            # Parse ISO date string to datetime with timezone
            dt = datetime.fromisoformat(v['date'].replace("Z", "+00:00"))
            fe.pubDate(dt)
        
    rss_feed = fg.rss_str(pretty=True)
    
    with open('feed.xml', 'wb') as f:
        f.write(rss_feed)
    print("Generated feed.xml")

def main():
    print("Fetching changelog and blame data...")
    data = fetch_changelog_blame()
    
    print("Parsing changelog...")
    versions = parse_changelog(data)
    
    print(f"Found {len(versions)} versions.")
    
    # Sort by date
    versions.sort(key=lambda x: x['date'] or "")
    
    print("Generating RSS feed...")
    generate_rss(versions)
    print("Done!")

if __name__ == "__main__":
    main()
