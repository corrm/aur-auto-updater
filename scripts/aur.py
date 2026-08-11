#!/usr/bin/env python3
"""AUR repository operations - check, clone, and publish packages."""

import os
import re
import shutil
import subprocess
import time
from typing import Any
from pathlib import Path

import requests  # type: ignore[import-untyped]

RPC_INFO_URL = "https://aur.archlinux.org/rpc/v5/info"
CGIT_PKGBUILD_URL = "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD"

# Signatures of deterministic git/SSH failures — retrying these never helps.
_DEFINITIVE_ERROR_MARKERS = (
    "not found",
    "does not appear to be a git repository",
    "permission denied",
    "publickey",
    "host key verification failed",
    "non-fast-forward",
)

# Signatures of transient failures worth retrying (AUR maintenance, network hiccups).
_TRANSIENT_ERROR_MARKERS = (
    "the aur is down",
    "down for maintenance",
    "could not read from remote repository",
    "connection reset",
    "connection refused",
    "connection timed out",
    "timed out",
    "temporary failure in name resolution",
    "could not resolve host",
    "service unavailable",
    "connection closed by remote host",
    "broken pipe",
    "network is unreachable",
)


class AurUnavailableError(RuntimeError):
    """The AUR could not be reached (maintenance/outage); state is unknown."""


def _is_transient_git_error(stderr: str) -> bool:
    """True when git stderr looks transient (retryable) rather than deterministic."""
    lowered = stderr.lower()
    if any(marker in lowered for marker in _DEFINITIVE_ERROR_MARKERS):
        return False
    return any(marker in lowered for marker in _TRANSIENT_ERROR_MARKERS)


def _git_run_with_retry(
    cmd: list[str],
    label: str,
    cwd: str | None = None,
    attempts: int = 3,
    backoff: float = 5.0,
    timeout: float | None = None,
    on_retry: Any = None,
) -> subprocess.CompletedProcess:
    """Run a network-bound git command, retrying transient AUR/network failures.

    Args:
        on_retry: Optional zero-arg callable invoked before each retry sleep
            (e.g. to remove a partial clone directory).

    Returns the final CompletedProcess (success or not); raises only when the
    git binary itself is missing.
    """
    result: subprocess.CompletedProcess | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(cmd, 124, "", f"{label} timed out after {timeout}s")
        if result.returncode == 0 or attempt == attempts or not _is_transient_git_error(result.stderr):
            return result
        delay = backoff * attempt
        print(f"  [AUR] ⚠️  {label} failed (attempt {attempt}/{attempts}), transient error — retrying in {delay:.0f}s")
        print(f"  [AUR] 📋 stderr: {result.stderr.strip()}")
        if on_retry is not None:
            on_retry()
        time.sleep(delay)
    return result


def info(pkgname: str) -> dict | None:
    """Look up a package in the AUR via the RPC API — no clone, no SSH.

    Returns the package's info dict (including its 'Version') or None if it is not
    published in the AUR. Raises on network/HTTP errors so callers can distinguish
    "not published" (None) from "couldn't check" (exception).

    Args:
        pkgname: The AUR package name.

    Returns:
        The package info dict, or None if the package is not in the AUR.
    """
    r = requests.get(RPC_INFO_URL, params={"arg[]": pkgname}, timeout=15)
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[0] if results else None


def current_version(pkgname: str) -> str | None:
    """Return the pkgver currently published in the AUR (pkgrel stripped), or None.

    e.g. AUR Version '1.2.3-1' -> '1.2.3'. Uses the RPC API (no clone), so it is the
    authoritative, cheap way to decide whether an upstream bump needs publishing.

    Args:
        pkgname: The AUR package name.

    Returns:
        The published pkgver without pkgrel, or None if not in the AUR.
    """
    data = info(pkgname)
    if not data:
        return None
    version = data.get("Version", "")
    return version.rsplit("-", 1)[0] if version else None


def remote_pkgbuild(pkgname: str) -> str | None:
    """Fetch the AUR's live PKGBUILD text via cgit — no clone, no SSH.

    Used to detect a packaging change (rendered PKGBUILD differs from what's published)
    even when the pkgver is unchanged. Raises on network/HTTP errors other than 404.

    Args:
        pkgname: The AUR package name.

    Returns:
        The raw PKGBUILD text, or None if the package has no published PKGBUILD.
    """
    r = requests.get(CGIT_PKGBUILD_URL, params={"h": pkgname}, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def exists(pkgname: str) -> bool:
    """Check if a package exists in the AUR using SSH git ls-remote.

    This method requires SSH key to be configured for aur@aur.archlinux.org.
    In CI environments, ensure AUR_SSH_PRIVATE_KEY secret is set.

    Args:
        pkgname: The name of the AUR package to check.

    Returns:
        True if the package exists in AUR, False if it definitively does not.

    Raises:
        AurUnavailableError: When the check cannot complete (AUR maintenance or
            outage, SSH misconfiguration). Existence is unknown — callers must
            not guess, or a live package gets misclassified as new.
    """
    url = f"ssh://aur@aur.archlinux.org/{pkgname}.git"
    print(f"  [AUR] 🔍 Checking package existence via SSH: {url}...")

    try:
        result = _git_run_with_retry(
            ["git", "ls-remote", url],
            label="git ls-remote",
            attempts=3,
            backoff=3.0,
            timeout=15,
        )
    except FileNotFoundError:
        print(f"  [AUR] ❌ Git command not found")
        raise AurUnavailableError("git executable not found") from None

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
        print(f"  [AUR] 💡 Check the AUR_SSH_PRIVATE_KEY secret (format, permissions, registered on AUR)")
        print(f"  [AUR] 💡 Check known_hosts contains aur.archlinux.org")
        print(f"  [AUR] 📋 stderr: {result.stderr.strip()}")
        raise AurUnavailableError(f"SSH authentication failed while checking {pkgname}")

    print(f"  [AUR] ⚠️  Existence check failed (AUR down or unreachable): {result.stderr.strip()}")
    raise AurUnavailableError(f"Could not check AUR existence for {pkgname}: {result.stderr.strip()}")


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
    result = _git_run_with_retry(
        ["git", "clone", f"ssh://aur@aur.archlinux.org/{repo}.git", dest],
        label=f"clone {repo}",
        on_retry=lambda: shutil.rmtree(dest, ignore_errors=True),
    )
    if result.returncode != 0:
        print(f"  [AUR] ❌ Clone failed: {result.stderr.strip()}")
        raise subprocess.CalledProcessError(
            result.returncode, "git clone", output=result.stdout, stderr=result.stderr
        )
    # Shallow clone (--depth 1) leaves HEAD detached on git >=2.48 and
    # doesn't set up remote tracking refs properly; AUR repos are tiny
    # so a full clone is fast and avoids all these issues.
    # Skip checkout for empty repos (new AUR packages with no commits yet).
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/master"],
        cwd=dest, capture_output=True,
    )
    if result.returncode == 0:
        subprocess.check_call(["git", "checkout", "-B", "master", "origin/master"], cwd=dest)
    return dest


def pull(repo_path: str) -> None:
    """Pull latest changes from AUR repository.

    Args:
        repo_path: Path to the cloned repository.

    Raises:
        subprocess.CalledProcessError: If git pull fails.
    """
    print(f"  [AUR] 🔄 Pulling latest changes...")
    result = _git_run_with_retry(["git", "pull", "origin", "master"], label="git pull", cwd=repo_path)
    if result.returncode != 0:
        print(f"  [AUR] ❌ Pull failed: {result.stderr.strip()}")
        raise subprocess.CalledProcessError(
            result.returncode, "git pull", output=result.stdout, stderr=result.stderr
        )


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
    print(f"  [AUR] 📝 Generating .SRCINFO using makepkg...")

    from makepkg_wrapper import generate_srcinfo as _generate_srcinfo
    _generate_srcinfo(repo_path)


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

    # Debug: check what files are staged
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
    print(f"  [AUR] 📋 Staged files:\n{result.stdout}")
    
    if not result.stdout.strip():
        print(f"  [AUR] ⚠️  No files to commit!")
        return

    print(f"  [AUR] ✍️  Committing: {msg}")
    result = subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [AUR] ❌ Git commit failed: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, "git commit", output=result.stderr)

    print(f"  [AUR] 🚀 Pushing to AUR...")
    result = _git_run_with_retry(["git", "push", "origin", "master"], label="git push", cwd=repo_path)
    if result.returncode != 0:
        print(f"  [AUR] ❌ Git push failed!")
        print(f"  [AUR] 📋 stderr: {result.stderr.strip()}")
        print(f"  [AUR] 📋 stdout: {result.stdout.strip() if result.stdout.strip() else '(empty)'}")
        raise subprocess.CalledProcessError(result.returncode, "git push", output=result.stderr, stderr=result.stderr)


def publish(pkgname: str, build_dir: str = "build", is_new: bool | None = None) -> dict[str, str]:
    """Publish a built package to AUR.

    Args:
        pkgname: Name of the package to publish.
        build_dir: Directory containing built PKGBUILD files.
        is_new: Whether the package is unpublished in AUR. Pass the build step's
            RPC-authoritative answer (True = created, False = updated) so a flaky
            SSH check can't flip an existing package into the new-package path.
            When None, falls back to an SSH existence check.

    Returns:
        Dictionary with 'pkgname' and 'status'/'error' keys.
    """
    print(f"\n{'='*60}")
    print(f"[PUBLISH] Publishing: {pkgname}")
    print(f"{'='*60}")

    try:
        if is_new is None:
            in_aur = exists(pkgname)
        else:
            in_aur = not is_new
            note = "new" if is_new else "existing"
            print(f"[{pkgname}] 🔎 Skipping SSH existence check — build's AUR RPC check says {note}")
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
            subprocess.check_call(["git", "init", "-b", "master"], cwd=repo_path)
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

        status = pkg.get("status")
        is_new = (status == "created") if status in ("created", "updated") else None
        result = publish(pkgname, build_dir, is_new=is_new)

        if "error" in result:
            failures.append(result)
        else:
            published.append(result)

    return {"published": published, "failures": failures}