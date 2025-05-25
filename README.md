ps: assuming you have pat tokens for both ado and gh, access to gh-cli and The User has git ssh/gpg key permissions on both the repos(Existing ADO repo and new GitHub repo)

## 1. Bare Migration of Files from ADO-repo to GH-repo

- Firstly create a repo on github without a readme
- Then execute the following script [code_migration.py](./code_migration.py) as so

```bash
python code_migration.py <ADO_REPO_URL> <GH_REPO_URL>
```

- What this code does :
  - Parses two command-line arguments:
    - <ADO_REPO_URL>: the Azure DevOps repository URL
    - <GH_REPO_URL>: the GitHub repository URL
  - Extracts the repository name from the Azure URL and appends .git to prepare for mirroring
  - Clones the Azure DevOps repo/ This creates a bare clone, copying all branches, tags, and refs.
  - Changes into the cloned repo directory
  - Pushes the mirrored repository to GitHub. This replicates all history, branches, and tags to GitHub. Errors are ignored to allow partial pushes if necessary.
  - Extracts the owner/repo from the GitHub URL using regex
  - Sets the default branch to main on GitHub. This step uses GitHub CLI and is optional — the script continues even if it fails

## 2. Migrating The PR's from ADO to GH

- Execute the following script [prmigrate.py](./prmigrate.py) as so

```bash
python prmigrate.py --ado-org <org_name> --ado-project <project_name> --ado-repo <ado_repo_name> --github-repo <user/repo_name>  --ado-pat <ADO_PAT_HERE>
```

or by using powershell env vars

```bash
export ADO_PAT=MY_ADO_PAT
python migrate_prs.py --ado-org myorg --ado-project myproject --ado-repo myrepo --github-repo myuser/mygithubrepo
```

- What the script does :
  - Connect to Azure DevOps using the PAT (Personal Access Token) to authenticate via REST API.
  - Hits the endpoint: https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repoId}/pullrequests
  - Fetch PR Metadata : Title, Description, Source branch, Target Branch
  - Use gh-cli to create pr(gh pr create --title "..." --body "..." --head source --base target)
  - Recreates the PR structure on GitHub, assuming branches already exist and are pushed.
- What the script does notdo/migrate:
  -PR Comments(not git objects and live in ADO’s PR discussion system which has no equivalent for gh pr create)
  -Review History(GH has no api endpoint allowing importing of review events outside of GH)
  -GH reviews and approvals(security reasons)
  -Attachments (are usually blobs hosted by ado and linked to prs or comments. GH does not support uploading attachments via PR API)

## 3. Migrating ADO pipelines to GH action pipelines

- Hasnt been automated yet but for now
- Either :
  - Refer to the following github project: [ADO-Pipeline-Yml-To-Github-Actions-Yml](https://github.com/rdx40/ADO-Pipeline-Yml-To-Github-Actions-Yml.git) A WebAPI that takes a ado pipeline as input and returns a github actions yaml as output
- OR Use the original project it was based on :
  - https://pipelinestoactions.azurewebsites.net/

## 4. Migrating Work Items(Issues, Tasks, Bugs)

- Although there does exist a powershell script for the same objective [This one](https://github.com/joshjohanning/ado_workitems_to_github_issues)
- Personally Using a python script for such tasks has always been my go to. So you could execute the following script [migrate_workitems.py](./migrate_workitems.py) as so

```bash
python migrate_workitems.py --ado-org <ORG_NAME> --ado-project <PROJECT_NAME> --github-repo <user/repo_name> --ado-pat <ADO_PAT_HERE> --github-token <GH_TOKEN_HERE>
```

## 5. To Follow Security Practises

- Please do refer to [Security_Practises.txt](./Security_Practises.txt)
