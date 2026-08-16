import json
import math
import os
import random
import os.path as op
import argparse
from pathlib import Path


def _lazy_import_matplotlib_pyplot():
    """Import matplotlib only when plotting is actually needed."""
    try:
        import matplotlib.pyplot as plt  # type: ignore
        return plt
    except Exception as e:
        raise RuntimeError(
            "matplotlib could not be imported (optional dependency). "
            f"Original error: {e}"
        ) from e


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

def generate_flows(src_hosts, dst_hosts, cdf_file, host_rate, duration, base_time=2.0, restrict=True):
    '''
    Generate flows between src_hosts and dst_hosts based on a CDF file and a specified send rate.
    '''
    custom_rand = CustomRand(cdf_file)
    flows = []
    avg_size = custom_rand.get_avg()
    rate_per_host = translate_bandwidth(host_rate)
    
    if rate_per_host <= 0:
        return []

    avg_interval = 1 / (rate_per_host / 8 / avg_size)

    for src in src_hosts:
        current_time = base_time + poisson(avg_interval*1e9)/1e9
        while current_time < base_time + duration:
            # Randomly choose a destination from the entire dst_hosts pool
            dst = random.choice([h for h in dst_hosts if h != src])
            flows.append(Flow(src, dst, max(1, int(custom_rand.rand())), current_time))
            current_time += poisson(avg_interval*1e9)/1e9

    flows.sort(key=lambda f: f.t)
    actual_rate = sum([f.size for f in flows]) / duration * 8
    target_rate = rate_per_host * len(src_hosts)
    
    # Relax restriction for very short bursts or small number of flows to avoid infinite recursion
    if (0.9 * target_rate <= actual_rate <= 1.1 * target_rate) or not restrict or duration < 0.07:
        if duration >= 0.07: 
            src_print = str(src_hosts[:3]) + "..." if len(src_hosts) > 3 else str(src_hosts)
            # dst_hosts might be very large now (all other switches), so just print count
            dst_print = f"[Total {len(dst_hosts)} hosts]"
            print(f'{src_print} -> {dst_print}')
            print(f'time: {base_time}-{base_time+duration}, avg_interval: {avg_interval*1000:.3f}ms, avg_size: {avg_size}, rate_per_host: {rate_per_host/1e9:.3f}G')
            print(f'Actual Rate: {actual_rate/1e9:.3f} Gbps, Target Rate: {target_rate/1e9:.3f} Gbps')
        return flows
    else:
        return generate_flows(src_hosts, dst_hosts, cdf_file, host_rate, duration, base_time, restrict=True)

def generate_dynamic_flows(as_list, cdf_file, total_rate, duration, 
                           slice_duration=0.02, slice_rate='100G', base_time=2.0):
    flows = []
    total_rate_f = translate_bandwidth(total_rate)
    slice_rate_f = translate_bandwidth(slice_rate)
    slice_count = int((total_rate_f * duration) / (slice_rate_f * slice_duration))
    if slice_count == 0:
        slice_count = 1
        
    avg_interval = duration / slice_count

    for src_as in as_list:
        cur_time = base_time + poisson(avg_interval * 1e9) / 1e9
        while cur_time < base_time + duration:
            dst_as = random.choice([as_item for as_item in as_list if as_item != src_as])
            flows += generate_flows(src_as, dst_as, cdf_file, f'{slice_rate_f/len(src_as)/1e9}G', slice_duration , cur_time, restrict=False)
            cur_time += poisson(avg_interval * 1e9) / 1e9
    return flows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成网络流量')
    parser.add_argument('-b','--background-inter-load', type=int, default=100, help='background_inter_load')
    parser.add_argument('-d','--dynamic-load', type=int, default=100, help='dynamic_load')
    parser.add_argument('-f', '--flow_set', type=str, default='w')
    parser.add_argument('-w', '--wan-hosts-num', type=int, default=20, help='每个WAN Switch下的Host数量')
    
    # WAN 速率参数 (表示 Switch 对之间的速率)
    parser.add_argument('--wan-rate', type=str, default='400G', help='WAN Switch 对之间的速率')
    parser.add_argument('--wan-duration-ms', type=float, default=20.0,
                        help='WAN TCP 流量生成窗口长度（毫秒，默认 20）')
    parser.add_argument('--wan-base-time', type=float, default=2.0,
                        help='WAN TCP 流量生成窗口起始时间（秒，默认 2.0）')
    parser.add_argument('--wan-output', type=str, default='',
                        help='WAN TCP 输出文件名（相对于 config 目录；为空时按 w-tcp-<rate>.txt 命名）')
    parser.add_argument('--wan-only', action='store_true',
                        help='只生成 WAN TCP 文件，不生成 w-dynamic-* 文件')

    args = parser.parse_args()

    background_inter_load = args.background_inter_load
    dynamic_load = args.dynamic_load
    flow_set = args.flow_set
    wan_hosts_num = args.wan_hosts_num
    wan_pair_rate_str = args.wan_rate
    wan_duration_s = args.wan_duration_ms / 1000.0
    wan_base_time = args.wan_base_time
    if wan_duration_s <= 0:
        parser.error('--wan-duration-ms 必须大于 0')

    base_dir = op.join(op.dirname(__file__), '../traffic_gen')

    if flow_set == 'a':
        cdf_path = op.join(base_dir, 'AliStorage2019') + '.txt'
    elif flow_set == 's':
        cdf_path = op.join(base_dir, 'Solar2022') + '.txt'
    elif flow_set == 'm':
        cdf_path = op.join(base_dir, 'mining') + '.txt'
    else:
        cdf_path = op.join(base_dir, 'WebSearch') + '.txt'

    as_list:list[list[int]] = []
    wan_as_list:list[list[int]] = [] 
    
    # 读取拓扑
    topo_path = Path(__file__).parent / 'cernet_topo.txt'
    if not topo_path.exists():
        print(f"Warning: {topo_path} not found.")
        topo = {'as_topologies': [], 'wan_hosts': []}
    else:
        with topo_path.open() as f:
            topo = json.load(f)

    all_wan_hosts = topo.get('wan_hosts', [])
    wan_host_idx = 0

    # 分配 Host 到 AS (WAN Switch)
    for as_item in topo.get('as_topologies', []):
        as_list.append(as_item['hosts'])
        
        start = wan_host_idx
        end = wan_host_idx + wan_hosts_num
        selected_wan_hosts = all_wan_hosts[start:end]
        
        wan_as_list.append(selected_wan_hosts)
        wan_host_idx = end

    # ---------------------------------------------------------------------------------
    # 普通 DC 内部/间流量生成 (保持原样)
    # ---------------------------------------------------------------------------------
    flows = []
    if not args.wan_only:
        per_host_inter_load = background_inter_load / 5 / 16 
        intra_load = 100 * 0.3 
        
        for as1 in as_list:
            for as2 in as_list:
                if as1 == as2:
                    flows += generate_flows(as1, as2, cdf_path, f'{intra_load}G', 0.07)
                else:
                    flows += generate_flows(as1, as2, cdf_path, f'{per_host_inter_load}G', 0.07)

        if dynamic_load > 0:
            flows += generate_dynamic_flows(as_list, cdf_path, f'{dynamic_load}G', 0.07, slice_duration=0.03, slice_rate='100G')
    # ---------------------------------------------------------------------------------
    # 修改后的 WAN 流量生成逻辑
    # ---------------------------------------------------------------------------------
    wan_flows = []
    
    # 解析 WAN 对之间的总速率
    try:
        target_pair_bw = translate_bandwidth(wan_pair_rate_str)
    except Exception as e:
        print(f"Error parsing wan-rate: {e}, defaulting to 400G")
        target_pair_bw = 400 * 1e9

    # 过滤出有效的 WAN Switch（有Host的）
    active_wan_switches = [hosts for hosts in wan_as_list if len(hosts) > 0]
    num_wan_switches = len(active_wan_switches)

    print(f"\n[WAN Traffic Generation]")
    print(f"Configuration: {num_wan_switches} Active WAN Switches.")
    print(f"Target Rate per Switch Pair: {target_pair_bw/1e9} Gbps.")

    # 遍历每个源 Switch
    for i, src_hosts in enumerate(active_wan_switches):
        # 1. 收集所有其他 Switch 的 Host 作为目标池
        #    这样做的目的是让流量随机分布到其他所有 Switch，从而满足"到另外四个都是200G"的统计结果
        other_hosts_pool = []
        for j, other_hosts in enumerate(active_wan_switches):
            if i != j:
                other_hosts_pool.extend(other_hosts)
        
        if len(src_hosts) > 0 and len(other_hosts_pool) > 0:
            # 2. 应用用户指定的公式
            # 单机速率 = WAN对之间速率 * WAN Switch数量 / 该Switch下的Host数量
            # 例如：200G * 5 / 20 = 50G
            # 这样总出口流量 = 50G * 20 = 1000G。分摊给其他4个Switch，平均每个约250G。
            per_host_rate_val = (target_pair_bw * num_wan_switches) / len(src_hosts)
            per_host_rate_str = f"{per_host_rate_val/1e9}G"
            
            # 3. 生成流量 (src -> 所有其他 hosts)
            wan_flows += generate_flows(
                src_hosts, 
                other_hosts_pool, 
                cdf_path, 
                per_host_rate_str, 
                duration=wan_duration_s, 
                base_time=wan_base_time
            )

    # ---------------------------------------------------------------------------------
    # 保存结果
    # ---------------------------------------------------------------------------------

    flows.sort(key=lambda x : x.t)
    wan_flows.sort(key=lambda x : x.t)

    # 输出到文件 (DC 背景流)
    saved_path = op.join(op.dirname(__file__), f'{flow_set}-dynamic-{int(background_inter_load)}-{int(dynamic_load)}.txt')
    if not args.wan_only:
        print(f'\nOriginal Flow count: {len(flows)}, Saved to: {saved_path}')
        with open(saved_path, 'w') as ofile:
            ofile.write(f"{len(flows)}\n")
            for f in flows:
                ofile.write(str(f) + '\n')

    # 输出到文件 (WAN 流量)
    wan_rate_lbl = wan_pair_rate_str.replace('G', '').replace('M', '')
    wan_filename = args.wan_output or f'{flow_set}-tcp-{wan_rate_lbl}.txt'
    wan_saved_path = op.join(op.dirname(__file__), wan_filename)
    print(f'WAN Flow count: {len(wan_flows)}, Saved to: {wan_saved_path}')
    with open(wan_saved_path, 'w') as ofile:
        ofile.write(f"{len(wan_flows)}\n")
        for f in wan_flows:
            ofile.write(str(f) + '\n')
