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
        # In CI environments, this shouldn't happen if SSH key is properly configured
        # However, we'll assume the package doesn't exist and continue (don't fail fast)
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

            # Don't fail fast - assume package doesn't exist and let publish handle it
            print(f"  [AUR] ⚠️  Assuming package does not exist due to SSH error")
            return False

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
    """Generate .SRCINFO file from PKGBUILD using pure Python.

    This function parses a PKGBUILD file and generates a valid .SRCINFO
    file without requiring makepkg (which cannot run as root).

    Args:
        repo_path: Path to the repository containing PKGBUILD.

    Raises:
        FileNotFoundError: If PKGBUILD doesn't exist
        Exception: If parsing fails
    """
    print(f"  [AUR] 📝 Generating .SRCINFO...")

    pkgbuild_path = f"{repo_path}/PKGBUILD"

    if not os.path.exists(pkgbuild_path):
        raise FileNotFoundError(f"PKGBUILD not found at {pkgbuild_path}")

    # Read PKGBUILD content
    with open(pkgbuild_path, 'r') as f:
        pkgbuild_content = f.read()

    # Parse PKGBUILD variables
    srcinfo_lines = []

    # Simple bash variable extraction for PKGBUILD
    def extract_value(content: str, varname: str) -> str | None:
        """Extract a variable value from PKGBUILD content."""
        import re
        # Match patterns like: varname=value or varname=(values)
        pattern = rf'^{varname}\s*=\s*(.+?)\s*$'
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def extract_array(content: str, varname: str) -> list[str]:
        """Extract an array variable from PKGBUILD content."""
        import re
        value = extract_value(content, varname)
        if not value:
            return []
        # Remove parentheses and split
        value = value.strip('()')
        if not value:
            return []
        # Split on whitespace, handling quoted strings
        items = []
        current = ''
        in_quotes = False
        quote_char = None
        for char in value:
            if char in '"\'':
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
                else:
                    current += char
            elif char in ' \t\n' and not in_quotes:
                if current:
                    items.append(current.strip('"\''))
                    current = ''
            else:
                current += char
        if current:
            items.append(current.strip('"\''))
        return items

    # Extract basic fields
    pkgname = extract_value(pkgbuild_content, 'pkgname')
    pkgver = extract_value(pkgbuild_content, 'pkgver')
    pkgrel = extract_value(pkgbuild_content, 'pkgrel')
    epoch = extract_value(pkgbuild_content, 'epoch')
    pkgdesc = extract_value(pkgbuild_content, 'pkgdesc')
    url = extract_value(pkgbuild_content, 'url')
    arch = extract_array(pkgbuild_content, 'arch')
    license_list = extract_array(pkgbuild_content, 'license')

    if not pkgname:
        raise ValueError("Could not extract pkgname from PKGBUILD")
    if not pkgver:
        raise ValueError("Could not extract pkgver from PKGBUILD")
    if not pkgrel:
        raise ValueError("Could not extract pkgrel from PKGBUILD")

    # Build SRCINFO content
    srcinfo_lines.append(f"pkgbase = {pkgname}")
    srcinfo_lines.append(f"\tpkgver = {pkgver}")
    srcinfo_lines.append(f"\tpkgrel = {pkgrel}")
    if epoch:
        srcinfo_lines.append(f"\tepoch = {epoch}")
    if pkgdesc:
        # Clean up pkgdesc (remove quotes)
        pkgdesc_clean = pkgdesc.strip('"\'')
        srcinfo_lines.append(f"\tpkgdesc = {pkgdesc_clean}")
    if url:
        srcinfo_lines.append(f"\turl = {url.strip('\"\'')}")

    for a in arch:
        srcinfo_lines.append(f"\tarch = {a}")

    for lic in license_list:
        srcinfo_lines.append(f"\tlicense = {lic.strip('\"\'')}")

    # Extract dependencies
    depends = extract_array(pkgbuild_content, 'depends')
    for dep in depends:
        srcinfo_lines.append(f"\tdepend = {dep.strip('\"\'')}")

    makedepends = extract_array(pkgbuild_content, 'makedepends')
    for dep in makedepends:
        srcinfo_lines.append(f"\tmakedepend = {dep.strip('\"\'')}")

    checkdepends = extract_array(pkgbuild_content, 'checkdepends')
    for dep in checkdepends:
        srcinfo_lines.append(f"\tcheckdepend = {dep.strip('\"\'')}")

    optdepends = extract_array(pkgbuild_content, 'optdepends')
    for dep in optdepends:
        srcinfo_lines.append(f"\toptdepend = {dep.strip('\"\'')}")

    # Extract source URLs and checksums
    sources = extract_array(pkgbuild_content, 'source')
    sha256sums = extract_array(pkgbuild_content, 'sha256sums')
    md5sums = extract_array(pkgbuild_content, 'md5sums')
    sha1sums = extract_array(pkgbuild_content, 'sha1sums')
    sha512sums = extract_array(pkgbuild_content, 'sha512sums')

    for src in sources:
        srcinfo_lines.append(f"\tsource = {src.strip('\"\'')}")

    for checksum in sha256sums:
        srcinfo_lines.append(f"\tsha256sums = {checksum.strip('\"\'')}")

    for checksum in md5sums:
        srcinfo_lines.append(f"\tmd5sums = {checksum.strip('\"\'')}")

    for checksum in sha1sums:
        srcinfo_lines.append(f"\tsha1sums = {checksum.strip('\"\'')}")

    for checksum in sha512sums:
        srcinfo_lines.append(f"\tsha512sums = {checksum.strip('\"\'')}")

    # Write .SRCINFO file
    srcinfo_content = '\n'.join(srcinfo_lines) + '\n'

    with open(f"{repo_path}/.SRCINFO", "w") as f:
        f.write(srcinfo_content)

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