import argparse
import base64
import json
import os
import urllib.request
import urllib.error
from datetime import datetime

# === ARG PARSING ===
parser = argparse.ArgumentParser(description="Migrate Azure DevOps work items to GitHub Issues.")
parser.add_argument("--ado-pat", help="Azure DevOps PAT (or set ADO_PAT env var)")
parser.add_argument("--ado-org", required=True, help="Azure DevOps organization")
parser.add_argument("--ado-project", required=True, help="Azure DevOps project")
parser.add_argument("--github-repo", required=True, help="GitHub repo (e.g., user/repo)")
parser.add_argument("--github-token", help="GitHub token (or set GITHUB_TOKEN env var)")
parser.add_argument("--limit", type=int, default=50, help="Limit number of work items to migrate")
args = parser.parse_args()

# === AUTH SETUP ===
ado_pat = args.ado_pat or os.getenv("ADO_PAT")
if not ado_pat:
    raise ValueError("Azure DevOps PAT must be provided via --ado-pat or ADO_PAT env var.")
github_token = args.github_token or os.getenv("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GitHub token must be provided via --github-token or GITHUB_TOKEN env var.")

# === LOGGING ===
log_file = open("migration_errors.log", "w")
def log_error(msg):
    print("❌", msg)
    log_file.write(msg + "\n")

def make_request(url, method="GET", headers=None, data=None):
    """Generic HTTP request function"""
    req = urllib.request.Request(url, method=method)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    if data:
        req.data = json.dumps(data).encode("utf-8")
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        log_error(f"HTTP Error {e.code} - {e.reason}\nURL: {url}\n{error_body}")
        raise
    except Exception as e:
        log_error(f"Request failed: {str(e)}\nURL: {url}")
        raise

# === FETCH WORK ITEM IDS ===
print("📦 Fetching work items...")
wiql_url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/wiql?api-version=7.0"
headers_ado = {
    "Authorization": f"Basic {base64.b64encode(f':{ado_pat}'.encode()).decode()}",
    "Content-Type": "application/json"
}
query = {
    "query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project ORDER BY [System.CreatedDate] ASC"
}

try:
    wiql_data = make_request(wiql_url, "POST", headers_ado, query)
    ids = [item["id"] for item in wiql_data["workItems"]][:args.limit]
except Exception:
    log_file.close()
    exit(1)

# === FETCH EXISTING GITHUB ISSUES ===
print("🔍 Fetching GitHub issues to avoid duplicates...")
existing_titles = set()
page = 1
headers_gh = {
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github+json"
}

while True:
    url = f"https://api.github.com/repos/{args.github_repo}/issues?state=all&per_page=100&page={page}"
    try:
        issues_data = make_request(url, "GET", headers_gh)
        if not issues_data:
            break
        existing_titles.update(issue["title"] for issue in issues_data)
        page += 1
    except Exception:
        break  # Stop on error or empty page

# === MIGRATION LOOP ===
for wi_id in ids:
    try:
        # Get work item details
        url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workitems/{wi_id}?$expand=all&api-version=7.0-preview"
        wi = make_request(url, "GET", headers_ado)
        
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
        create_url = f"https://api.github.com/repos/{args.github_repo}/issues"
        gh_issue = make_request(create_url, "POST", headers_gh, payload)
        issue_number = gh_issue["number"]
        print(f"✅ Created GitHub issue #{issue_number}: {title}")

        # Fetch and migrate comments
        comments_url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workItems/{wi_id}/comments?api-version=7.0-preview"
        try:
            comments_data = make_request(comments_url, "GET", headers_ado)
            for comment in comments_data.get("comments", []):
                author = comment["createdBy"]["displayName"]
                text = comment["text"]
                date = comment["createdDate"].split("T")[0]
                comment_body = f"_Comment by **{author}** on {date}_:\n\n{text}"
                comment_url = f"https://api.github.com/repos/{args.github_repo}/issues/{issue_number}/comments"
                make_request(comment_url, "POST", headers_gh, {"body": comment_body})
        except Exception as e:
            log_error(f"Failed to migrate comments for work item {wi_id}: {str(e)}")
            
    except Exception as e:
        log_error(f"Work item {wi_id} failed: {str(e)}")

log_file.close()
print("\n🎉 Migration complete.")