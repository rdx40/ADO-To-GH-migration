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