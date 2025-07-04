# Migration of Repositories from ADO to GitHub Enterprises

## Below has been attached three different ways by which repositories can be migrated from Azure DevOps to Github:

### Prerequisites :

- Github PAT - Organization Page -> Settings -> Personal Access Tokens -> Token Classic with necessary permissions.
- Azure DevOps Personal Access Token -> Your Account Logo(in upper right) -> Your Organizations -> Settings -> Developer Settings -> PAT Creation.

### For the sake of ease of use the Personal Access Tokens can be stored as environment variables in the system

# **Method I: Making Use of Python Scripts**

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

[The Script(using requests library)](./01_code_migration.py)

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

## Work Item (Issue) Migration

[The script](./03_migrate_workitems.py)
[The Script(without using requests library)](./without_using_requests_lib/03_migrate_workitems.py)

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

## Pull Request Migration

### **_NOTE_** :

- It is best practise that Pull Requests are Merged before the repositories are migrated
- But in the scenario where it is required that the Pull Requests are migrated, the below provided script can be made use of.

### A python script for the PR migration

[The Script](./02_code_migration)
[The Script(without using requests library)](./without_using_requests_lib/02_prmigrate.py)

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

# **Method II: Making Use of gh-cli**

## II.0) Install gh-cli

[Link to the installation Guide](https://cli.github.com/). Install the .msi file. Run it and proceed with the installation and signin

## II.1) Install ado2gh extension

```bash
gh extension install github/gh-ado2gh
```

## II.2) Update and Upgrade the extension

```bash
gh extension upgrade github/gh-ado2gh
```

## II.3) Set the environment variables

If you are using Powershell (**Recommended**)

```bash
$env:GH_PAT=GH_PAT
$env:ADO_PAT=ADO_PAT
//this is assuming that the PATs have been saved as environment variables
```

## II.4) Generate a migration script

```bash
gh ado2gh generate-script --ado-org <SOURCE_TO_BE_ENTERED> --github-org <DESTINATION_TO_BE_ENTERED> --output <FILENAME_TO_BE_ENTERED>
```

| Placeholder | Value                            |
| ----------- | -------------------------------- |
| DESTINATION | Name of Destination Organization |
| FILENAME    | Name of the Script               |
| SOURCE      | Name of Source Organization      |

## II.5) Reviewing the script

- If there are any repositories you don't want to migrate, delete or comment out the corresponding lines.
- If you want any repositories to have a different name in the destination organization, update the value for the corresponding --target-repo flag.
- If you want to change the visibility of new repository, update the value for the corresponding --target-repo-visibility flag. By default, the script sets the same visibility as the source repository.

## II.6) Migrate the repos

```bash
.\FILENAME
```

## If you wish to migrate a single repo

```bash
gh ado2gh migrate-repo --ado-org SOURCE --ado-team-project TEAM-PROJECT --ado-repo CURRENT-NAME --github-org DESTINATION --github-repo NEW-NAME
```

## Issue faced issues - The ado2gh extension does not facilitate the migration of issues of a repository. In the case that migration of issues is essential the attached script could be made use of [The Script](./03_migrate_workitems.py)

# **Method III: Making Use of the GUI**

- Go to create a repository
- Click on Import a repository on the top of the page
- Provide the url of the source repository
- Provide the username or registered email id and the ADO PAT
- Select Your Organization as the owner and give it the name
- Select your repository to be private
- Begin Import

### Issue with this method is pull request and issues are not migrated . In the case where it is required that these are included in the repo, the following scripts can be used. [Pull Request Migration](./02_prmigrate.py) and [Issue Migration](./03_migrate_workitems.py)

![The GUI](./images/image.png)

## Miscallaneous Points:

### I) In the scenario where commit history can be ignored and only branches are required to be migrated the steps above can be altered in such a way

```bash
#create a new github repo

#create a bare clone of the ado repo
git clone --bare <ADO_REPO_URL>

#for each branch that has to be migrated
git checkout <branch-name>

#then
git checkout --orphan <new-branch-name>
git rm -rf .

git push origin <new-branch-name>
 ##and repeat this for each branch
```

---

### II) The Azure Valut to GitHub repository secrets must be done manually and with discretion

---

### III) Now if the development is carried out in GitHub and the required changes have to be synced with azure devops, in that case we can make use of a GitHub actions pipeline that mirrors its current state to the ADO repository.

#### github actions.yml

```bash
# .github/workflows/sync-to-ado.yml
name: Mirror to Azure DevOps

on:
  push:
    branches: [main, develop, feature/**]
    tags:
      - "**"
  delete:
    branches: [main, develop, feature/**]
    tags:
      - "**"
  create:
    branches: ['**']  # Catch branch creations
  pull_request:
    types: [opened, synchronize, reopened]

  workflow_dispatch:

jobs:
  mirror:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout full history
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          fetch-tags: true

      - name: Configure Git
        run: |
          git config --global user.name "OrgBorgCorg"
          git config --global user.email "ivanjaison@gmail.com"

      - name: Fetch and recreate all branches locally
        run: |
          git fetch origin "+refs/heads/*:refs/remotes/origin/*"
          for branch in $(git branch -r | grep origin/ | grep -v '\->' | sed 's|origin/||'); do
            git checkout -B "$branch" "origin/$branch"
          done

      - name: Add ADO Remote
        run: |
          git remote add ado https://:${{ secrets.ADO_PAT }}@dev.azure.com/ivanjmadathil/django-admin-jwt-test/_git/ShellScripts || \
          git remote set-url ado https://:${{ secrets.ADO_PAT }}@dev.azure.com/ivanjmadathil/django-admin-jwt-test/_git/ShellScripts

      - name: Get current GitHub branches
        id: github-branches
        run: |
          echo "github_branches=$(git branch -r | grep origin/ | grep -v '\->' | sed 's|origin/||' | jq -R -s -c 'split("\n")[:-1]')" >> $GITHUB_OUTPUT

      - name: Get current ADO branches
        id: ado-branches
        run: |
          git fetch ado
          echo "ado_branches=$(git ls-remote --heads ado | awk '{print $2}' | sed 's|refs/heads/||' | jq -R -s -c 'split("\n")[:-1]')" >> $GITHUB_OUTPUT

      - name: Delete removed branches from ADO
        run: |
          # Convert JSON arrays to bash arrays
          readarray -t github_branches <<< $(echo '${{ steps.github-branches.outputs.github_branches }}' | jq -r '.[]')
          readarray -t ado_branches <<< $(echo '${{ steps.ado-branches.outputs.ado_branches }}' | jq -r '.[]')

          # Find branches to delete
          for branch in "${ado_branches[@]}"; do
            if [[ ! " ${github_branches[@]} " =~ " ${branch} " ]]; then
              echo "Deleting branch $branch from ADO"
              git push ado --delete "$branch"
            fi
          done

      - name: Push all branches to ADO
        run: |
          git push --verbose ado --all --force
          git push --verbose ado --tags --force

      - name: Show branches pushed to ADO (debug)
        run: git ls-remote --heads ado

```
