import subprocess

def generate_srcinfo(pkgdir):
    return subprocess.check_output(
        ["makepkg", "--printsrcinfo"],
        cwd=pkgdir,
        text=True
    )