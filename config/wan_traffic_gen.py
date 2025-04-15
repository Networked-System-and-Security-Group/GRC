import json
import math
import random

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
        return None
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

def generate_flows(src_hosts, dst_hosts, cdf_file, send_rate, duration, base_time=2.0):
    custom_rand = CustomRand(cdf_file)
    flows = []
    avg_size = custom_rand.get_avg()
    rate_per_host = translate_bandwidth(send_rate)
    avg_interval = 1 / (rate_per_host / 8 / avg_size)
    print(f'{src_hosts} -> {dst_hosts}')
    print(f'time: {base_time}, duration: {duration}')
    print(f'avg_interval: {avg_interval*1000:.3f}ms, avg_size: {avg_size}, rate_per_host: {rate_per_host/1e9:.3f}G')

    for src in src_hosts:
        current_time = base_time + poisson(avg_interval*1e9)/1e9
        while current_time < base_time + duration:
            dst = random.choice([h for h in dst_hosts if h != src])
            flows.append(Flow(src, dst, int(custom_rand.rand()), current_time))
            current_time += poisson(avg_interval*1e9)/1e9


    flows.sort(key=lambda f: f.t)
    return flows

if __name__ == '__main__':
    # 合并后的配置（duration 为公共参数）
    cdf = '/home/zj/recover/ns-allinone-3.19/ns-3.19/traffic_gen/WebSearch.txt'
    as0 = list(range(0, 16))
    as1 = list(range(37, 53))
    as2 = list(range(74, 90))

    flows = generate_flows(as0, as0, cdf, '30G', 0.05) \
          + generate_flows(as1, as1, cdf, '30G', 0.05) \
          + generate_flows(as2, as2, cdf, '30G', 0.05) \
          + generate_flows(as0, as1, cdf, '10G', 0.05) \
          + generate_flows(as0, as2, cdf, '10G', 0.05) \
          + generate_flows(as1, as0, cdf, '10G', 0.05) \
          + generate_flows(as1, as2, cdf, '10G', 0.05) \
          + generate_flows(as2, as0, cdf, '6G', 0.05) \
          + generate_flows(as2, as1, cdf, '6G', 0.05) 
    flows.sort(key=lambda x : x.t)
    # 输出到文件
    with open('/home/zj/recover/ns-allinone-3.19/ns-3.19/config/wan_traffic.txt', 'w') as ofile:
        ofile.write(f"{len(flows)}\n")
        for f in flows:
            ofile.write(str(f) + '\n')
