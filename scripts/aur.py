#!/usr/bin/env python3
"""AUR repository operations."""

import subprocess


def clone(repo: str) -> None:
    """Clone an AUR repository.
    
    Args:
        repo: The name of the AUR package to clone.
        
    Raises:
        subprocess.CalledProcessError: If the git clone fails.
    """
    subprocess.check_call([
        "git", "clone",
        f"ssh://aur@aur.archlinux.org/{repo}.git"
    ])


def push(repo_path: str, msg: str) -> None:
    """Commit and push changes to an AUR repository.
    
    Args:
        repo_path: Path to the cloned repository.
        msg: Commit message.
        
    Raises:
        subprocess.CalledProcessError: If git add or push fails.
    """
    subprocess.check_call(["git", "add", "."], cwd=repo_path)
    subprocess.call(["git", "commit", "-m", msg], cwd=repo_path)
    subprocess.check_call(["git", "push"], cwd=repo_path)