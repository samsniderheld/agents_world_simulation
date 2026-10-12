#!/usr/bin/env python3
"""Create and delete the RunPod pods that run ComfyUI for the app.

    python deploy/runpod-comfyui/pods.py up            # both pods (they boot at the same time)
    python deploy/runpod-comfyui/pods.py up image      # create (or reuse) the image pod, ready to use
    python deploy/runpod-comfyui/pods.py up video
    python deploy/runpod-comfyui/pods.py status        # pods, cost per hour, URLs, ComfyUI up?
    python deploy/runpod-comfyui/pods.py down video    # delete the video pod (its volume stays)
    python deploy/runpod-comfyui/pods.py down all
    python deploy/runpod-comfyui/pods.py down image --volume --yes   # ...and delete its network volume too

Each kind (image, video) gets a RunPod network volume mounted at /workspace:
ComfyUI and the models live there, so `down` deletes the pod (no more GPU
billing) without losing anything, and the next `up` starts with everything
in place -- you only pay the volume's storage in between.

`up` creates the volume and the pod (RunPod's ComfyUI template image, the
GPUs and data center in pods.yaml), waits for ComfyUI to answer, and checks
it has every node and model file the kind's workflow uses. If not (a new
volume), it runs setup.sh on the pod over SSH -- your ~/.ssh public key is
given to the pod -- to download the models and update ComfyUI, restarting
the pod if needed. Finally it makes the pod the app's default ComfyUI server
for that kind (the running app's, or saved for its next start).

Needs RUNPOD_API_KEY in city_simulator/.env (RunPod console -> Settings -> API Keys).
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]                       # city_simulator/
sys.path.insert(0, str(APP))

API_URL = os.environ.get("RUNPOD_API_URL", "https://rest.runpod.io/v1")
APP_URL = os.environ.get("CITY_SIM_URL", "http://127.0.0.1:8420")
KINDS = ("image", "video")
WAIT_MINUTES = 30                           # the first boot copies ComfyUI onto the volume


def name_for(kind: str) -> str:
    return f"city-sim-comfyui-{kind}"


def load_settings(path: Path = HERE / "pods.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def say(*parts, end="\n"):
    print(*parts, end=end, flush=True)


class RunPod:
    """The bits of RunPod's REST API (https://rest.runpod.io/v1) this needs."""

    def __init__(self, api_key: str, base_url: str = API_URL, session: requests.Session = None):
        if not api_key:
            raise SystemExit("RUNPOD_API_KEY isn't set -- add it to city_simulator/.env "
                             "(RunPod console -> Settings -> API Keys).")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _req(self, method: str, path: str, **kw):
        resp = self.session.request(method, f"{self.base_url}{path}", timeout=60, **kw)
        if resp.status_code == 401:
            raise SystemExit("RunPod rejected RUNPOD_API_KEY (401) -- check it in city_simulator/.env.")
        if resp.status_code == 403:
            raise SystemExit(f"RunPod refused {method} {path} (403): RUNPOD_API_KEY doesn't have permission for it. "
                             "Use a key with Read/Write access (RunPod console -> Settings -> API Keys), or a "
                             "restricted key that can manage Pods and Network Volumes.")
        if resp.status_code >= 400:
            raise RuntimeError(f"RunPod {method} {path} failed ({resp.status_code}): {resp.text[:400]}")
        return resp.json() if resp.content else None

    def pods(self) -> list:
        return self._req("GET", "/pods") or []

    def pod(self, pod_id: str) -> dict:
        return self._req("GET", f"/pods/{pod_id}")

    def create_pod(self, body: dict) -> dict:
        return self._req("POST", "/pods", json=body)

    def start_pod(self, pod_id: str):
        return self._req("POST", f"/pods/{pod_id}/start")

    def restart_pod(self, pod_id: str):
        return self._req("POST", f"/pods/{pod_id}/restart")

    def delete_pod(self, pod_id: str):
        return self._req("DELETE", f"/pods/{pod_id}")

    def volumes(self) -> list:
        return self._req("GET", "/networkvolumes") or []

    def create_volume(self, name: str, size: int, datacenter: str) -> dict:
        return self._req("POST", "/networkvolumes", json={"name": name, "size": size, "dataCenterId": datacenter})

    def delete_volume(self, volume_id: str):
        return self._req("DELETE", f"/networkvolumes/{volume_id}")


def find_pod(api: RunPod, kind: str):
    live = [p for p in api.pods() if p.get("name") == name_for(kind) and p.get("desiredStatus") != "TERMINATED"]
    return live[0] if live else None


def find_volume(api: RunPod, kind: str):
    return next((v for v in api.volumes() if v.get("name") == name_for(kind)), None)


def comfyui_url(settings: dict, pod_id: str) -> str:
    return settings.get("comfyui_url", "https://{pod_id}-8188.proxy.runpod.net").format(pod_id=pod_id)


def ssh_public_key() -> str:
    """The public key handed to the pod (RunPod's image adds PUBLIC_KEY to
    root's authorized_keys) so setup.sh can be run over SSH."""
    named = os.environ.get("RUNPOD_SSH_PUBLIC_KEY")
    candidates = [Path(named).expanduser()] if named else \
        [Path.home() / ".ssh" / n for n in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub")]
    for path in candidates:
        if path.exists():
            return path.read_text().strip()
    return ""


def wait_for_comfyui(url: str, minutes: float = WAIT_MINUTES, session: requests.Session = None) -> bool:
    session = session or requests.Session()
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        try:
            if session.get(f"{url}/system_stats", timeout=10).status_code == 200:
                say(" up")
                return True
        except requests.RequestException:
            pass
        say(".", end="")
        time.sleep(10)
    say()
    return False


def check(kind: str, url: str) -> dict:
    from visuals.providers.comfyui import check_server
    return check_server(kind, url)


def describe(result: dict) -> str:
    if result.get("error"):
        return result["error"]
    parts = [f"ComfyUI {result.get('version')} on {result.get('gpu')}"]
    if result.get("missing_nodes"):
        parts.append("missing nodes: " + ", ".join(result["missing_nodes"]))
    if result.get("missing_models"):
        parts.append("missing models: " + ", ".join(result["missing_models"]))
    return "; ".join(parts)


def run_setup_over_ssh(pod: dict, kind: str) -> int:
    """setup.sh on the pod (fed over SSH, so the pod needs no copy of this
    repo); its exit code (3 = ComfyUI was updated, restart it), or None if
    the pod has no SSH port yet / no key was given."""
    port = (pod.get("portMappings") or {}).get("22")
    ip = pod.get("publicIp")
    if not (port and ip and ssh_public_key()):
        return None
    say(f"== running setup.sh {kind} on the pod over SSH (root@{ip} -p {port})")
    cmd = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
           "-o", "ConnectTimeout=20", f"root@{ip}", f"COMFYUI_UPDATE=1 bash -s {kind}"]
    with open(HERE / "setup.sh", "rb") as script:
        return subprocess.run(cmd, stdin=script).returncode


def set_app_default(kind: str, url: str):
    """Make `url` the app's default ComfyUI server for `kind`: through the
    running app if it's up (takes effect now), else saved for its next start."""
    try:
        r = requests.post(f"{APP_URL}/api/visuals/comfyui/default", json={"kind": kind, "url": url}, timeout=5)
        if r.ok and r.json().get("ok"):
            say(f"The app now uses it for {kind} (no restart needed).")
            return
    except requests.RequestException:
        pass
    from visuals import config
    config.save_comfyui_default(kind, url)
    say(f"Saved as the app's default {kind} server (it picks it up when started).")


def up(api: RunPod, settings: dict, kind: str, wait_minutes: float = WAIT_MINUTES):
    """One kind: launch its pod, then get it ready."""
    return ready(api, settings, kind, launch(api, settings, kind), wait_minutes)


def up_many(api: RunPod, settings: dict, kinds, wait_minutes: float = WAIT_MINUTES) -> dict:
    """Several kinds: launch every pod first (so they boot at the same time),
    then get each ready in turn. One kind failing doesn't stop the others.
    Returns {kind: pod, or the failure message}."""
    launched, results = {}, {}
    for kind in kinds:
        try:
            launched[kind] = launch(api, settings, kind)
        except (SystemExit, RuntimeError) as e:
            results[kind] = str(e)
    for kind, pod in launched.items():
        say(f"\n---- {kind} ----")
        try:
            results[kind] = ready(api, settings, kind, pod, wait_minutes)
        except (SystemExit, RuntimeError) as e:
            results[kind] = str(e)
    say("\n==== summary")
    for kind in kinds:
        r = results.get(kind)
        say(f"  {kind}: " + (f"ready -- {comfyui_url(settings, r['id'])}" if isinstance(r, dict) else f"FAILED -- {r}"))
    return results


def launch(api: RunPod, settings: dict, kind: str) -> dict:
    """The kind's volume (made if new) and its pod, created, started or reused."""
    spec = settings[kind]
    volume = find_volume(api, kind)
    if volume is None:
        say(f"== creating network volume {name_for(kind)} ({spec['volume_gb']} GB in {settings['datacenter']})")
        volume = api.create_volume(name_for(kind), int(spec["volume_gb"]), settings["datacenter"])
    pod = find_pod(api, kind)
    if pod and pod.get("desiredStatus") == "RUNNING":
        say(f"== pod {pod['id']} is already running")
    elif pod:
        say(f"== starting pod {pod['id']}")
        api.start_pod(pod["id"])
    else:
        body = {
            "name": name_for(kind), "imageName": spec["image"], "gpuTypeIds": list(spec["gpus"]), "gpuCount": 1,
            "cloudType": "SECURE", "containerDiskInGb": int(spec.get("container_disk_gb", 30)),
            "networkVolumeId": volume["id"], "volumeMountPath": "/workspace",
            "dataCenterIds": [volume["dataCenterId"]],
            "ports": ["8188/http", "22/tcp", "8888/http"],
            "env": {"PUBLIC_KEY": ssh_public_key()} if ssh_public_key() else {},
        }
        say(f"== creating pod {name_for(kind)} ({', '.join(spec['gpus'])} in {volume['dataCenterId']})")
        try:
            pod = api.create_pod(body)
        except RuntimeError as e:
            raise SystemExit(f"{e}\n\nNo luck in {volume['dataCenterId']}? RunPod may have none of those GPUs free "
                             "there right now -- try again later, or add GPU types to pods.yaml.")
    return pod


def ready(api: RunPod, settings: dict, kind: str, pod: dict, wait_minutes: float = WAIT_MINUTES) -> dict:
    """Wait for the pod's ComfyUI, fix what's missing, make it the app's default."""
    url = comfyui_url(settings, pod["id"])
    say(f"== waiting for ComfyUI at {url} (the first start copies ComfyUI onto the volume) ", end="")
    if not wait_for_comfyui(url, wait_minutes):
        raise SystemExit(f"ComfyUI didn't answer within {wait_minutes} min. The pod's logs are in the RunPod console.")

    result = check(kind, url)
    for attempt in range(2):
        if result.get("ok"):
            break
        say("== not ready yet: " + describe(result))
        code = run_setup_over_ssh(api.pod(pod["id"]), kind)
        if code is None:
            say("\nNo SSH (no ~/.ssh/*.pub key, or the pod has no public SSH port). Finish it by hand: open the pod's\n"
                "web terminal (RunPod console -> the pod -> Connect) and run, from a clone of this repo:\n"
                f"    COMFYUI_UPDATE=1 bash city_simulator/deploy/runpod-comfyui/setup.sh {kind}\n"
                "restart the pod if it says so, then run `pods.py up` again.")
            raise SystemExit(1)
        if code == 3:                                  # ComfyUI was updated: restart it
            say("== restarting the pod to load the updated ComfyUI ", end="")
            api.restart_pod(pod["id"])
            time.sleep(15)
            if not wait_for_comfyui(url, wait_minutes):
                raise SystemExit("ComfyUI didn't come back after the restart -- check the pod's logs.")
        elif code != 0:
            raise SystemExit(f"setup.sh failed on the pod (exit {code}).")
        result = check(kind, url)
    if not result.get("ok"):
        raise SystemExit("Still not ready: " + describe(result))

    say(f"== ready: {describe(result)}")
    say(f"   {url}")
    set_app_default(kind, url)
    pod = api.pod(pod["id"])
    if pod.get("costPerHr"):
        say(f"   costs ${pod['costPerHr']}/hr while it runs -- `pods.py down {kind}` when you're done.")
    return pod


def down(api: RunPod, kind: str, volume: bool = False, yes: bool = False):
    pod = find_pod(api, kind)
    if pod:
        api.delete_pod(pod["id"])
        say(f"deleted the {kind} pod ({pod['id']})")
    else:
        say(f"no {kind} pod running")
    if volume:
        vol = find_volume(api, kind)
        if vol is None:
            say(f"no {kind} network volume")
        elif not yes and input(f"Delete network volume {vol['name']} ({vol.get('size')} GB) and everything on it -- "
                               "ComfyUI and the models? [y/N] ").strip().lower() != "y":
            say("kept the volume")
        else:
            api.delete_volume(vol["id"])
            say(f"deleted network volume {vol['name']}")
    elif find_volume(api, kind):
        say(f"  (its network volume {name_for(kind)} is kept -- `--volume` deletes it too)")


def status(api: RunPod, settings: dict):
    pods = {p.get("name"): p for p in api.pods() if p.get("desiredStatus") != "TERMINATED"}
    volumes = {v.get("name"): v for v in api.volumes()}
    for kind in KINDS:
        pod, vol = pods.get(name_for(kind)), volumes.get(name_for(kind))
        say(f"{kind}:")
        if pod:
            url = comfyui_url(settings, pod["id"])
            try:
                up_now = requests.get(f"{url}/system_stats", timeout=8).status_code == 200
            except requests.RequestException:
                up_now = False
            gpu = (pod.get("gpu") or {}).get("displayName") or (pod.get("machine") or {}).get("gpuTypeId") or ""
            say(f"  pod {pod['id']}  {pod.get('desiredStatus')}  {gpu}  ${pod.get('costPerHr', '?')}/hr")
            say(f"  {url}  ComfyUI {'up' if up_now else 'not answering'}")
        else:
            say("  no pod")
        say(f"  volume: {vol['name']} ({vol.get('size')} GB, {vol.get('dataCenterId')})" if vol else "  no volume")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create and delete the RunPod pods that run ComfyUI for the app.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_up = sub.add_parser("up", help="create (or reuse) pods, wait until ComfyUI is ready, make them the app's defaults")
    p_up.add_argument("kind", nargs="?", default="all", choices=KINDS + ("all",),
                      help="image, video, or all (the default)")
    p_down = sub.add_parser("down", help="delete a pod (its network volume is kept unless --volume)")
    p_down.add_argument("kind", choices=KINDS + ("all",))
    p_down.add_argument("--volume", action="store_true", help="also delete its network volume (ComfyUI + models)")
    p_down.add_argument("--yes", action="store_true", help="don't ask before deleting a volume")
    sub.add_parser("status", help="the pods and volumes, cost per hour, and whether ComfyUI answers")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(APP / ".env")
    api = RunPod(os.environ.get("RUNPOD_API_KEY", ""))
    settings = load_settings()
    if args.command == "up":
        if args.kind == "all":
            results = up_many(api, settings, KINDS)
            if not all(isinstance(r, dict) for r in results.values()):
                raise SystemExit(1)
        else:
            up(api, settings, args.kind)
    elif args.command == "down":
        for kind in (KINDS if args.kind == "all" else (args.kind,)):
            down(api, kind, volume=args.volume, yes=args.yes)
    else:
        status(api, settings)


if __name__ == "__main__":
    main()
