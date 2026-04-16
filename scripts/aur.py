#!/usr/bin/env python3
"""AUR repository operations - check, clone, and publish packages."""

import os
import re
import shutil
import subprocess
from pathlib import Path


def exists(pkgname: str) -> bool:
    """Check if a package exists in the AUR using SSH git ls-remote.

    This method requires SSH key to be configured for aur@aur.archlinux.org.
    In CI environments, ensure AUR_SSH_PRIVATE_KEY secret is set.

    Args:
        pkgname: The name of the AUR package to check.

    Returns:
        True if the package exists in AUR, False otherwise.
    """
    url = f"ssh://aur@aur.archlinux.org/{pkgname}.git"
    print(f"  [AUR] 🔍 Checking package existence via SSH: {url}...")

    try:
        result = subprocess.run(
            ["git", "ls-remote", url],
            capture_output=True,
            text=True,
            timeout=15
        )

        # If ls-remote succeeds (even with no output), repo exists
        if result.returncode == 0:
            print(f"  [AUR] ✅ Package EXISTS in AUR")
            return True

        # Check stderr for specific errors
        stderr_lower = result.stderr.lower()

        # Repository doesn't exist
        if "not found" in stderr_lower or "does not appear to be a git repository" in stderr_lower:
            print(f"  [AUR] ❌ Package NOT found in AUR (new package)")
            return False

        # SSH authentication errors - this means the repo likely exists but we can't access
        # In CI, this shouldn't happen if SSH key is properly configured
        if "permission denied" in stderr_lower or "publickey" in stderr_lower or "host key verification failed" in stderr_lower:
            print(f"  [AUR] ❌ SSH authentication FAILED")
            print(f"  [AUR] 🔎 Debug info:")
            print(f"  [AUR]     URL: {url}")
            print(f"  [AUR]     Return code: {result.returncode}")
            print(f"  [AUR]     Stderr: {result.stderr.strip()}")
            print(f"  [AUR]     Stdout: {result.stdout.strip() if result.stdout.strip() else '(empty)'}")

            # Check for common SSH issues
            if "permission denied (publickey)" in stderr_lower:
                print(f"  [AUR] 💡 Possible causes:")
                print(f"  [AUR]     - AUR_SSH_PRIVATE_KEY secret is missing or empty")
                print(f"  [AUR]     - SSH key format is incorrect (should be ED25519 or RSA)")
                print(f"  [AUR]     - SSH key permissions are wrong (should be 600)")
                print(f"  [AUR]     - Key is not added to AUR account")
            elif "host key verification failed" in stderr_lower:
                print(f"  [AUR] 💡 Possible causes:")
                print(f"  [AUR]     - known_hosts file is missing aur.archlinux.org")
                print(f"  [AUR]     - SSH strict host key checking is enabled")

            # Fast fail - raise exception instead of returning None
            raise PermissionError(f"SSH authentication failed for {url}: {result.stderr.strip()}")

        # Other errors - assume doesn't exist
        print(f"  [AUR] ⚠️  Git check failed: {result.stderr.strip()}")
        print(f"  [AUR] ❌ Package NOT found in AUR (new package)")
        return False

    except subprocess.TimeoutExpired:
        print(f"  [AUR] ⚠️  Git check timed out")
        print(f"  [AUR] ⚠️  Assuming package does not exist")
        return False
    except FileNotFoundError:
        print(f"  [AUR] ❌ Git command not found")
        return False
    except Exception as e:
        print(f"  [AUR] ❌ Error checking package: {type(e).__name__}: {e}")
        print(f"  [AUR] ⚠️  Assuming package does not exist")
        return False


def clone(repo: str, dest: str = None) -> str:
    """Clone an AUR repository.

    Args:
        repo: The name of the AUR package to clone.
        dest: Optional destination directory (default: aur-repos/{repo})

    Returns:
        Path to the cloned repository.

    Raises:
        subprocess.CalledProcessError: If the git clone fails.
    """
    if dest is None:
        dest = f"aur-repos/{repo}"

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    # Remove existing clone if present
    if os.path.exists(dest):
        shutil.rmtree(dest)

    print(f"  [AUR] 📥 Cloning {repo} from AUR...")
    subprocess.check_call([
        "git", "clone", "--depth", "1",
        f"ssh://aur@aur.archlinux.org/{repo}.git",
        dest
    ])
    return dest


def pull(repo_path: str) -> None:
    """Pull latest changes from AUR repository.

    Args:
        repo_path: Path to the cloned repository.

    Raises:
        subprocess.CalledProcessError: If git pull fails.
    """
    print(f"  [AUR] 🔄 Pulling latest changes...")
    subprocess.check_call(["git", "pull"], cwd=repo_path)


def generate_srcinfo(repo_path: str) -> None:
    """Generate .SRCINFO file from PKGBUILD.

    Args:
        repo_path: Path to the repository containing PKGBUILD.

    Raises:
        subprocess.CalledProcessError: If mksrcinfo fails.
    """
    print(f"  [AUR] 📝 Generating .SRCINFO...")
    try:
        result = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        # Write stdout to .SRCINFO file
        with open(f"{repo_path}/.SRCINFO", "w") as f:
            f.write(result.stdout)

        # Check if command failed
        if result.returncode != 0:
            print(f"  [AUR] ❌ makepkg failed with exit code {result.returncode}")
            print(f"  [AUR] 🔎 STDERR output:")
            for line in result.stderr.split('\n'):
                print(f"         {line}")
            print(f"  [AUR] 🔎 STDOUT output:")
            for line in result.stdout.split('\n'):
                print(f"         {line}")
            raise subprocess.CalledProcessError(result.returncode, ["makepkg", "--printsrcinfo"])

    except FileNotFoundError:
        print(f"  [AUR] ❌ makepkg command not found - please install archlinux-keyring and pacman-contrib")
        raise


def commit_and_push(repo_path: str, msg: str) -> None:
    """Commit and push changes to an AUR repository.

    Args:
        repo_path: Path to the cloned repository.
        msg: Commit message.

    Raises:
        subprocess.CalledProcessError: If git add, commit, or push fails.
    """
    print(f"  [AUR] 📦 Adding files...")
    subprocess.check_call(["git", "add", "."], cwd=repo_path)

    print(f"  [AUR] ✍️  Committing: {msg}")
    subprocess.check_call(["git", "commit", "-m", msg], cwd=repo_path)

    print(f"  [AUR] 🚀 Pushing to AUR...")
    subprocess.check_call(["git", "push"], cwd=repo_path)


def publish(pkgname: str, build_dir: str = "build") -> dict[str, str]:
    """Publish a built package to AUR.

    Args:
        pkgname: Name of the package to publish
        build_dir: Directory containing built PKGBUILD files

    Returns:
        Dictionary with 'pkgname' and 'status'/'error' keys
    """
    print(f"\n{'='*60}")
    print(f"[PUBLISH] Publishing: {pkgname}")
    print(f"{'='*60}")

    try:
        # Check if package exists in AUR
        # Note: exists() now raises PermissionError on SSH auth failure (fast fail)
        in_aur = exists(pkgname)

        if in_aur:
            print(f"[{pkgname}] 📦 Package exists in AUR - will update")
            repo_path = f"aur-repos/{pkgname}"

            # Clone/pull the repository
            if os.path.exists(repo_path):
                pull(repo_path)
            else:
                clone(pkgname, repo_path)
        else:
            print(f"[{pkgname}] ✨ New package - will create in AUR")
            repo_path = f"aur-repos/{pkgname}"
            # For new packages, we need to initialize an empty git repo
            os.makedirs(repo_path, exist_ok=True)
            subprocess.check_call(["git", "init"], cwd=repo_path)
            # Create initial .gitignore
            Path(f"{repo_path}/.gitignore").write_text(".SRCINFO\n")
            subprocess.check_call(["git", "add", "."], cwd=repo_path)
            subprocess.check_call(["git", "commit", "-m", "initial commit"], cwd=repo_path)

        # Copy PKGBUILD from build directory to repo
        src_pkgbuild = f"{build_dir}/{pkgname}/PKGBUILD"
        dst_pkgbuild = f"{repo_path}/PKGBUILD"

        if not os.path.exists(src_pkgbuild):
            raise FileNotFoundError(f"PKGBUILD not found at {src_pkgbuild}")

        print(f"[{pkgname}] 📄 Copying PKGBUILD to repo...")
        shutil.copy2(src_pkgbuild, dst_pkgbuild)

        # Generate .SRCINFO
        generate_srcinfo(repo_path)

        # Determine commit message
        if in_aur:
            msg = f"upstream update: {pkgname}"
        else:
            msg = f"initial package upload: {pkgname}"

        # Commit and push
        commit_and_push(repo_path, msg)

        print(f"[{pkgname}] ✅ SUCCESS - Published to AUR")

        return {"pkgname": pkgname, "status": "published"}

    except Exception as e:
        print(f"[{pkgname}] ❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[{pkgname}] 📋 Traceback:")
        for line in traceback.format_exc().split('\n'):
            print(f"         {line}")

        # Clean up failed clone attempt
        repo_path = f"aur-repos/{pkgname}"
        if os.path.exists(repo_path):
            print(f"[{pkgname}] 🧹 Cleaning up failed clone...")
            shutil.rmtree(repo_path)

        return {"pkgname": pkgname, "error": str(e)}


def publish_all(packages: list[dict[str, str]], build_dir: str = "build") -> dict[str, list]:
    """Publish multiple packages to AUR.

    Args:
        packages: List of package dictionaries with 'pkgname' and 'status' keys
        build_dir: Directory containing built PKGBUILD files

    Returns:
        Dictionary with published, failed lists
    """
    published = []
    failures = []

    for pkg in packages:
        pkgname = pkg.get("pkgname")
        if not pkgname:
            continue

        result = publish(pkgname, build_dir)

        if "error" in result:
            failures.append(result)
        else:
            published.append(result)

    return {"published": published, "failures": failures}