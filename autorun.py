import os
import argparse

def main():
    # 默认运行cernet_topo，
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--flow_set', type=str, default='w')
    parser.add_argument('-e', '--expr', type=str, default='s')

    args = parser.parse_args()
    flow_set = args.flow_set
    expr_type = args.expr
    static_flow = [150,200,250,300,350]
    dynamic_flow = [0, 50, 100, 150, 200]

    expr_cnt = 1

    # 首先生成对应的流量集：
    if expr_type == 's':
        # 静态流量集生成
        for flow in static_flow:
            #os.system(f"python ./config/large_traffic_gen.py -b {flow} -d 0 -f {flow_set}")
            flow_name = f'{flow_set}-dynamic-{flow}-0'
            for wan_cc_mode in range(0,3):
                os.system(f"python run.py --topo cernet_topo --my_flow {flow_name} --wan_cc_mode {wan_cc_mode} --msg 'No.{expr_cnt}静态实验-流{flow_name} -wan_cc_mode{wan_cc_mode}' ")
                expr_cnt += 1

    elif expr_type == 'd':
        for flow in dynamic_flow:
            #os.system(f"python ./config/large_traffic_gen.py -b 150 -d {flow} -f {flow_set}")
            flow_name = f'{flow_set}-dynamic-150-{flow}'
            for wan_cc_mode in range(0,3):
                os.system(f"python run.py --topo cernet_topo --my_flow {flow_name} --wan_cc_mode {wan_cc_mode} --msg 'No.{expr_cnt}动态实验-流{flow_name} -wan_cc_mode{wan_cc_mode}' ")
                expr_cnt += 1

    
if __name__ == "__main__":
    main()