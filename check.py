#!/usr/bin/env python3
import os
from datetime import datetime
import sys
import re
import subprocess
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class RemoteProcess:
    pid: int
    command: str
    config_path: Optional[str]


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _abs_from_repo(path: str) -> str:
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(_repo_root(), path))


def _extract_config_path(command: str) -> Optional[str]:
    # Best-effort: scratch/remote is launched with a config.txt path argument.
    for token in command.split():
        if token.endswith("config.txt"):
            return token
    return None


def _list_remote_processes_for_this_repo() -> list[RemoteProcess]:
    repo = _repo_root()
    ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=False)
    lines = ps.stdout.splitlines()

    procs: list[RemoteProcess] = []
    for line in lines:
        if "scratch/remote" not in line:
            continue
        if " grep " in f" {line} ":
            continue
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue

        try:
            pid = int(parts[1])
        except ValueError:
            continue

        command = parts[10]
        config_path = _extract_config_path(command)

        # Filter by the current repo root.
        if config_path is not None:
            abs_cfg = _abs_from_repo(config_path)
            if not abs_cfg.startswith(repo + os.sep):
                continue
        else:
            # Fallback: if we can't find config.txt, at least ensure the command contains this repo path.
            if repo not in command:
                continue

        procs.append(RemoteProcess(pid=pid, command=command, config_path=config_path))

    return procs

def check_folders_for_log(n=5):
    # 获取当前目录下的所有子文件夹
    current_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), './mix/output')
    subfolders = [f.path for f in os.scandir(current_dir) if f.is_dir()]

    # 按照修改时间降序排序
    def get_id(path):
        match = re.search(r'\[(\d+)\]', path)
        if match:
            return int(match.group(1))
        else:
            return 0
    subfolders.sort(key=lambda x: get_id(x), reverse=True)

    latest_folders = subfolders[n-1::-1]

    # 检查每个子文件夹中的 config.log 文件
    for folder in latest_folders:
        config_log_path = os.path.join(folder, "config.log")
        if os.path.exists(config_log_path):
            # 检查文件内容是否包含指定字符串
            with open(config_log_path, "r") as log_file:
                log_content = log_file.read()
                if "Simulator is enforced to be finished" in log_content:
                    print(f"{os.path.basename(folder)}: \tFinished!")
                else:
                    print(f"{os.path.basename(folder)}: \tNot finished.\t{log_content.count('已导入') * 1000}")                    
        else:
            print(f"{os.path.basename(folder)}: \tconfig.log file not found.")

    # Only show scratch/remote processes belonging to THIS repo.
    for proc in _list_remote_processes_for_this_repo():
        experiment = proc.config_path or "(unknown config)"
        print(f"Process ID: {proc.pid}, Experiment: {experiment}")

def convert_str_to_id(config_ids_str: str) -> list[int]:
    ids = []
    for part in config_ids_str.split(','):
        if '-' in part:
            a, b = map(int, part.split('-'))
            ids.extend(range(a, b+1))
        else:
            ids.append(int(part))
    return ids

def kill_process_by_id(config_ids_str: str):
    ids = convert_str_to_id(config_ids_str)
    for proc in _list_remote_processes_for_this_repo():
        experiment_name = proc.config_path or proc.command
        if any(f'[{id}]' in experiment_name for id in ids):
            print(f"Killing PID: {proc.pid}, Experiment: {experiment_name}")
            os.kill(proc.pid, 9)

if __name__ == "__main__":
    command = sys.argv[1]
    if command == 'state':
        if len(sys.argv) == 3:
            check_folders_for_log(int(sys.argv[2]))
        else:
            check_folders_for_log()
    elif command == 'kill':
        kill_process_by_id(sys.argv[2])
