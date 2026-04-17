#!/usr/bin/env python3
"""Generate .SRCINFO files for AUR packages."""

import subprocess


def generate_srcinfo(pkgdir: str) -> str:
    """Generate .SRCINFO content for a package directory.
    
    Args:
        pkgdir: Path to the package directory containing PKGBUILD.
        
    Returns:
        The generated .SRCINFO content as a string.
        
    Raises:
        subprocess.CalledProcessError: If makepkg fails.
    """
    env = os.environ.copy()
    env["ALLOW_ROOT"] = "1"
    return subprocess.check_output(
        ["makepkg", "--printsrcinfo"],
        cwd=pkgdir,
        text=True,
        env=env
    )