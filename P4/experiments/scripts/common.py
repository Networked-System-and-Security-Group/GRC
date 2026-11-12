#!/usr/bin/env python3
"""Local testbed configuration and SSH helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from ipaddress import IPv4Address
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
P4_DIR = REPO_ROOT / "p4"
CTRL_DIR = REPO_ROOT / "ctrl"
RESULTS_DIR = REPO_ROOT / "results"
ROLES = ("client", "server")


@lru_cache(maxsize=1)
def testbed():
    path = REPO_ROOT / "testbed.local.json"
    if not path.is_file():
        raise SystemExit("Copy testbed.example.json to testbed.local.json and fill in your testbed.")
    return validate_testbed(json.loads(path.read_text()))


def validate_testbed(cfg):
    for field in ("switch_ssh", "traffic_ssh"):
        if not re.fullmatch(r"(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9_][a-zA-Z0-9_.-]*", cfg[field]):
            raise ValueError(f"{field} must be an SSH host alias or user@host")
    for field in ("switch_work", "traffic_work", "sde", "sde_install", "switchd_conf", "bfrt_python"):
        value = cfg[field]
        if not re.fullmatch(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value) or ".." in value.split("/"):
            raise ValueError(f"{field} must be an absolute remote path without spaces or '..'")
    if not isinstance(cfg["bfrt_pythonpath"], list) or any(
        not re.fullmatch(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", part)
        for part in cfg["bfrt_pythonpath"]
    ):
        raise ValueError("bfrt_pythonpath must be a list of absolute SDK module paths")
    endpoints = cfg["endpoints"]
    if set(endpoints) != set(ROLES):
        raise ValueError("Expected exactly the client and server endpoints")
    for role in ROLES:
        endpoint = endpoints[role]
        for name in ("device", "interface"):
            if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", endpoint[name]):
                raise ValueError(f"Invalid {role} {name}")
        if not isinstance(endpoint["ip"], str):
            raise ValueError(f"Invalid {role} IPv4 address")
        IPv4Address(endpoint["ip"])
        port = endpoint["switch_port"]
        if type(port) is not int or not 0 <= port < 512:
            raise ValueError(f"Invalid {role} Tofino2 device port")
    for key in ("device", "interface", "ip", "switch_port"):
        if endpoints["client"][key] == endpoints["server"][key]:
            raise ValueError(f"Client and server need different values for {key}")
    if endpoints["client"]["switch_port"] >> 7 != endpoints["server"]["switch_port"] >> 7:
        raise ValueError("Both experiment ports must belong to the same Tofino2 pipe")
    return cfg


def topology_header(endpoints):
    lines = []
    for role in ROLES:
        endpoint = endpoints[role]
        prefix = "GSCC_" + role.upper()
        lines.append(f"#define {prefix}_IPV4 32w0x{int(IPv4Address(endpoint['ip'])):08x}")
        lines.append(f"#define {prefix}_PORT 9w{endpoint['switch_port']}")
    return "\n".join(lines) + "\n"


SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "ConnectTimeout=10",
]

# ssh 每次都会打这两行，屏掉
_NOISE = ("post-quantum", "store now", "openssh.com/pq", "may need to be upgraded")


def _clean(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not any(n in ln for n in _NOISE)
    )


def run(cmd, timeout=120, check=True, cwd=None) -> str:
    """本机执行命令，返回 stdout（stderr 合并）。"""
    proc = subprocess.run(
        cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
        timeout=timeout, cwd=str(cwd) if cwd else None,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if check and proc.returncode != 0:
        raise RuntimeError(f"命令失败（rc={proc.returncode}）: {cmd}\n{out[-2000:]}")
    return out


def ssh(host: str, remote_cmd: str, timeout=180, check=True) -> str:
    """在远端执行命令，返回清洗后的输出。"""
    return _clean(run(["ssh", *SSH_OPTS, host, remote_cmd],
                      timeout=timeout, check=check))


def ssh_script(host: str, script: str, timeout=180, check=True) -> str:
    """在远端执行一段多行脚本（stdin 传给 bash），避免多层引号。"""
    proc = subprocess.run(
        ["ssh", *SSH_OPTS, host, "bash -s"],
        input=script, capture_output=True, text=True, timeout=timeout,
    )
    out = _clean((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
    if check and proc.returncode != 0:
        raise RuntimeError(f"远端脚本失败（rc={proc.returncode}）: {script[:400]}\n{out[-2000:]}")
    return out


def scp_to(local, remote: str, timeout=300) -> None:
    run(["scp", *SSH_OPTS, str(local), remote], timeout=timeout)


def scp_from(remote: str, local, timeout=300) -> None:
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    run(["scp", *SSH_OPTS, remote, str(local)], timeout=timeout)


# scp 在这套环境里偶尔对"远端父目录刚建好"的路径报 ENOENT，
# 所以文件传输统一走 ssh + cat（二进制安全，也不依赖 sftp）。
def push_file(host: str, local, remote_path: str, timeout=300) -> None:
    """把本地文件写到远端（自动建父目录）。"""
    import shlex
    data = Path(local).read_bytes()
    remote_dir = str(Path(remote_path).parent)
    proc = subprocess.run(
        ["ssh", *SSH_OPTS, host,
         f"mkdir -p {shlex.quote(remote_dir)} && cat > {shlex.quote(str(remote_path))}"],
        input=data, capture_output=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"推送失败 {local} -> {host}:{remote_path}\n"
                           f"{_clean(proc.stderr.decode('utf-8', 'replace'))[-800:]}")


def pull_file(host: str, remote_path: str, local, timeout=300) -> None:
    """从远端取文件到本地。"""
    import shlex
    proc = subprocess.run(
        ["ssh", *SSH_OPTS, host, f"cat {shlex.quote(remote_path)}"],
        capture_output=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"拉取失败 {host}:{remote_path}\n"
                           f"{_clean(proc.stderr.decode('utf-8', 'replace'))[-800:]}")
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(proc.stdout)


def emit(obj) -> None:
    """统一的机器可读输出：一行 JSON 到 stdout。"""
    print(json.dumps(obj, ensure_ascii=False, sort_keys=False))


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_matrix(path) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
