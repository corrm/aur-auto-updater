import subprocess

def clone(repo):
    subprocess.check_call([
        "git", "clone",
        f"ssh://aur@aur.archlinux.org/{repo}.git"
    ])

def push(repo_path, msg):
    subprocess.check_call(["git", "add", "."], cwd=repo_path)
    subprocess.call(["git", "commit", "-m", msg], cwd=repo_path)
    subprocess.check_call(["git", "push"], cwd=repo_path)