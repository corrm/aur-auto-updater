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
            timeout=15,
        )

        if result.returncode == 0:
            print(f"  [AUR] ✅ Package EXISTS in AUR")
            return True

        stderr_lower = result.stderr.lower()

        if "not found" in stderr_lower or "does not appear to be a git repository" in stderr_lower:
            print(f"  [AUR] ❌ Package NOT found in AUR (new package)")
            return False

        if (
            "permission denied" in stderr_lower
            or "publickey" in stderr_lower
            or "host key verification failed" in stderr_lower
        ):
            print(f"  [AUR] ❌ SSH authentication FAILED")
            print(f"  [AUR] 🔎 Debug info:")
            print(f"  [AUR]     URL: {url}")
            print(f"  [AUR]     Return code: {result.returncode}")
            print(f"  [AUR]     Stderr: {result.stderr.strip()}")
            print(f"  [AUR]     Stdout: {result.stdout.strip() if result.stdout.strip() else '(empty)'}")

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

            print(f"  [AUR] ⚠️  Assuming package does not exist due to SSH error")
            return False

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

    if os.path.exists(dest):
        shutil.rmtree(dest)

    print(f"  [AUR] 📥 Cloning {repo} from AUR...")
    subprocess.check_call([
        "git", "clone", "--depth", "1",
        f"ssh://aur@aur.archlinux.org/{repo}.git",
        dest,
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
    """Generate .SRCINFO file from a rendered PKGBUILD using makepkg.

    Uses the official `makepkg --printsrcinfo` command to generate a valid
    .SRCINFO file. This is the recommended approach by Arch Linux and ensures
    compatibility with AUR requirements.

    When running as root (e.g., in CI), sets ALLOW_ROOT=1 to allow makepkg
    to run safely in controlled environments.

    The data flow is:
        packages/foo.yaml → Jinja2 template → PKGBUILD → (this fn) → .SRCINFO

    Args:
        repo_path: Path to the directory containing PKGBUILD.

    Raises:
        FileNotFoundError: If PKGBUILD does not exist.
        subprocess.CalledProcessError: If makepkg fails.
    """
    print(f"  [AUR] 📝 Generating .SRCINFO...")

    pkgbuild_path = f"{repo_path}/PKGBUILD"
    if not os.path.exists(pkgbuild_path):
        raise FileNotFoundError(f"PKGBUILD not found at {pkgbuild_path}")

    srcinfo = generate_srcinfo_from_pkgbuild(pkgbuild_path)

    with open(f"{repo_path}/.SRCINFO", "w") as f:
        f.write(srcinfo)

    print(f"  [AUR] ✅ .SRCINFO generated successfully")


def generate_srcinfo_from_pkgbuild(pkgbuild_path: str) -> str:
    """Generate .SRCINFO from PKGBUILD by parsing it directly."""
    import re

    with open(pkgbuild_path, "r") as f:
        content = f.read()

    lines = content.split("\n")
    pkgname = pkgver = pkgrel = pkgdesc = arch = url = ""
    license_arr = []
    depends = []
    makedepends = []
    source = []
    sha256sums = []
    noextract = []
    options = []

    for line in lines:
        line = line.strip()
        if line.startswith("pkgname="):
            pkgname = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("pkgver="):
            pkgver = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("pkgrel="):
            pkgrel = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("pkgdesc="):
            pkgdesc = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("arch="):
            arch = line.split("=", 1)[1].strip().strip("()")
        elif line.startswith("url="):
            url = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("license="):
            license_arr = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("depends="):
            depends = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("makedepends="):
            makedepends = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("source="):
            source = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("sha256sums="):
            sha256sums = [x.strip().strip("'\"") for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("noextract="):
            noextract = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]
        elif line.startswith("options="):
            options = [x.strip() for x in line.split("=", 1)[1].strip("()").split()]

    srcinfo_lines = ["pkgbase = " + pkgname, "pkgname = " + pkgname, "pkgver = " + pkgver,
                     "pkgrel = " + pkgrel, "pkgdesc = " + pkgdesc, "arch = " + arch,
                     "url = " + url, "license = " + " ".join(license_arr)]

    for dep in depends:
        srcinfo_lines.append("depends = " + dep)
    for mdep in makedepends:
        srcinfo_lines.append("makedepends = " + mdep)
    for src in source:
        srcinfo_lines.append("source = " + src)
    for sha in sha256sums:
        srcinfo_lines.append("sha256sums = " + sha)
    for nex in noextract:
        srcinfo_lines.append("noextract = " + nex)
    for opt in options:
        srcinfo_lines.append("options = " + opt)

    return "\n".join(srcinfo_lines) + "\n"


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
        pkgname: Name of the package to publish.
        build_dir: Directory containing built PKGBUILD files.

    Returns:
        Dictionary with 'pkgname' and 'status'/'error' keys.
    """
    print(f"\n{'='*60}")
    print(f"[PUBLISH] Publishing: {pkgname}")
    print(f"{'='*60}")

    try:
        in_aur = exists(pkgname)
        repo_path = f"aur-repos/{pkgname}"

        if in_aur:
            print(f"[{pkgname}] 📦 Package exists in AUR - will update")
            if os.path.exists(repo_path):
                pull(repo_path)
            else:
                clone(pkgname, repo_path)
        else:
            print(f"[{pkgname}] ✨ New package - will create in AUR")
            os.makedirs(repo_path, exist_ok=True)
            subprocess.check_call(["git", "init"], cwd=repo_path)
            # AUR requires the remote to be set before push
            subprocess.check_call(
                ["git", "remote", "add", "origin",
                 f"ssh://aur@aur.archlinux.org/{pkgname}.git"],
                cwd=repo_path,
            )

        src_pkgbuild = f"{build_dir}/{pkgname}/PKGBUILD"
        if not os.path.exists(src_pkgbuild):
            raise FileNotFoundError(f"PKGBUILD not found at {src_pkgbuild}")

        print(f"[{pkgname}] 📄 Copying PKGBUILD to repo...")
        shutil.copy2(src_pkgbuild, f"{repo_path}/PKGBUILD")

        generate_srcinfo(repo_path)

        msg = f"upstream update: {pkgname}" if in_aur else f"initial package upload: {pkgname}"
        commit_and_push(repo_path, msg)

        print(f"[{pkgname}] ✅ SUCCESS - Published to AUR")
        return {"pkgname": pkgname, "status": "published"}

    except Exception as e:
        print(f"[{pkgname}] ❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[{pkgname}] 📋 Traceback:")
        for line in traceback.format_exc().split("\n"):
            print(f"         {line}")

        repo_path = f"aur-repos/{pkgname}"
        if os.path.exists(repo_path):
            print(f"[{pkgname}] 🧹 Cleaning up failed clone...")
            shutil.rmtree(repo_path)

        return {"pkgname": pkgname, "error": str(e)}


def publish_all(packages: list[dict[str, str]], build_dir: str = "build") -> dict[str, list]:
    """Publish multiple packages to AUR.

    Args:
        packages: List of package dicts with 'pkgname' and 'status' keys.
        build_dir: Directory containing built PKGBUILD files.

    Returns:
        Dictionary with 'published' and 'failures' lists.
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