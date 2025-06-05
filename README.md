# Migration of Repositories from ADO to GitHub Enterprises

## Code Migration

- CREATE A NEW REPO ON GITHUB
- Set up a bare mirror clone of ado repository
  eg.

```bash
git clone --mirror git@ssh.dev.azure.com:v3/ivanjmadathil/django-admin-jwt-test/django-admin-jwt-test
```

- cd into the mirror
- Push the mirror to the new GitHub repo
  eg.

```bash
git push --mirror git@github.com:<your-org>/<your-repo>.git
```

### A python script for the step above

[The Script](./01_code_migration.py)

```bash
##python.exe .\01_code_migration.py <AZURE_REPO> <GITHUB_REPO>
import argparse
import os
import re
import subprocess

def run(cmd, ignore_error=False):
    print(f"Running: {cmd}")
    try:
        subprocess.check_call(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            raise
        print(f"Warning: Command failed but continuing. Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Migrate Azure DevOps repo to GitHub.")
    parser.add_argument("azure_repo_url", help="Azure DevOps repository URL")
    parser.add_argument("github_repo_url", help="GitHub repository URL")
    args = parser.parse_args()

    repo_name = args.azure_repo_url.rstrip('/').split('/')[-1] + ".git"

    # Clone the Azure DevOps repo as a bare mirror
    run(f'git clone --mirror "{args.azure_repo_url}"')

    # Change directory to the cloned repo
    os.chdir(repo_name)

    # Push the mirror to the new GitHub repo, ignore errors
    run(f'git push --mirror "{args.github_repo_url}"', ignore_error=True)

    # Set the default branch to 'main' on GitHub using GitHub CLI
    # Extract owner/repo from the GitHub URL
    m = re.search(r'github\.com[:/](.+?)/(.+?)\.git', args.github_repo_url)
    if m:
        owner_repo = f"{m.group(1)}/{m.group(2)}"
        run(f'gh repo edit {owner_repo} --default-branch main', ignore_error=True)
    else:
        print("Could not parse GitHub repo owner/name from URL.")

if __name__ == "__main__":
    main()
```

## Pull Request Migration

### **_NOTE_** :

- It is best practise that Pull Requests are Merged before the repositories are migrated
- But in the scenario where it is required that the Pull Requests are migrated, the below provided code can be made use of.

### A python script for the PR migration

[The Script](./02_code_migration)

```bash
# python.exe .\prmigrate.py --ado-pat <ADO_PAT_HERE> --ado-org <ADO_ORG_HERE> --ado-project <ADO_PROJECT_HERE> --ado-repo <ADO_REPO_HERE> --github-repo <Github_User/Github_Repo>

import argparse
import base64
import json
import os
import subprocess
from datetime import datetime

import requests

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

headers = {
    "Authorization": f"Basic {base64.b64encode(f':{ado_pat}'.encode()).decode()}"
}

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

# === FETCH PULL REQUESTS FROM ADO ===
ado_pr_api = f"https://dev.azure.com/{ado_org}/{ado_project}/_apis/git/repositories/{ado_repo_id}/pullrequests?api-version=7.0"
pr_response = requests.get(ado_pr_api, headers=headers)
if pr_response.status_code != 200:
    log_error(f"Failed to fetch PRs: {pr_response.status_code} - {pr_response.text}")
    exit(1)

prs = pr_response.json()["value"]

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

    attribution = f"_Originally created by **{created_by}** on {created_on} in Azure DevOps_\n\n"
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
        log_error(f"Failed to create PR '{title}': {e}")
        continue

    # === FETCH AND MIGRATE COMMENTS ===
    pr_id = pr["pullRequestId"]
    comments_url = f"https://dev.azure.com/{ado_org}/{ado_project}/_apis/git/repositories/{ado_repo_id}/pullRequests/{pr_id}/threads?api-version=7.0"
    thread_response = requests.get(comments_url, headers=headers)

    if thread_response.status_code != 200:
        log_error(f"Failed to fetch comments for PR {title}: {thread_response.text}")
        continue

    threads = thread_response.json()["value"]
    for thread in threads:
        for comment in thread.get("comments", []):
            author = comment["author"]["displayName"]
            content = comment["content"]
            date = datetime.strptime(comment["publishedDate"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d")

            comment_text = f"_Comment by **{author}** on {date}_:\n\n{content}"
            try:
                subprocess.run([
                    "gh", "pr", "comment",
                    pr_url,
                    "--repo", github_repo,
                    "--body", comment_text
                ], check=True)
            except subprocess.CalledProcessError as e:
                log_error(f"Failed to post comment from {author} on PR '{title}': {e}")

log_file.close()
print("\n✅ Migration complete. Check 'migration_errors.log' for any issues.")
```

## Work Item ( Issue) Migration

[The script](./03_migrate_workitems.py)

```bash
#python.exe .\migrate_workitems.py --ado-pat <ADO_PAT_HERE> --ado-org <ADO_ORG_HERE> --ado-project <ADO_PROJECT_HERE> --github-repo <Github_USER/Github_REPO> --github-token <GH_PAT_HERE>
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
        url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workitems/{wi_id}?$expand=all&api-version=7.0-preview"
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
        comments_url = f"https://dev.azure.com/{args.ado_org}/{args.ado_project}/_apis/wit/workItems/{wi_id}/comments?api-version=7.0-preview"
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
```

## Branch Protection, Restriction Rules

- These have to be done manually and based on the workflow of the repository
- Enable branch protection to effectively prevent force pushing
- Enable on any branch meant for ongoing collabration
- By default, all collaborators who have been granted write permissions to the repository are able to push to the protected branch. By explicitly specifying permitted collaborators, you will narrow down the list of existing collaborators who can push to the branch.
- Create a "Maintainers" teams.
- Enable branch protection on main branch by turning on "Require status checks to pass before merging" to avoid broken code.
- Require at least one pull request review by checking the "Require pull request reviews before merging"

## Secrets and Pipelines

- For the migration of secrets and pipelines from azure devops to github
- Firstly, Secrets cannot be migrated and will have to be set in the repository settings in github.
- Secondly, for the conversion of Azure pipelines yaml to github compliant yaml [The following website could be used](https://pipelinestoactions.azurewebsites.net/). Or its NuGet package could be utilized.
- NOTE: For the pipeline conversion the tool only promises a 90% conversion accuracy at best. So a pipeline review would be required.

## Wikis

- Has to be migrated manually
