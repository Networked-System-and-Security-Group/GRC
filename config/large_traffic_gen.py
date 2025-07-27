import json
import math
import os
import random
import os.path as op
import argparse
from pathlib import Path
import matplotlib.pyplot as plt


class Flow:
    def __init__(self, src, dst, size, t):
        self.src = src
        self.dst = dst
        self.size = size
        self.t = t
    def __str__(self):
        return f"{self.src} {self.dst} 3 {self.size} {self.t:.9f}"

class CustomRand:
    def __init__(self, cdf_file_name: str):
        self.cdf = []
        with open(cdf_file_name, 'r') as f:
            for line in f:
                x, y = map(float, line.strip().split())
                self.cdf.append([x, y])
        assert self.cdf[0][1] == 0 and self.cdf[-1][1] == 100
        for i in range(1, len(self.cdf)):
            assert self.cdf[i][1] > self.cdf[i - 1][1] or self.cdf[i][0] > self.cdf[i - 1][0]

    def get_avg(self):
        s = 0
        last_x, last_y = self.cdf[0]
        for x, y in self.cdf[1:]:
            s += (x + last_x) / 2.0 * (y - last_y)
            last_x, last_y = x, y
        return s / 100

    def rand(self):
        return self.get_value_from_percentile(random.uniform(0, 100))

    def get_value_from_percentile(self, percentile):
        for i in range(1, len(self.cdf)):
            if percentile <= self.cdf[i][1]:
                x0, y0 = self.cdf[i - 1]
                x1, y1 = self.cdf[i]
                return x0 + (x1 - x0) / (y1 - y0) * (percentile - y0)

def translate_bandwidth(bw_str):
    if not isinstance(bw_str, str) or len(bw_str) < 2:
        raise ValueError(f"Invalid bandwidth string: {bw_str}")
    units = {'G': 1e9, 'M': 1e6, 'K': 1e3}
    return float(bw_str[:-1]) * units.get(bw_str[-1], 1)

def poisson(lam):
    return int(-math.log(1 - random.random()) * lam)

def generate_intra_as_flows(hosts, cdf_file, bandwidth, load, duration, base_time=2_000_000_000):
    custom_rand = CustomRand(cdf_file)
    flows = []
    avg_size = custom_rand.get_avg()
    avg_interval = 1 / (bandwidth * load / 8 / avg_size) * 1e9

    for src in hosts:
        current_time = base_time + poisson(avg_interval)
        while current_time < base_time + duration:
            dst = random.choice([h for h in hosts if h != src])
            flows.append(Flow(src, dst, int(custom_rand.rand()), current_time * 1e-9))
            current_time += poisson(avg_interval)

    flows.sort(key=lambda f: f.t)
    return flows

def generate_flows(src_hosts, dst_hosts, cdf_file, host_rate, duration, base_time=2.0, restrict=True):
    '''
    Generate flows between src_hosts and dst_hosts based on a CDF file and a specified send rate.
    Args:
        src_hosts (list[int]): List of source hosts.
        dst_hosts (list[int]): List of destination hosts.
        cdf_file (str): Path to the CDF file containing flow size distribution.
        host_rate (str): Desired send rate in Gbps (e.g., '10G', '100M').
        duration (float): Duration for which the flows should be generated, in seconds.
        base_time (float): Base time in seconds from which to start generating flows.
        restrict (bool): If True, restricts the generated flows to be within 10%
    '''
    custom_rand = CustomRand(cdf_file)
    flows = []
    avg_size = custom_rand.get_avg()
    rate_per_host = translate_bandwidth(host_rate)
    avg_interval = 1 / (rate_per_host / 8 / avg_size)

    for src in src_hosts:
        current_time = base_time + poisson(avg_interval*1e9)/1e9
        while current_time < base_time + duration:
            dst = random.choice([h for h in dst_hosts if h != src])
            flows.append(Flow(src, dst, int(custom_rand.rand()), current_time))
            current_time += poisson(avg_interval*1e9)/1e9


    flows.sort(key=lambda f: f.t)
    actual_rate = sum([f.size for f in flows]) / duration * 8
    target_rate = rate_per_host * len(src_hosts)
    if 0.9 * target_rate <= actual_rate <= 1.1 * target_rate or not restrict:
        print(f'{src_hosts} -> {dst_hosts}')
        print(f'time: {base_time}-{base_time+duration}, avg_interval: {avg_interval*1000:.3f}ms, avg_size: {avg_size}, rate_per_host: {rate_per_host/1e9:.3f}G')
        print(f'Actual Rate: {actual_rate/1e9:.3f} Gbps, Target Rate: {target_rate/1e9:.3f} Gbps')
        return flows
    else:
        return generate_flows(src_hosts, dst_hosts, cdf_file, host_rate, duration, base_time, restrict=True)

def generate_dynamic_flows(as_list, cdf_file, total_rate, duration, 
                           slice_duration=0.02, slice_rate='100G', base_time=2.0):
    '''
    Generate flows between all pairs of ASes based on a CDF file and a specified send rate.
    Args:
        as_list (list[list[int]]): List of ASes, each containing a list of hosts.
        cdf_file (str): Path to the CDF file containing flow size distribution.
        send_rate (str): Desired send rate in Gbps (e.g., '10G', '100M').
        duration (float): Duration for which the flows should be generated, in seconds.
        slice_duration (float): Duration of each slice in seconds.
        slice_bw (str): Bandwidth for each slice in Gbps (e.g., '50G').
        base_time (float): Base time in seconds from which to start generating flows.
    '''
    flows = []
    total_rate_f = translate_bandwidth(total_rate)
    slice_rate_f = translate_bandwidth(slice_rate)
    slice_count = int((total_rate_f * duration) / (slice_rate_f * slice_duration))
    avg_interval = duration / slice_count

    for src_as in as_list:
        cur_time = base_time + poisson(avg_interval * 1e9) / 1e9
        while cur_time < base_time + duration:
            dst_as = random.choice([as_item for as_item in as_list if as_item != src_as])
            print(f'Generating flows for AS {src_as} -> AS {dst_as} at slice {cur_time:.3f}-{cur_time + slice_duration:.3f}s')
            flows += generate_flows(src_as, dst_as, cdf_file, f'{slice_rate_f/len(src_as)/1e9}G', slice_duration , cur_time, restrict=False)
            cur_time += poisson(avg_interval * 1e9) / 1e9

    return flows


def plot_concurrent_flows(flows: list[Flow], bw: float, output_filename: str = "concurrent_flows.png"):
    """
    计算并绘制并发流数量随时间变化的折线图。

    参数:
    - flows (List[Flow]): 一个包含Flow对象的列表。
    - bw (float): 链路带宽。
    - output_filename (str): 输出图像的文件名。
    """
    if not flows:
        print("流列表为空，无法生成图像。")
        return

    # 1. 根据流的大小和带宽计算持续时间，并创建事件列表
    #    (time, +1) 表示流开始
    #    (time, -1) 表示流结束
    flows = list(flows)
    print(f"Calculating concurrent flows for {len(flows)} flows with bandwidth {bw/1e9:.2f} GB/s")
    events = []
    for flow in flows:
        duration = flow.size / bw
        events.append((flow.t, 1))
        events.append((flow.t + duration, -1))

    # 2. 按时间对事件进行排序
    events.sort()

    # 3. 计算每个时间点的并发流数量
    time_points = [0]
    flow_counts = [0]
    current_flows = 0
    
    # 遍历排序后的事件来构建时间点和流计数的列表
    for t, event_type in events:
        # 如果当前事件的时间点与上一个不同，则添加一个点以保持上一个状态
        if t > time_points[-1]:
            time_points.append(t)
            flow_counts.append(current_flows)

        # 更新流计数
        current_flows += event_type
        
        # 更新当前时间点的流计数值
        if t == time_points[-1]:
            flow_counts[-1] = current_flows
        else:
            # 这个分支理论上在上面的if条件下不会被执行，但为保险起见保留
            time_points.append(t)
            flow_counts.append(current_flows)

    # 4. 绘图
    plt.figure(figsize=(10, 6))
    # 使用 'post' 方式绘制阶梯图，表示值在每个时间点之后保持不变
    plt.step(time_points, flow_counts, where='post')
    
    plt.xlabel("time (t)")
    plt.ylabel("concurrent flows")
    plt.grid(True)
    
    # 设置刻度为整数
    max_flows = max(flow_counts) if flow_counts else 0
    max_time = time_points[-1] if time_points else 1
    #plt.xticks(range(0, int(max_time) + 2))
    plt.yticks(range(0, int(max_flows) + 2))
    plt.xlim(2, 2.1)

    # 保存图像
    plt.savefig(output_filename)
    plt.close() # 关闭图形，释放内存

    print(f"绘图已保存为 {output_filename}")

if __name__ == '__main__':
    # 添加命令行参数解析
    parser = argparse.ArgumentParser(description='生成网络流量并绘制并发流图')
    # 添加background_inter_load参数（默认值150）
    parser.add_argument('-b','--background-inter-load', type=int, default=150,
                        help='background_inter_load的值（默认150）')
    # 添加dynamic_load参数（默认值200）
    parser.add_argument('-d','--dynamic-load', type=int, default=200,
                        help='dynamic_load的值（默认200）')
    # 添加流量集参数
    parser.add_argument('-f', '--flow_set', type=str, default='w')

    # 解析参数
    args = parser.parse_args()

    # 从命令行参数获取值（替代原有的硬编码）
    background_inter_load = args.background_inter_load
    dynamic_load = args.dynamic_load
    flow_set = args.flow_set

    base_dir = op.join(op.dirname(__file__), '../traffic_gen')

    if flow_set == 'a':
        cdf_path = op.join(base_dir, 'AliStorage2019') + '.txt'
    else:
        cdf_path = op.join(base_dir, 'WebSearch') + '.txt'

    as_list:list[list[int]] = []
    with (Path(__file__).parent / 'cernet_topo.txt').open() as f:
        topo = json.load(f)
        for as_item in topo['as_topologies']:
            as_list.append(as_item['hosts'])

    per_host_inter_load = background_inter_load / 5 / 16 # 总的出速率是250Gbps,分给5个目标DC,再分给16个host
    intra_load = 100 * 0.3 # 每个网卡最高速率100GGbps,平均速率为0.3
    flows = []
    # 生成DC内背景流和WAN间的背景流
    for as1 in as_list:
        for as2 in as_list:
            if as1 == as2:
                flows += generate_flows(as1, as2, cdf_path, f'{intra_load}G', 0.1)
            else:
                flows += generate_flows(as1, as2, cdf_path, f'{per_host_inter_load}G', 0.1)

    if dynamic_load > 0:
        flows += generate_dynamic_flows(as_list, cdf_path, f'{dynamic_load}G', 0.1, slice_duration=0.03, slice_rate='100G')

    
    flows.sort(key=lambda x : x.t)

    #plot_concurrent_flows(filter(lambda f: f.dst in as_list[1], flows), 400 * 1e9 / 8, 
    #                      output_filename=f'concurrent_flows{"_d" if dynamic_load > 0 else ""}.png')
    # 输出到文件
    saved_path = op.join(op.dirname(__file__), f'{flow_set}-dynamic-{int(background_inter_load)}-{int(dynamic_load)}.txt')
    print(f'Flow count: {len(flows)}, Saved to: {saved_path}')
    with open(saved_path, 'w') as ofile:
        ofile.write(f"{len(flows)}\n")
        for f in flows:
            ofile.write(str(f) + '\n')
