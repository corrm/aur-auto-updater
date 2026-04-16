import requests
import re

def github_latest(repo, asset_regex):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    tag = data["tag_name"].lstrip("v")

    for a in data["assets"]:
        if re.match(asset_regex, a["name"]):
            return tag, a["browser_download_url"], a["id"]

    raise RuntimeError("No matching asset found")


def fetch(cfg):
    upstream = cfg["upstream"]

    if upstream["provider"] == "github":
        return github_latest(upstream["repo"], upstream["asset_regex"])

    if upstream["provider"] == "url":
        # minimal direct URL mode
        return None, upstream["url"], None

    raise RuntimeError("Unsupported provider")