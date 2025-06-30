import argparse
import base64
import json
import os
import subprocess
from datetime import datetime
import urllib.request
import urllib.error

# === ARGUMENT PARSING ===
parser = argparse.ArgumentParser(description="Migrate PRs from Azure DevOps to GitHub.")
parser.add_argument("--ado-pat", help="Azure DevOps PAT (or set ADO_PAT env var)")
parser.add_argument("--ado-org", required=True, help="Azure DevOps organization name")
parser.add_argument("--ado-project", required=True, help="Azure DevOps project name")
parser.add_argument("--ado-repo", required=True, help="Azure DevOps repo ID or name")
parser.add_argument("--github-repo", required=True, help="GitHub repo (e.g., user/repo)")

args = parser.parse_args()

# === CREDENTIALS AND HEADERS ===
ado_pat = args.ado_pat or os.environ.get("ADO_PAT")
if not ado_pat:
    raise ValueError("Azure DevOps PAT must be provided via --ado-pat or ADO_PAT env var.")

auth_header = f"Basic {base64.b64encode(f':{ado_pat}'.encode()).decode()}"

# === VARIABLES ===
ado_org = args.ado_org
ado_project = args.ado_project
ado_repo_id = args.ado_repo
github_repo = args.github_repo

# === LOGGING ===
log_file = open("migration_errors.log", "w")

def log_error(message):
    print("❌", message)
    log_file.write(message + "\n")

def fetch_existing_github_prs():
    print("🔍 Fetching existing GitHub PRs to avoid duplicates...")
    result = subprocess.run(["gh", "pr", "list", "--repo", github_repo, "--json", "title,headRefName,baseRefName"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log_error("Failed to fetch GitHub PRs.")
        return []

    try:
        return json.loads(result.stdout)
    except Exception as e:
        log_error(f"Failed to parse PR list: {e}")
        return []

existing_prs = fetch_existing_github_prs()

def pr_already_exists(title, head, base):
    return any(
        pr["title"] == title and pr["headRefName"] == head and pr["baseRefName"] == base
        for pr in existing_prs
    )

def make_ado_request(url):
    """Make authenticated request to Azure DevOps API"""
    req = urllib.request.Request(url)
    req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if hasattr(e, 'read') else ''
        log_error(f"ADO API Error: {e.code} - {e.reason}\n{error_body}")
        raise

# === FETCH PULL REQUESTS FROM ADO ===
ado_pr_api = f"https://dev.azure.com/{ado_org}/{ado_project}/_apis/git/repositories/{ado_repo_id}/pullrequests?api-version=7.0"
try:
    pr_data = make_ado_request(ado_pr_api)
    prs = pr_data["value"]
except Exception as e:
    log_error(f"Failed to fetch PRs: {str(e)}")
    log_file.close()
    exit(1)

# === MAIN MIGRATION LOOP ===
for pr in prs:
    title = pr["title"]
    raw_description = pr["description"] or ""
    source_branch = pr["sourceRefName"].replace("refs/heads/", "")
    target_branch = pr["targetRefName"].replace("refs/heads/", "")
    created_by = pr["createdBy"]["displayName"]
    created_at_str = pr["creationDate"].split(".")[0] + "Z"
    created_on = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d")

    if pr_already_exists(title, source_branch, target_branch):
        print(f"⏩ Skipping existing PR: {title}")
        continue

    attribution = f"Originally created by *{created_by}* on {created_on} in Azure DevOps\n\n"
    body = attribution + raw_description

    print(f"\n📦 Creating PR: {title}")
    try:
        result = subprocess.run([
            "gh", "pr", "create",
            "--repo", github_repo,
            "--title", title,
            "--body", body,
            "--head", source_branch,
            "--base", target_branch
        ], capture_output=True, text=True, check=True)

        pr_url = result.stdout.strip().splitlines()[-1]  # Get last line = PR URL

    except subprocess.CalledProcessError as e:
        log_error(f"Failed to create PR '{title}': {e.stderr or e.stdout}")
        continue

    # === FETCH AND MIGRATE COMMENTS ===
    pr_id = pr["pullRequestId"]
    comments_url = f"https://dev.azure.com/{ado_org}/{ado_project}/_apis/git/repositories/{ado_repo_id}/pullRequests/{pr_id}/threads?api-version=7.0"
    try:
        thread_data = make_ado_request(comments_url)
        threads = thread_data["value"]
    except Exception as e:
        log_error(f"Failed to fetch comments for PR {title}: {str(e)}")
        continue

    for thread in threads:
        for comment in thread.get("comments", []):
            author = comment["author"]["displayName"]
            content = comment["content"]
            date = datetime.strptime(comment["publishedDate"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d")

            comment_text = f"Comment by *{author}* on {date}:\n\n{content}"
            try:
                subprocess.run([
                    "gh", "pr", "comment",
                    pr_url,
                    "--repo", github_repo,
                    "--body", comment_text
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                log_error(f"Failed to post comment from {author} on PR '{title}': {e.stderr or e.stdout}")

log_file.close()
print("\n✅ Migration complete. Check 'migration_errors.log' for any issues.")