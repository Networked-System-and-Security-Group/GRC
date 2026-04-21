#!/usr/bin/env python3
import os
from datetime import datetime
import sys
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class RemoteProcess:
    pid: int
    command: str
    config_path: Optional[str]
    elapsed_s: int = 0


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


_EXPERIMENT_ID_RE = re.compile(r"\[(\d+)\]")


def _extract_experiment_id(text: str) -> Optional[int]:
    m = _EXPERIMENT_ID_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _is_finished_folder(folder: str) -> bool:
    config_log_path = os.path.join(folder, "config.log")
    if not os.path.exists(config_log_path):
        return False
    try:
        with open(config_log_path, "r") as log_file:
            return "Simulator is enforced to be finished" in log_file.read()
    except OSError:
        return False


def _list_remote_processes_for_this_repo() -> list[RemoteProcess]:
    repo = _repo_root()
    # Use -eo pid,etimes,args to get PID, elapsed seconds, and full command.
    # -ww ensures no truncation.
    ps = subprocess.run(["ps", "-ww", "-eo", "pid,etimes,args"], capture_output=True, text=True, check=False)
    lines = ps.stdout.splitlines()

    procs: list[RemoteProcess] = []
    for line in lines:
        if "scratch/remote" not in line:
            continue
        if "waf" in line:
            continue
        if " grep " in f" {line} ":
            continue
        
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue

        try:
            pid = int(parts[0])
            elapsed_s = int(parts[1])
            command = parts[2]
        except ValueError:
            continue

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

        procs.append(RemoteProcess(pid=pid, command=command, config_path=config_path, elapsed_s=elapsed_s))

    return procs


def monitor(interval_s: float = 2.0, kill_hours: Optional[float] = None):
    unfinished: set[int] = set()
    finished: set[int] = set()
    killed: set[int] = set()
    last_pid_by_id: dict[int, int] = {}
    folder_by_id: dict[int, str] = {}

    report_interval_s = 15 * 60
    last_report_ts = time.monotonic() - report_interval_s  # force initial report
    seen_any_experiment = False

    msg = "Monitoring scratch/remote experiments for this repo... (Ctrl-C to stop)\n"
    msg += f"Polling interval: {interval_s}s"
    if kill_hours is not None:
        msg += f", Auto-kill after: {kill_hours} hours"
    print(msg)

    def _print_status(*, running_ids: set[int]):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "=" * 72)
        print(now)
        print(f"Running:  {sorted(running_ids)}")
        print(f"Finished: {sorted(finished)}")
        if killed:
            print(f"Killed:   {sorted(killed)}")
        print(
            f"Totals: running={len(running_ids)} unfinished={len(unfinished)} finished={len(finished)} killed={len(killed)}"
        )

    try:
        while True:
            prev_unfinished = set(unfinished)
            prev_finished = set(finished)
            prev_killed = set(killed)

            procs = _list_remote_processes_for_this_repo()
            running_ids: set[int] = set()

            for proc in procs:
                text = proc.config_path or proc.command
                exp_id = _extract_experiment_id(text)
                if exp_id is None:
                    continue

                seen_any_experiment = True

                # Record folder path early if available (useful even if auto-killed)
                if proc.config_path is not None:
                    abs_cfg = _abs_from_repo(proc.config_path)
                    folder_by_id[exp_id] = os.path.dirname(abs_cfg)

                # Check for timeout kill
                if kill_hours is not None and proc.elapsed_s > kill_hours * 3600:
                    print(
                        f"\n[Auto-kill] PID {proc.pid} exp[{exp_id}] elapsed {proc.elapsed_s/3600:.2f}h > {kill_hours}h. Killing..."
                    )
                    try:
                        os.kill(proc.pid, 9)
                        killed.add(exp_id)
                        unfinished.discard(exp_id)
                    except OSError as e:
                        print(f"Failed to kill {proc.pid}: {e}")
                    continue  # Process is killed, don't count it as running

                running_ids.add(exp_id)
                last_pid_by_id[exp_id] = proc.pid

            # On startup: include all currently-running experiments; afterwards, keep adding new ones.
            for exp_id in running_ids:
                if exp_id not in finished and exp_id not in killed:
                    unfinished.add(exp_id)

            # Promote finished experiments based on config.log.
            for exp_id in list(unfinished):
                folder = folder_by_id.get(exp_id)
                if folder and _is_finished_folder(folder):
                    unfinished.discard(exp_id)
                    finished.add(exp_id)

            new_unfinished = sorted(unfinished - prev_unfinished)
            new_finished = sorted(finished - prev_finished)
            new_killed = sorted(killed - prev_killed)
            should_report = (time.monotonic() - last_report_ts) >= report_interval_s

            if new_unfinished or new_finished or new_killed or should_report:
                _print_status(running_ids=running_ids)
                last_report_ts = time.monotonic()

            # Auto-exit: once we've observed at least one experiment and all observed experiments are done.
            if seen_any_experiment and not unfinished and not running_ids:
                print("\nAll experiments completed (or killed). Exiting monitor.")
                break

            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\nStopped monitoring.")

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
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python3 check.py state [N]\n"
            "  python3 check.py kill <ids>\n"
            "  python3 check.py monitor [kill_hours] [interval_seconds]"
        )
        raise SystemExit(2)

    command = sys.argv[1]
    if command == 'state':
        if len(sys.argv) == 3:
            check_folders_for_log(int(sys.argv[2]))
        else:
            check_folders_for_log()
    elif command == 'kill':
        kill_process_by_id(sys.argv[2])
    elif command == 'monitor':
        kill_hours = None
        interval_s = 2.0
        
        if len(sys.argv) >= 3:
            val = float(sys.argv[2])
            if val > 0:
                kill_hours = val
        
        if len(sys.argv) >= 4:
            interval_s = float(sys.argv[3])
            
        monitor(interval_s=interval_s, kill_hours=kill_hours)
