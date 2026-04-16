def select_template(cfg):
    if cfg["type"] == "appimage":
        return "templates/appimage.PKGBUILD.j2"

    if cfg["type"] == "debian":
        return "templates/debian.PKGBUILD.j2"

    raise RuntimeError("Unknown package type")