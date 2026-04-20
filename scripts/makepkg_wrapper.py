#!/usr/bin/env python3
"""Unified makepkg wrapper for generating .SRCINFO and other makepkg operations."""
from __future__ import annotations

import subprocess
import os


def run_makepkg(*args: str, cwd: str | None = None, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run makepkg with unified error handling and stderr output.
    
    Args:
        args: Arguments to pass to makepkg
        cwd: Working directory
        
    Returns:
        CompletedProcess object
    """
    cmd = ["makepkg", *args]
    print(f"  [makepkg] Running: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture_output,
        text=True,
    )
    
    if result.returncode != 0:
        print(f"  [makepkg] ❌ Exit code: {result.returncode}")
        if result.stderr:
            print(f"  [makepkg] stderr:\n{result.stderr}")
    
    return result


def generate_srcinfo(repo_path: str) -> None:
    """Generate .SRCINFO file from PKGBUILD.
    
    Args:
        repo_path: Path to the directory containing PKGBUILD
    """
    print(f"  [makepkg] Generating .SRCINFO...")
    
    pkgbuild_path = f"{repo_path}/PKGBUILD"
    if not os.path.exists(pkgbuild_path):
        raise FileNotFoundError(f"PKGBUILD not found at {pkgbuild_path}")
    
    result = run_makepkg("--printsrcinfo", cwd=repo_path)
    
    if result.returncode == 0:
        with open(f"{repo_path}/.SRCINFO", "w") as f:
            f.write(result.stdout)
        print(f"  [makepkg] ✅ .SRCINFO generated successfully")
    else:
        raise subprocess.CalledProcessError(
            result.returncode, 
            "makepkg", 
            output=result.stderr
        )