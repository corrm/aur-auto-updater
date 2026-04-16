import json, os
from datetime import datetime

def default_state(pkgname):
    return {
        "pkgname": pkgname,
        "last_version": None,
        "last_asset_id": None,
        "last_commit_sha": None,
        "last_updated": None,
        "last_success": False,
        "last_error": None,
        "retry_count": 0
    }

def load_state(path, pkgname):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        return default_state(pkgname)

    return json.load(open(path))

def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    state["last_updated"] = datetime.utcnow().isoformat() + "Z"
    json.dump(state, open(path, "w"), indent=2)