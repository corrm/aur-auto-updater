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
    """Generate .SRCINFO file from a rendered PKGBUILD using pure Python.

    Parses the PKGBUILD produced by the Jinja2 template rendering step
    (build/pkgname/PKGBUILD) and writes a valid .SRCINFO beside it.
    Does not require makepkg so it works when running as root in CI.

    The data flow is:
        packages/foo.yaml → Jinja2 template → PKGBUILD → (this fn) → .SRCINFO

    Args:
        repo_path: Path to the directory containing PKGBUILD.

    Raises:
        FileNotFoundError: If PKGBUILD does not exist.
        ValueError: If required fields (pkgname, pkgver, pkgrel) are missing.
    """
    print(f"  [AUR] 📝 Generating .SRCINFO...")

    pkgbuild_path = f"{repo_path}/PKGBUILD"
    if not os.path.exists(pkgbuild_path):
        raise FileNotFoundError(f"PKGBUILD not found at {pkgbuild_path}")

    with open(pkgbuild_path, "r") as f:
        content = f.read()

    def extract_scalar(varname: str) -> str | None:
        """Extract a scalar bash variable, stripping surrounding quotes."""
        # Double-quoted: varname="value"
        match = re.search(rf'^{varname}\s*=\s*"([^"]*)"', content, re.MULTILINE)
        if match:
            return match.group(1)
        # Single-quoted: varname='value'
        match = re.search(rf"^{varname}\s*=\s*'([^']*)'", content, re.MULTILINE)
        if match:
            return match.group(1)
        # Bare: varname=value
        match = re.search(rf'^{varname}\s*=\s*([^\s(][^\n]*)', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def extract_array(varname: str) -> list[str]:
        """Extract a bash array variable, handling multi-line forms.

        Handles both single-line  varname=(a b c)
        and multi-line            varname=(
                                      a
                                      b
                                  )
        Preserves the filename::url rename syntax used in source=().
        """
        match = re.search(
            rf'^{varname}\s*=\s*\((.*?)\)',
            content,
            re.MULTILINE | re.DOTALL,
        )
        if not match:
            return []

        raw = match.group(1)
        # Tokenize: quoted strings first, then bare words
        items = []
        for token in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', raw):
            items.append(token.strip("\"'"))
        return items

    # ------------------------------------------------------------------ #
    # Required fields
    # ------------------------------------------------------------------ #
    pkgname = extract_scalar("pkgname")
    pkgver  = extract_scalar("pkgver")
    pkgrel  = extract_scalar("pkgrel")

    if not pkgname:
        raise ValueError("Could not extract pkgname from PKGBUILD")
    if not pkgver:
        raise ValueError("Could not extract pkgver from PKGBUILD")
    if not pkgrel:
        raise ValueError("Could not extract pkgrel from PKGBUILD")

    # ------------------------------------------------------------------ #
    # Build .SRCINFO lines
    # ------------------------------------------------------------------ #
    lines: list[str] = []

    def scalar_line(key: str, val: str | None) -> None:
        if val:
            lines.append(f"\t{key} = {val}")

    def array_lines(key: str, vals: list[str]) -> None:
        for v in vals:
            lines.append(f"\t{key} = {v}")

    lines.append(f"pkgbase = {pkgname}")

    scalar_line("pkgdesc",      extract_scalar("pkgdesc"))
    scalar_line("pkgver",       pkgver)
    scalar_line("pkgrel",       pkgrel)
    scalar_line("epoch",        extract_scalar("epoch"))
    scalar_line("url",          extract_scalar("url"))

    array_lines("arch",         extract_array("arch"))
    array_lines("license",      extract_array("license"))
    array_lines("depends",      extract_array("depends"))
    array_lines("makedepends",  extract_array("makedepends"))
    array_lines("checkdepends", extract_array("checkdepends"))
    array_lines("optdepends",   extract_array("optdepends"))
    array_lines("conflicts",    extract_array("conflicts"))
    array_lines("provides",     extract_array("provides"))
    array_lines("replaces",     extract_array("replaces"))
    array_lines("noextract",    extract_array("noextract"))
    array_lines("options",      extract_array("options"))
    array_lines("source",       extract_array("source"))
    array_lines("sha256sums",   extract_array("sha256sums"))
    array_lines("sha512sums",   extract_array("sha512sums"))
    array_lines("md5sums",      extract_array("md5sums"))
    array_lines("sha1sums",     extract_array("sha1sums"))

    # AUR's server-side hook requires a pkgname block at the end
    lines.append("")
    lines.append(f"pkgname = {pkgname}")
    lines.append("")

    with open(f"{repo_path}/.SRCINFO", "w") as f:
        f.write("\n".join(lines))

    print(f"  [AUR] ✅ .SRCINFO generated successfully")


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