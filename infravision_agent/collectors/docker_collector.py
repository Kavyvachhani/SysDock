"""
Docker collector: containers (with live stats), images, volumes.
Method 1: docker-py SDK.
Method 2: docker CLI (json format).
Fails silently when Docker is not installed.
Python 3.6+. All Linux distributions.

Accuracy notes:
- CPU %: (cpu_delta / sys_delta) * ncpus * 100 — matches `docker stats`
- Memory %: use `inactive_file` (cgroups v2) or `cache` (cgroups v1) to
  subtract the page cache from usage, matching `docker stats` output.
"""
from __future__ import annotations

import json as _json
import subprocess
import re
from datetime import datetime


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except FileNotFoundError:
        return "", 127
    except Exception:
        return "", -1


def _parse_docker_df():
    """
    Run `docker system df` and return structured sizes.
    Returns dict: {images_size, containers_size, volumes_size, build_cache_size} or {}.
    """
    out, rc = _run(["docker", "system", "df"], timeout=10)
    if rc != 0 or not out:
        return {}
    result = {}
    for line in out.splitlines():
        low = line.lower()
        # Match lines like: "Images   5   5   2.3GB   0B (0%)"
        # Extract the RECLAIMABLE column (4th field) as 'size'
        parts = line.split()
        if len(parts) < 4:
            continue
        # Size is 3rd column (index 3) for docker system df
        size_val = parts[3] if len(parts) > 3 else parts[-1]
        if "image" in low:
            result["images_size"] = size_val
        elif "container" in low:
            result["containers_size"] = size_val
        elif "volume" in low:
            result["volumes_size"] = size_val
        elif "build" in low:
            result["build_cache_size"] = size_val
    return result


def _docker_reachable():
    _, rc = _run(["docker", "info"], timeout=5)
    return rc == 0


def _get_sdk_client():
    try:
        import docker
        return docker.from_env(timeout=10)
    except Exception:
        return None


# ── Stats parsing ────────────────────────────────────────────────────────────

def _parse_stats(raw):
    """
    Parses a raw stats dict from the Docker API into friendly numbers.
    Matches docker stats CLI output exactly.
    """
    try:
        cpu_delta = (raw["cpu_stats"]["cpu_usage"]["total_usage"]
                   - raw["precpu_stats"]["cpu_usage"]["total_usage"])
        sys_delta = (raw["cpu_stats"].get("system_cpu_usage", 0)
                   - raw["precpu_stats"].get("system_cpu_usage", 0))
        ncpu = (raw["cpu_stats"].get("online_cpus")
                or len(raw["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])))
        cpu_pct = (cpu_delta / sys_delta) * ncpu * 100.0 if sys_delta > 0 else 0.0

        mem = raw.get("memory_stats", {})
        mem_usage = mem.get("usage", 0)
        limit     = mem.get("limit", 1)

        # Subtract page cache to get actual RSS — matches docker stats output.
        # cgroups v1: stats.cache
        # cgroups v2: stats.inactive_file (more accurate)
        stats_block = mem.get("stats", {})
        cache = stats_block.get("inactive_file",
                stats_block.get("cache", 0))
        used  = max(0, mem_usage - cache)

        mem_pct = (used / limit * 100.0) if limit else 0.0

        net_rx = net_tx = 0
        for nd in (raw.get("networks") or {}).values():
            net_rx += nd.get("rx_bytes", 0)
            net_tx += nd.get("tx_bytes", 0)

        blk_r = blk_w = 0
        for e in (raw.get("blkio_stats", {}).get("io_service_bytes_recursive") or []):
            op = (e.get("op") or "").lower()
            if op == "read":  blk_r += e.get("value", 0)
            if op == "write": blk_w += e.get("value", 0)

        return {
            "cpu_pct":      round(cpu_pct,  2),
            "mem_used_mb":  round(used  / 1024 ** 2, 1),
            "mem_limit_mb": round(limit / 1024 ** 2, 1),
            "mem_pct":      round(mem_pct,  2),
            "net_rx_mb":    round(net_rx    / 1024 ** 2, 2),
            "net_tx_mb":    round(net_tx    / 1024 ** 2, 2),
            "blk_read_mb":  round(blk_r     / 1024 ** 2, 2),
            "blk_write_mb": round(blk_w     / 1024 ** 2, 2),
            "pids":         raw.get("pids_stats", {}).get("current", 0),
        }
    except Exception as e:
        return {"error": str(e), "cpu_pct": 0.0, "mem_pct": 0.0,
                "mem_used_mb": 0.0, "mem_limit_mb": 0.0}


# ── SDK path ─────────────────────────────────────────────────────────────────

def _collect_sdk(client):
    try:
        info = client.info()
        ver  = client.version()
    except Exception as e:
        return {"available": True, "error": str(e), "containers": [], "images": [], "volumes": []}

    version_info = {
        "version":            ver.get("Version"),
        "api_version":        ver.get("ApiVersion"),
        "total_containers":   info.get("Containers"),
        "running_containers": info.get("ContainersRunning"),
        "stopped_containers": info.get("ContainersStopped"),
        "total_images":       info.get("Images"),
        "storage_driver":     info.get("Driver"),
    }

    containers = []
    try:
        for c in client.containers.list(all=True):
            attrs  = c.attrs
            state  = attrs.get("State", {})
            status = state.get("Status", "unknown")  # "running", "exited", "paused"
            entry  = {
                "id":            c.short_id,
                "name":          c.name,
                "image":         attrs.get("Config", {}).get("Image", "?"),
                "status":        status,
                "state":         status,  # normalized: running / exited / paused
                "created":       attrs.get("Created", "")[:19],
                "restart_count": attrs.get("RestartCount", 0),
                "ports":         {},
                "stats":         None,
            }
            # Port bindings
            for cp, hbs in (attrs.get("HostConfig", {}).get("PortBindings") or {}).items():
                if hbs:
                    entry["ports"][cp] = [b.get("HostPort") for b in hbs]
            # Live stats for running containers
            if status == "running":
                try:
                    entry["stats"] = _parse_stats(c.stats(stream=False))
                except Exception as e:
                    entry["stats"] = {"error": str(e), "cpu_pct": 0.0, "mem_pct": 0.0}
            containers.append(entry)
    except Exception:
        pass

    images = []
    try:
        for img in client.images.list():
            tags = img.tags or ["<none>:<none>"]
            images.append({
                "id":      img.short_id,
                "tags":    tags,
                "size_mb": round(img.attrs.get("Size", 0) / 1024 ** 2, 1),
                "created": img.attrs.get("Created", "")[:19],
            })
    except Exception:
        pass

    volumes = []
    try:
        for v in client.volumes.list():
            volumes.append({
                "name":       v.name,
                "driver":     v.attrs.get("Driver"),
                "mountpoint": v.attrs.get("Mountpoint"),
            })
    except Exception:
        pass

    df_disk = _parse_docker_df()
    version_info["disk_usage"] = df_disk

    return {
        "available":  True,
        "via":        "sdk",
        "version":    version_info,
        "containers": sorted(containers, key=lambda x: x.get("name", "")),
        "images":     images,
        "volumes":    volumes,
    }


# ── CLI path ─────────────────────────────────────────────────────────────────

def _collect_cli():
    # List all containers
    fmt = ('{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}",'
           '"status":"{{.Status}}","state":"{{.State}}"}')
    out, rc = _run(["docker", "ps", "-a", "--format", fmt])
    containers = []
    if rc == 0:
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                c = _json.loads(line)
                # Ensure "state" field is clean (running/exited/paused)
                if "state" not in c:
                    c["state"] = "unknown"
                containers.append(c)
            except Exception:
                pass

    # Live stats (no-stream) for running containers
    stats_fmt = ('{"name":"{{.Name}}","cpu":"{{.CPUPerc}}",'
                 '"mem":"{{.MemPerc}}","mem_usage":"{{.MemUsage}}",'
                 '"net_io":"{{.NetIO}}","pids":"{{.PIDs}}"}')
    out_s, rc_s = _run(["docker", "stats", "--no-stream", "--format", stats_fmt], timeout=20)
    stats_map = {}
    if rc_s == 0:
        for line in out_s.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                s = _json.loads(line)
                name = s.get("name", "")
                # Strip leading slash that docker sometimes adds
                if name.startswith("/"):
                    name = name[1:]
                cpu_str = s.get("cpu", "0%").replace("%", "").strip() or "0"
                mem_str = s.get("mem", "0%").replace("%", "").strip() or "0"
                try:
                    cpu_val = float(cpu_str)
                except ValueError:
                    cpu_val = 0.0
                try:
                    mem_val = float(mem_str)
                except ValueError:
                    mem_val = 0.0
                # Parse "10MiB / 1GiB" into float megabytes
                mem_usage_str = s.get("mem_usage", "")
                mem_used_mb = 0.0
                try:
                    first_part = mem_usage_str.split("/")[0].strip()
                    if "GiB" in first_part:
                        mem_used_mb = float(first_part.replace("GiB", "").strip()) * 1024
                    elif "MiB" in first_part:
                        mem_used_mb = float(first_part.replace("MiB", "").strip())
                    elif "KiB" in first_part:
                        mem_used_mb = float(first_part.replace("KiB", "").strip()) / 1024
                    elif "B" in first_part:
                        mem_used_mb = float(first_part.replace("B", "").strip()) / (1024**2)
                except Exception:
                    pass

                stats_map[name] = {
                    "cpu_pct":     cpu_val,
                    "mem_pct":     mem_val,
                    "mem_usage":   mem_usage_str,
                    "mem_used_mb": mem_used_mb,
                    "net_io":      s.get("net_io", ""),
                    "pids":        s.get("pids", ""),
                }
            except Exception:
                pass

    for c in containers:
        cname = c.get("name", "")
        if cname.startswith("/"):
            cname = cname[1:]
        c["stats"] = stats_map.get(cname) or stats_map.get(c.get("name", ""))

    # Images
    img_fmt = ('{"id":"{{.ID}}","repository":"{{.Repository}}",'
               '"tag":"{{.Tag}}","size":"{{.Size}}","created":"{{.CreatedAt}}"}')
    out_i, rc_i = _run(["docker", "images", "--format", img_fmt])
    images = []
    if rc_i == 0:
        for line in out_i.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                img = _json.loads(line)
                repo = img.get("repository", "<none>")
                tag  = img.get("tag", "<none>")
                images.append({
                    "id":      img.get("id", "")[:12],
                    "tags":    ["{repo}:{tag}".format(repo=repo, tag=tag)],
                    "size_mb": 0,       # CLI doesn't give bytes easily
                    "size":    img.get("size", "?"),
                    "created": img.get("created", "")[:19],
                })
            except Exception:
                pass

    # Version info
    ver_fmt = '{"server":"{{.Server.Version}}","api":"{{.Server.APIVersion}}"}'
    out_v, _ = _run(["docker", "version", "--format", ver_fmt])
    version_info = {}
    try:
        version_info = _json.loads(out_v)
    except Exception:
        pass

    # Add image/container counts to version_info
    version_info["total_containers"]   = len(containers)
    version_info["running_containers"] = sum(1 for c in containers if c.get("state") == "running")
    version_info["total_images"]       = len(images)

    df_disk = _parse_docker_df()
    version_info["disk_usage"] = df_disk

    return {
        "available":  True,
        "via":        "cli",
        "version":    version_info,
        "containers": containers,
        "images":     images,
        "volumes":    [],
    }


# ── Collect ───────────────────────────────────────────────────────────────────

def collect_all():
    if not _docker_reachable():
        return {
            "available":    False,
            "error":        "Docker daemon not reachable or not installed",
            "containers":   [],
            "images":       [],
            "collected_at": datetime.utcnow().isoformat() + "Z",
        }

    client = _get_sdk_client()
    if client:
        result = _collect_sdk(client)
    else:
        result = _collect_cli()

    result["collected_at"] = datetime.utcnow().isoformat() + "Z"
    return result
