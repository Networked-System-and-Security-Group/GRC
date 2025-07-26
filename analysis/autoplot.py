from deep_analyse import *
import os
import argparse

def main():
    # 负责绘制
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--expr', type=str)
    parser.add_argument('-f', '--flow_type', type=str)

    args = parser.parse_args()
    flow_type = args.flow_type
    expr = args.expr
    
    # 首先绘制AVG FCT

    dcqcn = []
    dcqcn_ecn = []
    gscc_intra = []
    gscc_inter = []
    gscc_inter_large = []
    gscc_inter_small = []
    
    wan_cc_mode = 0
    for ana in analyser_iter(expr):
        try:
            avg_vals, avg_intra, avg_inter = ana.get_avg_fct()
            p99_vals, p99_intra, p99_inter = ana.get_p99_fct()
            # results[wan_cc_mode].append({
            #     'ID': ana.id,
            #     'Avg_FCT': avg_vals,
            #     'Avg_Intra_FCT': avg_intra,
            #     'Avg_Inter_FCT': avg_inter,
            #     'P99_FCT': p99_vals,
            #     'P99_Intra_FCT': p99_intra,
            #     'P99_Inter_FCT': p99_inter
            # })
        except Exception as e:
            print(f'Error processing {ana.id}: {e}')
        
        wan_cc_mode = (wan_cc_mode + 1) % 3

    
    return

if __name__ == "__main__":
    main()