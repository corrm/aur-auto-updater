import yaml, hashlib, requests, os
from jinja2 import Template

from upstream import fetch
from state import load_state, save_state
from template import select_template

def sha256(url):
    r = requests.get(url)
    r.raise_for_status()
    return hashlib.sha256(r.content).hexdigest()

def build(pkgfile):
    cfg = yaml.safe_load(open(pkgfile))

    pkgname = cfg["pkgname"]
    state_path = f"state/{pkgname}.json"

    state = load_state(state_path, pkgname)

    try:
        tag, url, asset_id = fetch(cfg)

        if state.get("last_version") == tag:
            state["last_success"] = True
            state["last_error"] = None
            save_state(state_path, state)
            return None

        checksum = sha256(url)

        tmpl_path = select_template(cfg)
        tmpl = Template(open(tmpl_path).read())

        pkgver = tag or "0"

        rendered = tmpl.render(
            **cfg,
            pkgver=pkgver,
            download_url=url,
            sha256=checksum
        )

        outdir = f"build/{pkgname}"
        os.makedirs(outdir, exist_ok=True)

        open(f"{outdir}/PKGBUILD", "w").write(rendered)

        state.update({
            "last_version": tag,
            "last_asset_id": asset_id,
            "last_success": True,
            "last_error": None,
            "retry_count": 0
        })

        save_state(state_path, state)

        return {"pkgname": pkgname, "status": "updated"}

    except Exception as e:
        state["last_success"] = False
        state["last_error"] = str(e)
        state["retry_count"] += 1

        save_state(state_path, state)

        return {"pkgname": pkgname, "error": str(e)}