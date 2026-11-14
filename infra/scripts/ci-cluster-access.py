"""Temporary runner access to an existing DOKS cluster; never provisions resources."""

import ipaddress
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api(path="", body=None):
    cluster_id = str(uuid.UUID(os.environ["DIGITALOCEAN_CLUSTER_ID"]))
    request = Request(
        f"https://api.digitalocean.com/v2/kubernetes/clusters/{cluster_id}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["DIGITALOCEAN_TOKEN"],
            "Content-Type": "application/json",
        },
        method="GET" if body is None else "PUT",
    )
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (409, 429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def update_firewall(cluster, addresses):
    api(body={
        "name": cluster["name"],
        "control_plane_firewall": {"enabled": True, "allowed_addresses": addresses},
    })


def open_access(state, kubeconfig):
    cluster = json.loads(api())["kubernetes_cluster"]
    firewall = cluster.get("control_plane_firewall") or {}
    addresses = firewall.get("allowed_addresses") or []
    added = None
    if firewall.get("enabled"):
        with urlopen("https://api.ipify.org", timeout=20) as response:
            ip = ipaddress.IPv4Address(response.read().decode().strip())
        if not any(ip in ipaddress.ip_network(cidr) for cidr in addresses):
            added = f"{ip}/32"
    # Persist cleanup intent BEFORE the API write, including on an ambiguous failure.
    write_private(state, json.dumps({"added": added}).encode())
    if added:
        update_firewall(cluster, addresses + [added])
    write_private(kubeconfig, api("/kubeconfig?expiry_seconds=1800&type=token"))
    print("Short-lived cluster credentials prepared; no resources provisioned.")


def close_access(state):
    if not state.exists():
        return
    added = json.loads(state.read_text())["added"]
    if added:
        cluster = json.loads(api())["kubernetes_cluster"]
        firewall = cluster.get("control_plane_firewall") or {}
        addresses = firewall.get("allowed_addresses") or []
        if firewall.get("enabled") and added in addresses:
            # Re-read so cleanup preserves operator changes made during deployment.
            update_firewall(cluster, [cidr for cidr in addresses if cidr != added])
    state.unlink()
    print("Temporary runner access removed.")


if __name__ == "__main__":
    state = Path(os.environ["ACCESS_STATE"])
    if sys.argv[1:] == ["open"]:
        open_access(state, Path(os.environ["KUBECONFIG"]))
    elif sys.argv[1:] == ["close"]:
        close_access(state)
    else:
        raise SystemExit("Usage: ci-cluster-access.py open|close")
