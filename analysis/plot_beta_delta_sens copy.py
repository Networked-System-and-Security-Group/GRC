import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from mpl_toolkits.mplot3d import Axes3D
from deep_analyse import get_analyser, analyser_iter
import matplotlib
matplotlib.rcParams['pdf.fonttype'] = 42  # TrueType 字体
matplotlib.rcParams['ps.fonttype'] = 42  # TrueType 字体

# Determine script directory for saving files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Set Global Font Sizes
plt.rcParams.update({
    'font.size': 18,
    'axes.titlesize': 20,
    'axes.labelsize': 27,
    'xtick.labelsize': 16,
    'ytick.labelsize': 16,
    'legend.fontsize': 22,
    'figure.titlesize': 22
})

# Default IDs if not provided
DEFAULT_IDS_STR = "241-260,264,265"
DEFAULT_METRICS = ['inter_avg_fct', 'wan_buffer_p99']

def get_metric_label(metric_key):
    if metric_key == 'inter_avg_fct':
        return 'Avg. Normalized FCT'
    elif metric_key == 'wan_buffer_avg':
        return 'Avg WAN Buffer (MB)'
    elif metric_key == 'wan_buffer_p99':
        return 'Queue Length (MB)'
    elif metric_key == 'drop_number':
        return 'Total Packet Drop Count'
    return metric_key

def parse_msg(msg):
    params = {}
    if not msg:
        return params
    for part in msg.split(','):
        if '=' in part:
            key, val = part.split('=', 1)
            params[key.strip()] = val.strip()
    return params

def collect_data(config_ids_str, metric_key):
    data = []
    print(f"Collecting data for ids: {config_ids_str}...")
    
    for ana in analyser_iter(config_ids_str):
        run_id = ana.id
        try:
            # Assuming get_analyser returns an object with .config dict
            msg = ana.config.get('MSG', '')
            params = parse_msg(msg)
            
            beta_str = params.get('BETA')
            inv_delta_str = params.get('INV_DELTA')
            
            if beta_str is None or inv_delta_str is None:
                # If msg is missing or doesn't have BETA/INV_DELTA, we skip or log
                # print(f"Skipping ID {run_id}: Missing BETA or INV_DELTA in MSG: {msg}")
                continue
                
            beta = float(beta_str)
            inv_delta = float(inv_delta_str) / 1048576.0 # Convert to MB
            
            # Capture other potential grouping keys
            enable_v = params.get('ENABLE_V', 'N/A')
            
            value = np.nan
            if metric_key == 'inter_avg_fct':
                _, _, value = ana.get_avg_fct()
            elif metric_key == 'wan_buffer_avg':
                mean, _ = ana.get_wan_buffer_stats()
                value = mean
            elif metric_key == 'wan_buffer_p99':
                _, p99 = ana.get_wan_buffer_stats()
                value = p99
            elif metric_key == 'drop_number':
                value = ana.get_drop_number()
                
            data.append({
                'RunID': run_id,
                'Beta': beta,
                'InvDelta': inv_delta,
                'EnableV': enable_v,
                'Value': value,
                'MSG': msg
            })
            
        except Exception as e:
            print(f"Error processing ID {run_id}: {e}")
            pass
            
    return pd.DataFrame(data)

def plot_group(df, group_name, metric_key):
    z_label = get_metric_label(metric_key)
    
    # Filename prefix (sanitize group name)
    safe_group_name = group_name.replace('=', '_').replace(' ', '_')
    prefix = f"new_beta_delta_{metric_key}_{safe_group_name}"
    
    # 2. Plot Heatmap
    try:
        # Check for duplicates
        if df.duplicated(subset=['Beta', 'InvDelta']).any():
             print(f"Warning: Duplicates found in group {group_name}. Taking mean.")
             df = df.groupby(['Beta', 'InvDelta']).agg({'Value': 'mean'}).reset_index()

        pivot_table = df.pivot(index='InvDelta', columns='Beta', values='Value')
        pivot_table = pivot_table.sort_index(ascending=True) 
        pivot_table = pivot_table.sort_index(axis=1, ascending=True)

        plt.figure(figsize=(10, 8))
        sns.heatmap(pivot_table, annot=True, fmt=".2f", cmap="viridis_r", cbar_kws={'label': z_label})
        title = f"{z_label}\n(InvDelta vs Beta) - {group_name}"
        plt.title(title)
        plt.xlabel("Beta")
        plt.ylabel("Inv Delta (MB)")
        # plt.tight_layout() # Using bbox_inches='tight' instead
        heatmap_path = os.path.join(SCRIPT_DIR, f"{prefix}_heatmap.pdf")
        plt.savefig(heatmap_path, bbox_inches='tight')
        print(f"Saved heatmap to {heatmap_path}")
        plt.close()
        
        # 3. Plot 3D
        X_vals = pivot_table.columns.values # Beta
        Y_vals = pivot_table.index.values   # InvDelta
        
        # Use indices for equidistant spacing
        X_indices = np.arange(len(X_vals))
        Y_indices = np.arange(len(Y_vals))
        X_mesh, Y_mesh = np.meshgrid(X_indices, Y_indices)
        Z = pivot_table.values

        fig = plt.figure(figsize=(12, 10))
        ax = fig.add_subplot(111, projection='3d')
        surf = ax.plot_surface(X_mesh, Y_mesh, Z, cmap='viridis', edgecolor='k', linewidth=0.5, alpha=0.9)
        
        # Set ticks to show original values
        ax.set_xticks(X_indices)
        ax.set_xticklabels([f"{x:g}" for x in X_vals])
        ax.set_yticks(Y_indices)
        ax.set_yticklabels([f"{y:g}" for y in Y_vals])
        
        # Explicitly set tick label size
        ax.tick_params(axis='x', labelsize=24)
        ax.tick_params(axis='y', labelsize=24)
        ax.tick_params(axis='z', labelsize=24)

        if metric_key == 'inter_avg_fct':
            ax.set_zticks([1.5, 1.8, 2.1, 2.4, 2.7, 3.0])
        
        #ax.set_title(title)
        ax.set_xlabel('$\\beta$', labelpad=15)         
        ax.set_ylabel('$\\frac{1}{\\delta}$ (MB)', labelpad=15) 
        ax.set_zlabel(z_label, labelpad=15)
        # fig.colorbar(surf, ax=ax, shrink=0.5, aspect=5, label=z_label)
        # plt.tight_layout()
        plot3d_path = os.path.join(SCRIPT_DIR, f"{prefix}_3d.pdf")
        plt.savefig(plot3d_path)
        print(f"Saved 3D plot to {plot3d_path}")
        plt.close()
        
    except Exception as e:
        print(f"Error plotting group {group_name}: {e}")
        import traceback
        traceback.print_exc()

import matplotlib.lines as mlines

def plot_combined_3d(df, metric_key):
    z_label = get_metric_label(metric_key)
    groups = df.groupby('EnableV')
    
    if len(groups) <= 1:
        return

    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # Use different colors for surfaces
    colors = ['blue', 'red', 'green', 'orange']
    legend_handles = []
    
    for i, (enable_v, group_df) in enumerate(groups):
        label = f"EnableV={enable_v}"
        
        if group_df.duplicated(subset=['Beta', 'InvDelta']).any():
             group_df = group_df.groupby(['Beta', 'InvDelta']).agg({'Value': 'mean'}).reset_index()

        pivot_table = group_df.pivot(index='InvDelta', columns='Beta', values='Value')
        pivot_table = pivot_table.sort_index(ascending=True) 
        pivot_table = pivot_table.sort_index(axis=1, ascending=True)

        X_vals = pivot_table.columns.values
        Y_vals = pivot_table.index.values
        
        # Use indices for equidistant spacing
        X_indices = np.arange(len(X_vals))
        Y_indices = np.arange(len(Y_vals))
        X_mesh, Y_mesh = np.meshgrid(X_indices, Y_indices)
        Z = pivot_table.values
        
        c = colors[i % len(colors)]
        
        surf = ax.plot_surface(X_mesh, Y_mesh, Z, color=c, edgecolor='k', linewidth=0.2, alpha=0.5)
        
        legend_handles.append(mlines.Line2D([0], [0], linestyle="none", marker='o', color=c, label=label))
        
        # We need to set ticks at the end, assuming all groups share roughly the same X/Y
        # But groups might have different subsets. For now, assume consistent grid across groups if possible.
        # Ideally, we should unify the grid.
        
    # Unify ticks based on the last group (Assuming logic holds: same expr setup for both groups)
    # If this assumption fails, we need more complex logic.
    if 'X_vals' in locals():
        ax.set_xticks(X_indices)
        ax.set_xticklabels([f"{x:g}" for x in X_vals])
        ax.set_yticks(Y_indices)
        ax.set_yticklabels([f"{y:g}" for y in Y_vals])
        
        # Explicitly set tick label size
        ax.tick_params(axis='x', labelsize=16)
        ax.tick_params(axis='y', labelsize=16)
        ax.tick_params(axis='z', labelsize=16)
        
        if metric_key == 'inter_avg_fct':
            ax.set_zticks([1.5, 1.8, 2.1, 2.4, 2.7, 3.0])
    
    ax.set_title(f"Combined {z_label} (InvDelta vs Beta)")
    ax.set_xlabel('Beta', labelpad=15)         
    ax.set_ylabel('Inv Delta (MB)', labelpad=15) 
    ax.set_zlabel(z_label, labelpad=15)
    ax.legend(handles=legend_handles)
    
    filename = f"beta_delta_{metric_key}_combined_3d.pdf"
    filepath = os.path.join(SCRIPT_DIR, filename)
    # plt.tight_layout()
    plt.savefig(filepath, bbox_inches='tight')
    print(f"Saved combined 3D plot to {filepath}")
    plt.close()


def main():
    metrics = DEFAULT_METRICS
    config_ids_str = DEFAULT_IDS_STR
    
    # Usage: python plot.py [ids_str] [metric]
    args = sys.argv[1:]
    if len(args) >= 1:
        config_ids_str = args[0]
    if len(args) >= 2:
        metrics = [args[1]]
    
    for metric in metrics:
        print(f"\n--- Processing Metric: {metric} ---")
        df = collect_data(config_ids_str, metric)
        
        if df.empty:
            print(f"No data collected found for the given range for metric {metric}.")
            continue

        # Save raw data
        csv_name = f"beta_delta_{metric}_raw.csv"
        csv_path = os.path.join(SCRIPT_DIR, csv_name)
        df.to_csv(csv_path, index=False)
        print(f"Saved raw data to {csv_path}")
        
        # Group by extra parameters (EnableV)
        groups = df.groupby('EnableV')
        
        for enable_v, group_df in groups:
            group_name = f"EnableV={enable_v}"
            print(f"Plotting group: {group_name} with {len(group_df)} records")
            plot_group(group_df, group_name, metric)

        # Plot combined if we have groups
        if len(groups) > 1:
            print("Plotting combined 3D plot...")
            plot_combined_3d(df, metric)


if __name__ == "__main__":
    main()
