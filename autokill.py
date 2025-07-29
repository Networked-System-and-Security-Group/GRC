#!/usr/bin/env python3
from check import *
import re
import datetime
import time
import os
import sys

def write_pid_file():
    """写入PID文件，方便后续停止进程"""
    pid = os.getpid()
    with open('autokill.pid', 'w') as f:
        f.write(str(pid))
    print(f"PID文件已创建: autokill.pid (PID: {pid})")

def remove_pid_file():
    """删除PID文件"""
    if os.path.exists('autokill.pid'):
        os.remove('autokill.pid')
        print("PID文件已删除")

def autokill():
    processes = os.popen("ps aux | grep scratch/remote | grep -v grep").read().strip().split('\n')
    pattern = r'\[(\d+)\]-(\d+)-(\d+)-(\d+:\d+:\d+)'
    if len(processes) == 0:
        return
    
    for process in processes:
        if not process:  # 处理空行
            continue
        if 'python2' in process or 'grep' in process:
            continue
        match = re.search(pattern, process)
        if match:
            pid = match.group(1)
            month = match.group(2)
            day = match.group(3)
            time_str = match.group(4)
            year = datetime.datetime.now().year
            extracted_time_str = f"{year}-{month}-{day} {time_str}"
            try:
                extracted_datetime = datetime.datetime.strptime(
                    extracted_time_str, 
                    "%Y-%m-%d %H:%M:%S"
                )
                current_datetime = datetime.datetime.now()
                time_diff_seconds = abs((current_datetime - extracted_datetime).total_seconds())
                if time_diff_seconds >= 28800:  # 8小时（28800秒）
                    kill_process_by_id(pid)
                    print(f"已杀死进程 {pid}，运行时间超过8小时")
            except ValueError as e:
                print(f"时间格式解析错误: {e}")

def run_scheduled(interval_seconds):
    print(f"开始定时任务，间隔 {interval_seconds} 秒")
    try:
        # 写入PID文件
        write_pid_file()
        
        while True:
            autokill()
            # 等待指定时间后再次执行
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("定时任务已手动停止")
    finally:
        # 确保程序退出时删除PID文件
        remove_pid_file()

if __name__ == "__main__":
    # 设置执行间隔（单位：秒）
    check_interval = 600
    run_scheduled(check_interval)
