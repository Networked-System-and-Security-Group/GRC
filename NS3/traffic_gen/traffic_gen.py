import sys
import random
import math
import heapq
from optparse import OptionParser

from custom_rand import CustomRand
import numpy as np

class Flow:
	def __init__(self, src, dst, size, t):
		self.src, self.dst, self.size, self.t = src, dst, size, t
	def __str__(self):
		return "%d %d 3 %d %.9f"%(self.src, self.dst, self.size, self.t)

def translate_bandwidth(b):
	if b == None:
		return None
	if type(b)!=str:
		return None
	if b[-1] == 'G':
		return float(b[:-1])*1e9
	if b[-1] == 'M':
		return float(b[:-1])*1e6
	if b[-1] == 'K':
		return float(b[:-1])*1e3
	return float(b)

def poisson(lam):
	return -math.log(1-random.random())*lam

def generate_normal_integer(mean, std_dev):
    random_float = np.random.normal(mean, std_dev)
    random_int = int(round(random_float))
    return random_int

def get_random_host_by_pod(pod_size, pod_no):
	return random.randint(pod_size * pod_no, pod_size * (pod_no + 1) - 1)


if __name__ == "__main__":
	port = 80
	parser = OptionParser()
	parser.add_option("-c", "--cdf", dest = "cdf_file", help = "the file of the traffic size cdf", default = "AliStorage2019.txt")
	parser.add_option("-n", "--nhost", dest = "nhost", help = "number of hosts", default = 256)
	parser.add_option("-l", "--load", dest = "load", help = "the percentage of the traffic load to the network capacity, by default 0.3", default = "0.3")
	parser.add_option("-b", "--bandwidth", dest = "bandwidth", help = "the bandwidth of host link (G/M/K), by default 10G", default = "100G")
	parser.add_option("-t", "--time", dest = "time", help = "the total run time (s), by default 10", default = "0.03")
	parser.add_option("-o", "--output", dest = "output", help = "the output file", default = "tmp_traffic.txt")
	
	
	options,args = parser.parse_args()

	base_t = 2000000000 # 2000000000

	if not options.nhost:
		print("please use -n to enter number of hosts")
		sys.exit(0)
	nhost = int(options.nhost)
	load = float(options.load)
	bandwidth = translate_bandwidth(options.bandwidth)
	time = float(options.time)*1e9 # translates to ns
	output = options.output
	if bandwidth == None:
		print("bandwidth format incorrect")
		sys.exit(0)

	fileName = options.cdf_file
	file = open(fileName,"r")
	lines = file.readlines()
	# read the cdf, save in cdf as [[x_i, cdf_i] ...]
	cdf = []
	for line in lines:
		x,y = map(float, line.strip().split(' '))
		cdf.append([x,y])

	# create a custom random generator, which takes a cdf, and generate number according to the cdf
	customRand = CustomRand()
	if not customRand.setCdf(cdf):
		print("Error: Not valid cdf")
		sys.exit(0)

	ofile = open(output, "w")

	# generate flows
	avg = customRand.getAvg()
	flows = []
    # 首先，生成random流量
	avg_inter_arrival = 1/(bandwidth*load/8./avg)*1000000000 
	#n_flow_estimate = int(time / avg_inter_arrival * nhost)
	#n_flow = 0
	host_list = [(base_t + int(poisson(avg_inter_arrival)), i) for i in range(nhost)]# (时间，hostid)
	heapq.heapify(host_list)
	while len(host_list) > 0:
		t,src = host_list[0]
		inter_t = int(poisson(avg_inter_arrival))
		dst = random.randint(0, nhost-1)
		while (dst == src):
			dst = random.randint(0, nhost-1)
		if (t + inter_t > time + base_t):
			heapq.heappop(host_list)
		else:
			size = int(customRand.rand())
			if size <= 0:
				size = 1
			#n_flow += 1
			flows.append(Flow(src, dst, size, t * 1e-9))
			heapq.heapreplace(host_list, (t + inter_t, src))

	flows.sort(key=lambda x : x.t)
	ofile.write(f"{len(flows)}\n")
	for f in flows:
		ofile.write(f.__str__() + '\n')
	ofile.close()
