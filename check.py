#!/usr/bin/env python3
import os
from datetime import datetime
import sys
import re

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
    # 使用 ps aux | grep scratch/remote 检查所有相关进程
    processes = os.popen("ps aux | grep scratch/remote | grep -v grep").read().strip().split('\n')
    for process in processes:
        if 'python2' in process or 'grep' in process or process == '':
            continue
        pid = process.split()[1]
        experiment_name = process.split()[-1]
        print(f"Process ID: {pid}, Experiment Name: {experiment_name}")

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
    processes = os.popen("ps aux | grep scratch/remote | grep -v grep").read().strip().split('\n')
    for process in processes:
        if 'python2' in process or 'grep' in process:
            continue
        pid = process.split()[1]
        experiment_name = process.split()[-1]
        if any(f'[{id}]' in experiment_name for id in ids):
            print(f"Process ID: {pid}, Experiment Name: {experiment_name}")
            os.system(f"kill -9 {pid}")

if __name__ == "__main__":
    command = sys.argv[1]
    if command == 'state':
        if len(sys.argv) == 3:
            check_folders_for_log(int(sys.argv[2]))
        else:
            check_folders_for_log()
    elif command == 'kill':
        kill_process_by_id(sys.argv[2])
