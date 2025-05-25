import argparse
import base64
import json
import os
from datetime import datetime

import requests

# === ARG PARSING ===
parser = argparse.ArgumentParser(description="Migrate Azure DevOps work items to GitHub Issues.")
parser.add_argument("--ado-pat", help="Azure DevOps PAT (or set ADO_PAT env var)")
parser.add_argument("--ado-org", required=True, help="Azure DevOps organization")
parser.add_argument("--ado-project", required=True, help="Azure DevOps project")
parser.add_argument("--github-repo", required=True, help="GitHub repo (e.g., user/repo)")
parser.add_argument("--github-token", help="GitHub token (or set GITHUB_TOKEN env var)")
parser.add_argument("--limit", type=int, default=50, help="Limit number of work items to migrate")
args = parser.parse_args()

# === AUTH HEADERS ===
ado_pat = args.ado_pat or os.getenv("ADO_PAT")
if not ado_pat:
    raise ValueError("Azure DevOps PAT must be provided via --ado-pat or ADO_PAT env var.")
github_token = args.github_token or os.getenv("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GitHub token must be provided via --github-token or GITHUB_TOKEN env var.")

headers_ado = {
    "Authorization": f"Basic {base64.b64encode(f':{ado_pat}'.encode()).decode()}",
    "Content-Type": "application/json"
}
headers_gh = {
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github+json"
}

# === LOGGING ===
log_file = open("migration_errors.log", "w")
def log_error(msg):
    print("❌", msg)
    log_file.write(msg + "\n")

# === FETCH WORK ITEM IDS ===
print("📦 Fetching work items...")
wiql_url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/wiql?api-version=7.0"
query = {
    "query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project ORDER BY [System.CreatedDate] ASC"
}
resp = requests.post(wiql_url, headers=headers_ado, json=query)
resp.raise_for_status()

ids = [item["id"] for item in resp.json()["workItems"]][:args.limit]

# === FETCH EXISTING GITHUB ISSUES ===
print("🔍 Fetching GitHub issues to avoid duplicates...")
existing_titles = set()
page = 1
while True:
    url = f"https://api.github.com/repos/{args.github_repo}/issues?state=all&per_page=100&page={page}"
    resp = requests.get(url, headers=headers_gh)
    if resp.status_code != 200 or not resp.json():
        break
    existing_titles.update(issue["title"] for issue in resp.json())
    page += 1

# === MIGRATION LOOP ===
for wi_id in ids:
    try:
        # Get work item details
        url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workitems/{wi_id}?$expand=all&api-version=7.0"
        wi = requests.get(url, headers=headers_ado).json()
        title = wi["fields"]["System.Title"]
        if title in existing_titles:
            print(f"⏩ Skipping existing issue: {title}")
            continue

        desc = wi["fields"].get("System.Description", "")
        created_by = wi["fields"]["System.CreatedBy"]["displayName"]
        created_date = wi["fields"]["System.CreatedDate"].split("T")[0]
        work_item_url = wi["_links"]["html"]["href"]
        body = f"""**Created by:** {created_by}  
**Created on:** {created_date}  
**Original ADO Link:** [{work_item_url}]({work_item_url})

---

{desc}
"""

        # Create GitHub issue
        payload = {
            "title": title,
            "body": body,
            "labels": [wi["fields"].get("System.WorkItemType", "work-item")]
        }
        gh_issue = requests.post(f"https://api.github.com/repos/{args.github_repo}/issues",
                                 headers=headers_gh, json=payload)
        gh_issue.raise_for_status()
        issue_number = gh_issue.json()["number"]
        print(f"✅ Created GitHub issue #{issue_number}: {title}")

        # Fetch and migrate comments
        comments_url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workItems/{wi_id}/comments?api-version=7.0"
        comment_resp = requests.get(comments_url, headers=headers_ado)
        comment_resp.raise_for_status()
        for comment in comment_resp.json().get("comments", []):
            author = comment["createdBy"]["displayName"]
            text = comment["text"]
            date = comment["createdDate"].split("T")[0]
            comment_body = f"_Comment by **{author}** on {date}_:\n\n{text}"
            requests.post(f"https://api.github.com/repos/{args.github_repo}/issues/{issue_number}/comments",
                          headers=headers_gh, json={"body": comment_body})
    except Exception as e:
        log_error(f"Work item {wi_id} failed: {str(e)}")

log_file.close()
print("\n🎉 Migration complete.")
