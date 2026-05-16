# %% 
from __future__ import annotations
import json
import subprocess
import matplotlib.pyplot as plt
import os
import os.path as op
import re
import sys
from dataclasses import dataclass, field
from collections import Counter, OrderedDict, defaultdict
import numpy as np
import pandas as pd
from typing import Generator, Union, List, Dict
import functools
from IPython.display import display
from matplotlib.font_manager import FontProperties
import traceback
from pathlib import Path
import matplotlib
matplotlib.rcParams['pdf.fonttype'] = 42  # TrueType 字体
matplotlib.rcParams['ps.fonttype'] = 42  # TrueType 字体

font_prop = None

def auto_save_plot(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. 调用原函数，完成绘图
        result = func(*args, **kwargs)

        # 2. 确定保存目录
        base_dir = op.join(op.dirname(__file__), 'figures')
        os.makedirs(base_dir, exist_ok=True)

        # 3. 构造文件名
        self = args[0]
        name = func.__name__.replace('plot_', '')
        arg_parts = [str(a) for a in args[1:]]
        kw_parts  = [f"{k}_{v}" for k, v in kwargs.items()]
        parts = [self.id, name] + arg_parts + kw_parts
        raw = "-".join(parts)
        safe = re.sub(r'[^0-9A-Za-z_\-]+', '_', raw)
        filename = f"{safe}.pdf"
        save_path = op.join(base_dir, filename)

        # 4. 保存并关闭当前 figure
        #plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()
        plt.close()

        print(f"[auto_save_plot] 已保存：{save_path}")
        return result
    return wrapper

def get_dir_by_id(config_id):
    '''return experiment output dir by id'''
    base_dir = op.join(op.dirname(__file__), '../mix/output')
    cmd = f"ls -l {base_dir}"
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    full = [x.strip().split()[-1] for x in result.stdout.split('\n') if f'[{config_id}]' in x]
    if len(full) != 1:
        raise Exception(f'failed to find {config_id} experiment')
    return op.join(base_dir, full[0])

def latest(offset=0):
    """获取最新的实验目录"""
    base_dir = op.join(op.dirname(__file__), '../mix/output')
    cmd = f"ls -lt {base_dir}"
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    latest_dir = result.stdout.split('\n')[1+offset].split()[-1]
    id = latest_dir.split('[')[-1].split(']')[0]
    print(f'latest experiment dir: {latest_dir}')
    return get_analyser(id)


def plot_cdf(series, label=None, color=None):
    """辅助函数：绘制单个数据集的 CDF"""
    if series.empty: return
    sorted_vals = np.sort(series)
    y = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
    plt.plot(sorted_vals, y, label=label, color=color)

class Analyser:
    def __init__(self, id):
        self.id = str(id)
        self.dir = get_dir_by_id(self.id)
        self.flow_df: pd.DataFrame = None    # 全量流记录
        self.rtt_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,next_hop,rtt1_ms,measured_rtt_ms,timeout_count
        self.drop_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,flow_id,seq_num,type
        self.link_info: pd.DataFrame = None #timestamp_ns,src_id,dst_id,flow_id,bytes
        self.buffer_info: pd.DataFrame = None #timestamp_ns,switch_id,next_hop,ingress_bytes,egress_bytes
        self.qp_rate_info: pd.DataFrame = None #timestamp_ns,flow_id,rate,alpha,target_rate
        self.as_rate_info: pd.DataFrame = None #timestamp_ns,src_as,dst_as,real_rate,ref_rate
        self.cnp_info: pd.DataFrame = None #timestamp_ns,switch_id,flow_id
        self.cnp_trigger_prob_info: pd.DataFrame = None #timestamp_ns,switch_id,src_as,dst_as,cnp_cnt,pkt_cnt,prob
        self.accumulated_bytes_info: pd.DataFrame = None #timestamp_ns,switch_id,dst_as,accumulated_bytes
        self.pfc_info: pd.DataFrame = None #timestamp_ns,node_id,is_switch,nbr_id,is_pause
        self.config: map[str, object] = {}
        self.read_config()
        with (Path(__file__).parent.parent / self.config['TOPOLOGY_FILE']).open() as f:
            self.topo = json.load(f)

        self._wan_edge_attr_cache: dict[tuple[int, int], dict[str, float]] | None = None
        self._dci_to_as_cache: dict[int, int] | None = None

    def _parse_time_to_seconds(self, v: object) -> float:
        """Parse ns-3 style time string (e.g., '4000ns','1000us','2ms','1s') to seconds."""
        if v is None:
            raise ValueError('time is None')
        if isinstance(v, (int, float)):
            # Heuristic: treat numeric as nanoseconds.
            return float(v) * 1e-9
        s = str(v).strip()
        m = re.match(r'^\s*([0-9]*\.?[0-9]+)\s*(ns|us|ms|s)\s*$', s, flags=re.IGNORECASE)
        if not m:
            raise ValueError(f'Unsupported time format: {v!r}')
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit == 'ns':
            return val * 1e-9
        if unit == 'us':
            return val * 1e-6
        if unit == 'ms':
            return val * 1e-3
        if unit == 's':
            return val
        raise ValueError(f'Unsupported time unit: {unit}')

    def _parse_rate_to_bps(self, v: object) -> float:
        """Parse ns-3 style data rate string (e.g., '200Gbps') to bits/s."""
        if v is None:
            raise ValueError('rate is None')
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        m = re.match(r'^\s*([0-9]*\.?[0-9]+)\s*([KMGTP]?)(?:b|B)ps\s*$', s, flags=re.IGNORECASE)
        if not m:
            raise ValueError(f'Unsupported rate format: {v!r}')
        val = float(m.group(1))
        prefix = m.group(2).upper()
        mult = {
            '': 1.0,
            'K': 1e3,
            'M': 1e6,
            'G': 1e9,
            'T': 1e12,
            'P': 1e15,
        }.get(prefix)
        if mult is None:
            raise ValueError(f'Unsupported rate prefix: {prefix}')
        # Input is bps (bits per second) per ns-3 naming.
        return val * mult

    def _get_dci_to_as_map(self) -> dict[int, int]:
        if self._dci_to_as_cache is not None:
            return self._dci_to_as_cache
        m: dict[int, int] = {}
        for as_obj in self.topo.get('as_topologies', []):
            m[int(as_obj['dci_switch'])] = int(as_obj['as_id'])
        self._dci_to_as_cache = m
        return m

    def _get_as_by_dci_switch(self, switch_id: int) -> int | None:
        return self._get_dci_to_as_map().get(int(switch_id))

    def _get_wan_edge_attr(self) -> dict[tuple[int, int], dict[str, float]]:
        """Return per-directed-edge attributes for WAN links: delay_s, bw_Bps."""
        if self._wan_edge_attr_cache is not None:
            return self._wan_edge_attr_cache

        edges: dict[tuple[int, int], dict[str, float]] = {}
        for link in self.topo.get('wan_links', []):
            u = int(link['src'])
            v = int(link['dst'])
            delay_s = self._parse_time_to_seconds(link.get('delay', 0))
            bw_bps = self._parse_rate_to_bps(link.get('bw', 0))
            bw_Bps = bw_bps / 8.0 if bw_bps > 0 else 0.0
            edges[(u, v)] = {'delay_s': delay_s, 'bw_Bps': bw_Bps}
            edges[(v, u)] = {'delay_s': delay_s, 'bw_Bps': bw_Bps}

        self._wan_edge_attr_cache = edges
        return edges

    def get_wan_base_rtt_ms(self, src_as: int, dst_as: int) -> float:
        """Compute shortest-path base RTT (propagation-only) between src_as and dst_as in ms."""
        path = self.get_wan_key_path(src_as, dst_as)
        if not path or len(path) < 2:
            return float('nan')
        attr = self._get_wan_edge_attr()
        one_way_s = 0.0
        for u, v in zip(path[:-1], path[1:]):
            a = attr.get((int(u), int(v)))
            if a is None:
                raise KeyError(f'No WAN link attrs for edge {u}->{v} on path {path}')
            one_way_s += float(a['delay_s'])
        return float(one_way_s * 2.0 * 1e3)

    def _build_wan_path_edges(self, src_as: int, dst_as: int, *, include_return: bool) -> list[tuple[int, int]]:
        path = self.get_wan_key_path(src_as, dst_as)
        if not path or len(path) < 2:
            return []
        edges = [(int(u), int(v)) for u, v in zip(path[:-1], path[1:])]
        if include_return:
            edges += [(v, u) for (u, v) in edges]
        return edges

    def _get_queue_predictor_series(
        self,
        src_as: int,
        dst_as: int,
        *,
        include_return: bool = True,
        egress: bool = True,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
    ) -> pd.DataFrame:
        """Build time series of (queue_sum_bytes, queue_delay_pred_ms) along shortest WAN path."""
        self.__read_buffer_info()
        edges = self._build_wan_path_edges(src_as, dst_as, include_return=include_return)
        if not edges:
            return pd.DataFrame(columns=['timestamp_ns', 'queue_sum_bytes', 'queue_delay_pred_ms'])

        df = self.buffer_info
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= float(start_time_s) * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= float(end_time_s) * 1e9]
        if df.empty:
            return pd.DataFrame(columns=['timestamp_ns', 'queue_sum_bytes', 'queue_delay_pred_ms'])

        col = 'egress_bytes' if egress else 'ingress_bytes'
        edges_df = pd.DataFrame(edges, columns=['switch_id', 'next_hop']).drop_duplicates()

        # attach bandwidth to each edge
        attr = self._get_wan_edge_attr()
        edges_df['bw_Bps'] = edges_df.apply(
            lambda r: float(attr.get((int(r['switch_id']), int(r['next_hop'])), {}).get('bw_Bps', 0.0)),
            axis=1,
        )

        merged = df.merge(edges_df, on=['switch_id', 'next_hop'], how='inner')
        if merged.empty:
            return pd.DataFrame(columns=['timestamp_ns', 'queue_sum_bytes', 'queue_delay_pred_ms'])

        q_bytes = pd.to_numeric(merged[col], errors='coerce').fillna(0.0)
        bw_Bps = pd.to_numeric(merged['bw_Bps'], errors='coerce').replace(0.0, np.nan)
        merged = merged.assign(
            queue_bytes=q_bytes,
            queue_delay_ms=(q_bytes / bw_Bps) * 1e3,
        )
        merged['queue_delay_ms'] = merged['queue_delay_ms'].fillna(0.0)

        series = (
            merged
            .groupby('timestamp_ns', as_index=False)
            .agg(queue_sum_bytes=('queue_bytes', 'sum'), queue_delay_pred_ms=('queue_delay_ms', 'sum'))
            .sort_values('timestamp_ns')
            .reset_index(drop=True)
        )
        return series

    def rtt_queue_linearity(
        self,
        *,
        src_as: int | None = None,
        dst_as: int | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        include_return: bool = True,
        egress: bool = True,
        tolerance_s: float | None = None,
        plot_pair: tuple[int, int] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Compare (measured_rtt_ms - base_rtt_ms) vs queue predictor along WAN shortest path.

        Returns:
        - summary_df: per (src_as,dst_as) linearity stats (corr, r2, slope, intercept, mae, n)
        - samples_df: joined samples with columns including extra_rtt_ms and queue_delay_pred_ms

        Notes:
        - base_rtt_ms uses propagation delay only from topo['wan_links'].
        - queue_delay_pred_ms = Σ(queue_bytes / link_bw_Bps) along path (optionally include return direction).
        """
        self.__read_rtt_info()
        self.__read_buffer_info()

        rtt = self.rtt_info.copy()
        rtt['src_as'] = rtt['switch_id'].map(lambda x: self._get_as_by_dci_switch(int(x)))
        rtt = rtt.dropna(subset=['src_as']).copy()
        rtt['src_as'] = rtt['src_as'].astype(int)
        rtt['dst_as'] = rtt['dst_as'].astype(int)

        # rtt_log's dst_as may contain WAN switch IDs as well; keep only valid AS IDs.
        valid_as_set = set(int(a.get('as_id')) for a in self.topo.get('as_topologies', []))
        if valid_as_set:
            rtt = rtt[rtt['dst_as'].isin(valid_as_set)]

        if start_time_s is not None:
            rtt = rtt[rtt['timestamp_ns'] >= float(start_time_s) * 1e9]
        if end_time_s is not None:
            rtt = rtt[rtt['timestamp_ns'] <= float(end_time_s) * 1e9]
        if src_as is not None:
            rtt = rtt[rtt['src_as'] == int(src_as)]
        if dst_as is not None:
            rtt = rtt[rtt['dst_as'] == int(dst_as)]
        if rtt.empty:
            return pd.DataFrame(), pd.DataFrame()

        rtt = rtt.sort_values('timestamp_ns').reset_index(drop=True)

        # default tolerance based on monitoring interval
        if tolerance_s is None:
            try:
                interval_ns = int(float(self.config.get('SW_MONITORING_INTERVAL', 0)))
            except Exception:
                interval_ns = 0
            tolerance_ns = int(interval_ns * 2) if interval_ns > 0 else int(2e6)  # 2ms fallback
        else:
            tolerance_ns = int(float(tolerance_s) * 1e9)

        samples_all: list[pd.DataFrame] = []
        summary_rows: list[dict] = []

        pairs = sorted(set(zip(rtt['src_as'].tolist(), rtt['dst_as'].tolist())))
        for sa, da in pairs:
            pair_df = rtt[(rtt['src_as'] == sa) & (rtt['dst_as'] == da)].copy()
            if pair_df.empty:
                continue

            base_rtt_ms = self.get_wan_base_rtt_ms(sa, da)
            q_series = self._get_queue_predictor_series(
                sa, da,
                include_return=include_return,
                egress=egress,
                start_time_s=start_time_s,
                end_time_s=end_time_s,
            )
            if q_series.empty:
                continue

            joined = pd.merge_asof(
                pair_df.sort_values('timestamp_ns'),
                q_series.sort_values('timestamp_ns'),
                on='timestamp_ns',
                direction='nearest',
                tolerance=tolerance_ns,
            )

            joined['base_rtt_ms'] = float(base_rtt_ms)
            joined['measured_rtt_ms'] = pd.to_numeric(joined['measured_rtt_ms'], errors='coerce')
            joined['extra_rtt_ms'] = joined['measured_rtt_ms'] - joined['base_rtt_ms']
            joined = joined.dropna(subset=['measured_rtt_ms', 'queue_delay_pred_ms'])
            if joined.empty:
                continue

            # optional: drop negative extra RTT (numerical / model mismatch)
            joined = joined[joined['extra_rtt_ms'].notna()].copy()

            y = joined['extra_rtt_ms'].to_numpy(dtype=float)

            def _fit_stats(x_arr: np.ndarray, y_arr: np.ndarray) -> tuple[float, float, float, float, float]:
                mask = np.isfinite(x_arr) & np.isfinite(y_arr)
                x2 = x_arr[mask]
                y2 = y_arr[mask]
                if len(x2) < 3:
                    return (float('nan'), float('nan'), float('nan'), float('nan'), float('nan'))
                a2, b2 = np.polyfit(x2, y2, deg=1)
                y_hat2 = a2 * x2 + b2
                ss_res2 = float(np.sum((y2 - y_hat2) ** 2))
                ss_tot2 = float(np.sum((y2 - float(np.mean(y2))) ** 2))
                r2_2 = 1.0 - ss_res2 / ss_tot2 if ss_tot2 > 1e-12 else float('nan')
                corr2 = float(np.corrcoef(x2, y2)[0, 1])
                mae2 = float(np.mean(np.abs(y2 - y_hat2)))
                return (corr2, r2_2, float(a2), float(b2), mae2)

            x_delay = joined['queue_delay_pred_ms'].to_numpy(dtype=float)
            x_bytes = pd.to_numeric(joined['queue_sum_bytes'], errors='coerce').to_numpy(dtype=float)

            corr_d, r2_d, a_d, b_d, mae_d = _fit_stats(x_delay, y)
            corr_b, r2_b, a_b, b_b, mae_b = _fit_stats(x_bytes, y)

            summary_rows.append({
                'src_as': int(sa),
                'dst_as': int(da),
                'n': int(len(joined)),
                'base_rtt_ms': float(base_rtt_ms),
                'corr(extra_vs_queueDelay)': float(corr_d),
                'r2(extra~a*queueDelay+b)': float(r2_d),
                'slope_a_delay': float(a_d),
                'intercept_b_delay': float(b_d),
                'mae_ms_delay': float(mae_d),
                'corr(extra_vs_queueBytes)': float(corr_b),
                'r2(extra~a*queueBytes+b)': float(r2_b),
                'slope_a_bytes': float(a_b),
                'intercept_b_bytes': float(b_b),
                'mae_ms_bytes': float(mae_b),
            })

            joined = joined.assign(
                src_as=int(sa),
                dst_as=int(da),
                timestamp_s=joined['timestamp_ns'] / 1e9,
            )
            samples_all.append(joined)

            if plot_pair is not None and (int(sa), int(da)) == (int(plot_pair[0]), int(plot_pair[1])):
                plt.figure(figsize=(6, 4), dpi=300)
                plt.scatter(joined['queue_delay_pred_ms'], joined['extra_rtt_ms'], s=6, alpha=0.35)
                xs = np.linspace(float(np.nanmin(joined['queue_delay_pred_ms'])), float(np.nanmax(joined['queue_delay_pred_ms'])), 200)
                plt.plot(xs, a_d * xs + b_d, color='red', linewidth=2.0, label=f'fit: y={a_d:.2f}x+{b_d:.2f}; R2={r2_d:.2f}; r={corr_d:.2f}')
                plt.xlabel('Pred queueing delay (ms) = Σ(q/BW) along WAN path')
                plt.ylabel('Extra RTT (ms) = measured_rtt - base_rtt')
                plt.title(f'Linearity check: AS {sa}->{da} | baseRTT={base_rtt_ms:.3f}ms')
                plt.grid(True, linestyle='--', alpha=0.5)
                plt.legend(fontsize=9)
                plt.tight_layout()
                plt.show()

        summary_df = pd.DataFrame(summary_rows)
        if not summary_df.empty:
            summary_df = summary_df.sort_values(['r2(extra~a*queueDelay+b)', 'corr(extra_vs_queueDelay)'], ascending=False).reset_index(drop=True)
        samples_df = pd.concat(samples_all, axis=0, ignore_index=True) if samples_all else pd.DataFrame()
        return summary_df, samples_df

    def __read_accumulated_bytes_info(self):
        if self.accumulated_bytes_info is None:
            self.accumulated_bytes_info = pd.read_csv(op.join(self.dir, 'accumulated_bytes_log'))

    @auto_save_plot
    def plot_accumulated_bytes(self, src_as, dst_as):
        """绘制指定 switch_id 和 dst_as 的 accumulated_bytes 变化曲线"""
        self.__read_accumulated_bytes_info()
        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return
        df = self.accumulated_bytes_info[
            (self.accumulated_bytes_info['switch_id'] == switch_id) &
            (self.accumulated_bytes_info['dst_as'] == dst_as)
        ]
        if df.empty:
            print(f'No accumulated bytes info for switch {switch_id} and dst_as {dst_as}')
            return
        plt.figure(figsize=(10, 6))
        plt.plot(df['timestamp_ns'], df['accumulated_bytes'] / 1e3, label='Accumulated Bytes')
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.ylabel('Accumulated Bytes (KB)', fontsize=12)
        plt.title(f'Accumulated Bytes for Switch {switch_id} and dst_as {dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)


    def __read_cnp_info(self):
        if self.cnp_info is None:
            self.cnp_info = pd.read_csv(op.join(self.dir, 'cnp_log'))

    def __read_cnp_trigger_prob_info(self):
        if self.cnp_trigger_prob_info is None:
            self.cnp_trigger_prob_info = pd.read_csv(op.join(self.dir, 'cnp_trigger_prob_log'))

    @auto_save_plot
    def plot_cnp_timestamps(self, flow_id:int, start_time:float=2.0, end_time:float=2.05, bin_ms:float=1.0):
        """按时间槽统计 CNP 数量（折线图）"""
        self.__read_cnp_info()
        df = self.cnp_info[(self.cnp_info['flow_id'] == flow_id) &
                           (self.cnp_info['timestamp_ns'] >= start_time*1e9) &
                           (self.cnp_info['timestamp_ns'] <= end_time*1e9)]
        if df.empty:
            print(f'No CNP info for flow_id {flow_id}')
            return

        start_ns = int(start_time * 1e9)
        end_ns = int(end_time * 1e9)
        bin_ns = int(bin_ms * 1e6)
        if bin_ns <= 0:
            raise ValueError('bin_ms must be > 0')

        edges = np.arange(start_ns, end_ns + bin_ns, bin_ns)
        counts, _ = np.histogram(df['timestamp_ns'].to_numpy(), bins=edges)
        centers = (edges[:-1] + edges[1:]) / 2

        plt.figure(figsize=(10, 3))
        plt.plot(centers / 1e9, counts, linewidth=1.2)
        plt.xlabel('Time (s)', fontsize=12)
        plt.ylabel(f'CNP count / {bin_ms:g} ms', fontsize=12)
        plt.title(f'CNP Counts for Flow {flow_id}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)

    @auto_save_plot
    def plot_cnp_trigger_prob(self, src_as:int, dst_as:int, ewma_span:int=1):
        """绘制 epoch 粒度的 CNP 触发概率：prob = cnp_cnt / pkt_cnt"""
        self.__read_cnp_trigger_prob_info()

        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return

        df = self.cnp_trigger_prob_info[
            (self.cnp_trigger_prob_info['switch_id'] == switch_id) &
            (self.cnp_trigger_prob_info['src_as'] == src_as) &
            (self.cnp_trigger_prob_info['dst_as'] == dst_as)
        ].sort_values('timestamp_ns')
        if df.empty:
            print(f'No cnp_trigger_prob_log for {src_as}->{dst_as} (switch {switch_id})')
            return

        prob = df['prob']
        if ewma_span and ewma_span > 1:
            prob = prob.ewm(span=ewma_span, adjust=False).mean()

        plt.figure(figsize=(5, 4), dpi=300)
        plt.plot(df['timestamp_ns'] / 1e9, prob, label='CNP trigger prob')
        xlabel_kwargs = {'fontproperties': font_prop} if font_prop is not None else {}
        plt.xlabel('Time (s)', fontsize=14, **xlabel_kwargs)
        plt.ylabel('prob', fontsize=14, **xlabel_kwargs)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

    @auto_save_plot
    def plot_as_rate(self, src_as, dst_as):
        """绘制AS间的real_rate和ref_rate对比图"""
        self.__read_as_rate_info()
        df = self.as_rate_info[
            (self.as_rate_info['src_as'] == src_as) & 
            (self.as_rate_info['dst_as'] == dst_as)
        ]
        if df.empty:
            print(f'No rate info for AS {src_as}->{dst_as}')
            return
            
        plt.figure(figsize=(5, 4), dpi=300)
        plt.plot(df['timestamp_ns'] / 1e9, df['real_rate'] / 1e9, label='Real Rate', color='blue')
        plt.plot(df['timestamp_ns'] / 1e9, df['ref_rate'] / 1e9, label='Base Rate', color='red', linestyle='--')
        plt.xlabel('Time (s)', fontsize=14)
        plt.ylabel('Rate (GB/s)', fontsize=14)
        #plt.title(f'DC Rate Monitor: {src_as}->{dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

    @auto_save_plot
    def plot_qp_rate(self, flow_ids: List[int]):
        """绘制多个 flow_id 的速率折线图，每个 flow 一条曲线"""
        self.__read_qp_rate_info()
        plt.figure(figsize=(5, 4), dpi=300)
        for flow_id in flow_ids:
            df = self.qp_rate_info[self.qp_rate_info['flow_id'] == flow_id]
            if df.empty:
                print(f'No QP rate info for flow_id {flow_id}')
                continue
            if len(flow_ids) == 1:
                fig, ax1 = plt.subplots(figsize=(5, 4), dpi=300)
                ax1.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9 * 8, label=f'Flow {flow_id}')
                #ax1.plot(df['timestamp_ns'] / 1e9, df['target_rate'] / 1e9, label='Target Rate', linestyle='--')
                ax1.set_xlabel('Timestamp (s)', fontsize=22)
                ax1.set_ylabel('Rate (Gbps)', fontsize=22)
                ax1.tick_params(axis='both', which='major', labelsize=18)
                ax1.set_ylim(0,100)
                ax1.set_xlim(1.98,2.8)
                fig.gca().spines['top'].set_visible(False)
                fig.gca().spines['right'].set_visible(False)
                fig.savefig('motivation2.pdf', bbox_inches='tight')
                #ax2 = ax1.twinx()
                #ax2.plot(df['timestamp_ns'] / 1e9, df['alpha'], label='Alpha', linestyle=':', color='orange')
                #ax2.set_ylabel('Alpha', fontsize=22)
                return
            else:
                plt.plot(df['timestamp_ns'] / 1e9, df['rate'] / 1e9, label=f'Flow {flow_id}')
        plt.xlabel('Time (s)', fontsize=14)
        plt.ylabel('Rate (GB/s)', fontsize=14)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        #plt.title('QP Rate for Selected Flows', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=13)

    @auto_save_plot
    def plot_rtt(self, src_as, dst_as):
        self.__read_rtt_info()
        for as_obj in self.topo['as_topologies']:
            if as_obj['as_id'] == src_as:
                switch_id = as_obj['dci_switch']
                break
        else:
            print(f'No switch found for src_as {src_as}')
            return
        df = self.rtt_info[(self.rtt_info['switch_id']==switch_id)&(self.rtt_info['dst_as']==dst_as)]
        if df.empty:
            print(f'No RTT info for switch {switch_id} and dst_as {dst_as}')
            return
        plt.figure(figsize=(8, 5))
        for nxt, grp in df.groupby('next_hop'):
            plt.plot(grp['timestamp_ns'], grp['rtt1_ms'], label=f'{nxt}-Sens', linestyle='-', marker='.', markersize=4)
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.ylabel('RTT (ms)', fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=10)

    def get_avg_abs_rtt_diff(
        self,
        *,
        switch_id: int | None = None,
        dst_as: int | None = None,
        next_hop: int | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        use_rtt_col: str = 'rtt1_ms',
        use_measured_col: str = 'measured_rtt_ms',
    ) -> float:
        """返回 rtt_info 中 |rtt1_ms - measured_rtt_ms| 的平均值。

        可选按 switch_id/dst_as/next_hop 以及时间窗过滤。
        """
        self.__read_rtt_info()
        df = self.rtt_info

        missing = [c for c in (use_rtt_col, use_measured_col, 'timestamp_ns') if c not in df.columns]
        if missing:
            raise KeyError(f"rtt_log missing columns: {missing}; got {list(df.columns)}")

        if switch_id is not None:
            df = df[df['switch_id'] == int(switch_id)]
        if dst_as is not None:
            df = df[df['dst_as'] == int(dst_as)]
        if next_hop is not None:
            df = df[df['next_hop'] == int(next_hop)]
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= float(start_time_s) * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= float(end_time_s) * 1e9]

        if df.empty:
            return float('nan')

        a = pd.to_numeric(df[use_rtt_col], errors='coerce')
        b = pd.to_numeric(df[use_measured_col], errors='coerce')
        diff = (a - b).abs().dropna()
        if diff.empty:
            return float('nan')
        return float(diff.mean())

    @auto_save_plot
    def plot_fct_cdf(self):
        self.__read_flow_info()
        def _plot(series, label, color):
            if series.empty: return
            sorted_vals = np.sort(series)
            y = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
            plt.plot(sorted_vals, y, label=label, color=color)
        flow_df = self.flow_df
        _plot(flow_df['fct_slowdown'], 'Overall', 'blue')
        _plot(self.get_intra_df()['fct_slowdown'], 'Intra', 'green')
        _plot(self.get_inter_df()['fct_slowdown'], 'Inter', 'red')
        plt.grid(True, ls='--', alpha=.7)
        plt.xlabel('FCT Slowdown')
        plt.ylabel('CDF')
        plt.legend()
        plt.xscale('log')
        plt.ylim(0, 1.05)

    @auto_save_plot
    def plot_drop(self, switch_id, src_as, dst_as):
        """绘制丢包散点图（改为 plt 接口）"""
        self.__read_drop_info()
        df = self.drop_info[
            (self.drop_info['switch_id']==switch_id)&
            (self.drop_info['src_as']==src_as)&
            (self.drop_info['dst_as']==dst_as)
        ]
        if df.empty:
            print(f'No drop info for switch {switch_id}, {src_as}->{dst_as}')
            return
        plt.figure(figsize=(8, 5))
        times = df['timestamp_ns']
        plt.scatter(times, np.zeros_like(times), alpha=0.6, s=50)
        plt.xlabel('Timestamp (ns)', fontsize=12)
        plt.title(f'Drop Events: switch {switch_id}, src_as {src_as}, dst_as {dst_as}', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.7)

    def show_drop(self):
        self.__read_drop_info()
        grouped = self.drop_info.groupby(['switch_id', 'src_as', 'dst_as']).size()
        for (switch_id, src_as, dst_as), count in grouped.items():
            print(f'Switch ID: {switch_id}, Src AS: {src_as}, Dst AS: {dst_as}, Drop Count: {count}')

    def get_drop_number(self):
        self.__read_drop_info()
        return len(self.drop_info)
    
    def get_drop_rate(self):
        drop_cnt = self.get_drop_number()
        self.__read_flow_info()

        total_cnt = np.ceil(self.flow_df['fsize'] / 1000).sum()
        return drop_cnt/total_cnt

    @auto_save_plot
    def plot_link_utilization(self, src_id, dst_id, monitor_interval=500e-6, smooth_window=1):
        self.__read_link_info()
        series = (
            self.link_info[
                (self.link_info['src_id']==src_id)&
                (self.link_info['dst_id']==dst_id)
            ]
            .groupby('timestamp_ns')['bytes']
            .sum()
            .sort_index()
        )
        if series.empty:
            print(f'No link info for {src_id}->{dst_id}')
            return
        series /= monitor_interval
        series = series.rolling(smooth_window, center=True).mean()
        plt.figure()
        plt.plot(series.index, series.values / 1e9)
        plt.xlabel('Timestamp (ns)')
        plt.ylabel('GB/s')
        plt.title(f'Link Utilization {src_id}->{dst_id}')

    @auto_save_plot
    def plot_buffer(self, switch_id, egress=True):
        self.__read_buffer_info()
        df = self.buffer_info[
            (self.buffer_info['switch_id']==switch_id)
        ]
        if df.empty:
            print(f'No buffer info for switch {switch_id}')
            return
     
        col = 'egress_bytes' if egress else 'ingress_bytes'
        df = df[['timestamp_ns', 'next_hop', col]].rename(columns={col: 'bytes'})
        plt.figure(figsize=(5,4), dpi=300)
        for next_hop, group in df.groupby('next_hop'):
            plt.plot(group['timestamp_ns'] / 1e9, group['bytes'] / 1e6, label=f'Hop {next_hop}')
        plt.xlabel('Timestamp (s)', fontsize=16)
        plt.ylabel('Queue Length (MB)', fontsize=16)
        plt.title(f"Buffer Utilization switch {switch_id}, {'egress' if egress else 'ingress'}")
        plt.legend()

    @auto_save_plot
    def plot_pfc(self, node):
        """绘制指定 node 和 nbr 的 PFC 时间轴"""
        if self.pfc_info is None:
            self.pfc_info = pd.read_csv(op.join(self.dir, 'pfc_file'))
        plt.figure(figsize=(8, 4))
        y = 1
        y_tickets = []
        for nbr, df in self.pfc_info[(self.pfc_info['node_id'] == node) \
                                      & (self.pfc_info['is_pause'] == 1)].groupby('nbr_id'):
            plt.scatter(df['timestamp_ns'] / 1e9, np.ones(len(df)) *y, label=nbr, s=1)
            y += 1
            y_tickets.append(nbr)
        plt.yticks(range(1, y), y_tickets)
        plt.xlabel('Timestamp (s)', fontsize=12)
        plt.title(f'PFC Timeline: node {node}')
        plt.legend()
        plt.tight_layout()

    def print_info(self):
        print(f'===ID:{self.id}===')

    def get_avg_fct(self):
        self.__read_flow_info()
        return (
            self.flow_df['fct_slowdown'].mean(),
            self.get_intra_df()['fct_slowdown'].mean(),
            self.get_inter_df()['fct_slowdown'].mean()
        )

    def get_p99_fct(self):
        self.__read_flow_info()
        return (
            self.flow_df['fct_slowdown'].quantile(.99),
            self.get_intra_df()['fct_slowdown'].quantile(.99),
            self.get_inter_df()['fct_slowdown'].quantile(.99)
        )
    
    def get_large_flow_fct(self):
        self.__read_flow_info()
        df = self.get_large_flow_df().copy()
        return ( df['fct_slowdown'].mean(), 
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].mean(),
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].quantile(.99), 
                df[ df['src_as'] == df['dst_as'] ]['fct_slowdown'].mean())
    
    def get_small_flow_fct(self):
        self.__read_flow_info()
        df = self.get_small_flow_df().copy()
        return ( df['fct_slowdown'].mean(), 
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].mean(),
                df[ df['src_as'] != df['dst_as'] ]['fct_slowdown'].quantile(.99), 
                df[ df['src_as'] == df['dst_as'] ]['fct_slowdown'].mean())
    
    def get_buffer_information(self):
        self.__read_buffer_info()
        df = self.buffer_info[
            (self.buffer_info['timestamp_ns'] >= 2010000000) & (self.buffer_info['timestamp_ns'] <= 2100000000)
        ].groupby(['timestamp_ns', 'switch_id'])['egress_bytes'].sum().reset_index()
        return df['egress_bytes'].mean()

    def get_wan_buffer_stats(self):
        """
        Returns (mean, p99) of buffer occupancy (egress_bytes) for WAN switches.
        aggregated over all queues and time.
        """
        self.__read_buffer_info()
        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        if not wan_set:
            return (0.0, 0.0)

        df = self.buffer_info[self.buffer_info['switch_id'].isin(wan_set)]
        if df.empty:
            return (0.0, 0.0)
            
        # Each row is a queue sample.
        # We calculate statistics across all samples (all queues, all times).
        # Convert to MB
        return df['egress_bytes'].mean() / 1e6, df['egress_bytes'].quantile(0.99) / 1e6


    def get_fct(self):
        return (self.get_avg_fct(), self.get_p99_fct())
    
    def diagnose_slow_flow(self, threshold=99):
        """
        Diagnoses slow flows based on a given threshold for the 'fct_slowdown' column.
        """
        self.__read_flow_info()
        slow_df = self.get_inter_df().copy()
        
        # Get the 99th percentile of the 'fct_slowdown' column
        cutoff = slow_df['fct_slowdown'].quantile(0.99)
        slow_df = slow_df[slow_df['fct_slowdown'] > cutoff]

        start_time = self.flow_df['start_time'].min()
        end_time = self.flow_df['finish_time'].max()

        # Define time bins (time steps) based on the given range
        time_bins = np.arange(start_time, end_time, 1e-4)  # 每秒一个时间点 
        
        plt.figure(figsize=(5, 4))
        
        # Grouping by source AS and destination AS
        for (src_as, dst_as), group in slow_df.groupby(['src_as', 'dst_as']):
            # Binning start and end times of each flow
            start_bin_indices = np.digitize(group['start_time'], time_bins) - 1
            end_bin_indices = np.digitize(group['finish_time'], time_bins) - 1

            # Efficiently counting overlaps using a histogram-like approach
            counts = np.zeros(len(time_bins) - 1, dtype=int)
            
            # For each flow, increment the bins it starts and ends in
            for start_bin, end_bin in zip(start_bin_indices, end_bin_indices):
                counts[start_bin:end_bin + 1] += 1  # Increment the bins that overlap with this flow
            
            # Create DataFrame for the result
            result_df = pd.DataFrame({'Time Bin': time_bins[:-1], 'Count': counts})
            
            # Plotting
            plt.plot(time_bins[:-1], counts, label=f'{src_as}->{dst_as}')
        
        plt.title('Heatmap of Overlapping Intervals in Time Bins')
        plt.legend()
        plt.tight_layout()

        # 选出最慢的20条流并展示
        top20 = slow_df.sort_values('fct_slowdown', ascending=False).head(20)
        display(top20[['flow_id', 'src', 'dst', 'fct_slowdown', 'start_time', 'finish_time', 'src_as', 'dst_as']])
        


    def __read_rtt_info(self):
        if self.rtt_info is None:
            self.rtt_info = pd.read_csv(op.join(self.dir, 'rtt_log'))

    def __read_flow_info(self):
        if self.flow_df is not None:
            return
        with open(op.join(self.dir, 'flow_output'), 'r') as f:
            raw = json.load(f)
        host2as = {}
        for as_obj in self.topo['as_topologies']:
            for host in as_obj['hosts']:
                host2as[host] = as_obj["as_id"]
        df = pd.DataFrame(raw)
        df['fct_slowdown'] = (df['finish_time'] - df['start_time']) / df['std_fct']
        df['src_as']        = df['src'].apply(lambda x : host2as[x])
        df['dst_as']        = df['dst'].apply(lambda x : host2as[x])
        self.flow_df = df

    def get_intra_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['src_as'] == self.flow_df['dst_as']]

    def get_inter_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['src_as'] != self.flow_df['dst_as']]
    
    def get_large_flow_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['fsize'] >= 5000000]
    
    def get_small_flow_df(self):
        self.__read_flow_info()
        return self.flow_df[self.flow_df['fsize'] < 1000000]

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is None:
            self.drop_info = pd.read_csv(op.join(self.dir,'drop_log'))
            self.drop_info['src_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].src_as if x in self.id_to_flow else None)
            self.drop_info['dst_as'] = self.drop_info['flow_id'].map(lambda x: self.id_to_flow[x].dst_as if x in self.id_to_flow else None)

    def __read_drop_info(self):
        self.__read_flow_info()
        if self.drop_info is None:
            self.drop_info = pd.read_csv(op.join(self.dir, 'drop_log'))
            self.drop_info = self.drop_info.merge(
                self.flow_df[['flow_id', 'src_as', 'dst_as']],
                on='flow_id', how='left'
            )

    def __read_link_info(self):
        if self.link_info is None:
            self.link_info = pd.read_csv(op.join(self.dir,'link_utilization'))

    def __read_buffer_info(self):
        if self.buffer_info is None:
            self.buffer_info = pd.read_csv(op.join(self.dir,'buffer_monitor'))

    def wan_high_buffer_intervals(
        self,
        *,
        quantile: float = 0.90,
        direction: str = 'both',
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        min_duration_s: float = 0.0,
        max_gap_s: float | None = None,
        return_samples: bool = False,
    ) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
        """找出 WAN 交换机在“哪些时间段、哪些队列(端口->next_hop)”buffer 占用非常高。

        - 把所有时刻、所有 WAN 交换机、所有队列的 used_bytes 收集
        - 取 used_bytes 的 quantile 作为阈值
        - 对每条队列，输出超过阈值的连续时间段 (t_start,t_end)

        参数：
        - quantile: 分位数阈值，例如 0.9 表示 >= P90（最拥挤 10%）
        - direction: 'ingress'|'egress'|'both'
        - start_time_s/end_time_s: 时间窗过滤（秒）
        - min_duration_s: 过滤太短的事件段
        - max_gap_s: 允许把相邻采样点合并为同一段的最大间隔（默认用 SW_MONITORING_INTERVAL*1.5）
        - return_samples: True 时额外返回筛选后的采样（便于自定义画图）

        返回：events_df（每行一个高占用时间段）；可选 (events_df, samples_df)
        """
        self.__read_buffer_info()

        if not (0.0 < float(quantile) <= 1.0):
            raise ValueError('quantile must be in (0,1]')

        direction = str(direction).lower().strip()
        if direction not in {'ingress', 'egress', 'both'}:
            raise ValueError("direction must be 'ingress', 'egress', or 'both'")

        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        if not wan_set:
            raise ValueError('topology has no wan_switches')

        df = self.buffer_info.copy()
        df = df[df['switch_id'].isin(wan_set)]
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= start_time_s * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= end_time_s * 1e9]
        if df.empty:
            events = pd.DataFrame(
                columns=[
                    'switch_id', 'next_hop', 'direction',
                    't_start_s', 't_end_s', 'duration_s',
                    'peak_bytes', 't_peak_s',
                    'threshold_bytes', 'quantile'
                ]
            )
            return (events, df) if return_samples else events

        # default continuity gap from SW_MONITORING_INTERVAL
        try:
            interval_ns = int(float(self.config.get('SW_MONITORING_INTERVAL', 0)))
        except Exception:
            interval_ns = 0
        if max_gap_s is None:
            max_gap_ns = int(interval_ns * 1.5) if interval_ns > 0 else 0
        else:
            max_gap_ns = int(float(max_gap_s) * 1e9)

        # long-form samples
        samples: list[pd.DataFrame] = []
        if direction in {'ingress', 'both'}:
            s = df[['timestamp_ns', 'switch_id', 'next_hop', 'ingress_bytes']].copy()
            s = s.rename(columns={'ingress_bytes': 'used_bytes'})
            s['direction'] = 'ingress'
            samples.append(s)
        if direction in {'egress', 'both'}:
            s = df[['timestamp_ns', 'switch_id', 'next_hop', 'egress_bytes']].copy()
            s = s.rename(columns={'egress_bytes': 'used_bytes'})
            s['direction'] = 'egress'
            samples.append(s)
        samples_df = pd.concat(samples, axis=0, ignore_index=True)

        # Deduplicate: keep max usage for a (queue,time)
        samples_df = (
            samples_df
            .groupby(['timestamp_ns', 'switch_id', 'next_hop', 'direction'], as_index=False)['used_bytes']
            .max()
        )

        threshold_bytes = float(samples_df['used_bytes'].quantile(float(quantile)))
        samples_df['over'] = samples_df['used_bytes'] >= threshold_bytes
        samples_df = samples_df.sort_values(['switch_id', 'next_hop', 'direction', 'timestamp_ns']).reset_index(drop=True)

        events: list[dict] = []
        min_dur_ns = int(float(min_duration_s) * 1e9)
        for (sw, nh, d), g in samples_df.groupby(['switch_id', 'next_hop', 'direction'], sort=False):
            ts = g['timestamp_ns'].to_numpy()
            used = g['used_bytes'].to_numpy()
            over = g['over'].to_numpy()

            in_seg = False
            seg_start_i = 0
            last_over_ts = 0
            seg_peak_i = 0
            for i in range(len(g)):
                if over[i]:
                    if not in_seg:
                        in_seg = True
                        seg_start_i = i
                        seg_peak_i = i
                    else:
                        if max_gap_ns > 0 and (ts[i] - last_over_ts) > max_gap_ns:
                            start_ts = ts[seg_start_i]
                            end_ts = last_over_ts
                            if end_ts - start_ts >= min_dur_ns:
                                events.append({
                                    'switch_id': int(sw),
                                    'next_hop': int(nh),
                                    'direction': d,
                                    't_start_s': float(start_ts / 1e9),
                                    't_end_s': float(end_ts / 1e9),
                                    'duration_s': float((end_ts - start_ts) / 1e9),
                                    'peak_bytes': int(used[seg_peak_i]),
                                    't_peak_s': float(ts[seg_peak_i] / 1e9),
                                    'threshold_bytes': float(threshold_bytes),
                                    'quantile': float(quantile),
                                })
                            seg_start_i = i
                            seg_peak_i = i

                    if used[i] >= used[seg_peak_i]:
                        seg_peak_i = i
                    last_over_ts = ts[i]
                else:
                    if in_seg:
                        start_ts = ts[seg_start_i]
                        end_ts = last_over_ts
                        if end_ts - start_ts >= min_dur_ns:
                            events.append({
                                'switch_id': int(sw),
                                'next_hop': int(nh),
                                'direction': d,
                                't_start_s': float(start_ts / 1e9),
                                't_end_s': float(end_ts / 1e9),
                                'duration_s': float((end_ts - start_ts) / 1e9),
                                'peak_bytes': int(used[seg_peak_i]),
                                't_peak_s': float(ts[seg_peak_i] / 1e9),
                                'threshold_bytes': float(threshold_bytes),
                                'quantile': float(quantile),
                            })
                        in_seg = False

            if in_seg:
                start_ts = ts[seg_start_i]
                end_ts = last_over_ts
                if end_ts - start_ts >= min_dur_ns:
                    events.append({
                        'switch_id': int(sw),
                        'next_hop': int(nh),
                        'direction': d,
                        't_start_s': float(start_ts / 1e9),
                        't_end_s': float(end_ts / 1e9),
                        'duration_s': float((end_ts - start_ts) / 1e9),
                        'peak_bytes': int(used[seg_peak_i]),
                        't_peak_s': float(ts[seg_peak_i] / 1e9),
                        'threshold_bytes': float(threshold_bytes),
                        'quantile': float(quantile),
                    })

        events_df = pd.DataFrame(events)
        if not events_df.empty:
            events_df = events_df.sort_values(['t_start_s', 'switch_id', 'peak_bytes'], ascending=[True, True, False]).reset_index(drop=True)

        return (events_df, samples_df) if return_samples else events_df

    def _get_dci_switch_id(self, as_id: int) -> int:
        for as_obj in self.topo.get('as_topologies', []):
            if int(as_obj.get('as_id')) == int(as_id):
                return int(as_obj.get('dci_switch'))
        raise ValueError(f'No dci_switch found for as_id {as_id}')

    def _build_wan_graph(self) -> dict[int, set[int]]:
        graph: dict[int, set[int]] = defaultdict(set)
        for link in self.topo.get('wan_links', []):
            u = int(link['src'])
            v = int(link['dst'])
            graph[u].add(v)
            graph[v].add(u)
        return graph

    def _shortest_path(self, graph: dict[int, set[int]], src: int, dst: int) -> list[int]:
        if src == dst:
            return [src]
        q = [src]
        prev: dict[int, int | None] = {src: None}
        for u in q:
            for v in graph.get(u, []):
                if v in prev:
                    continue
                prev[v] = u
                if v == dst:
                    q = []
                    break
                q.append(v)

        if dst not in prev:
            return []
        path = [dst]
        cur = dst
        while prev[cur] is not None:
            cur = prev[cur]
            path.append(cur)
        path.reverse()
        return path

    def get_wan_key_path(self, src_as: int, dst_as: int) -> list[int]:
        """Return hop-minimal WAN path between src_as's and dst_as's DCI switches (node id list)."""
        src = self._get_dci_switch_id(src_as)
        dst = self._get_dci_switch_id(dst_as)
        graph = self._build_wan_graph()
        return self._shortest_path(graph, src, dst)

    @auto_save_plot
    def plot_wan_path_buffer(
        self,
        src_as: int,
        dst_as: int,
        *,
        egress: bool = True,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        unit: str = 'MB',
    ):
        """Plot per-hop WAN queue length overlay along the shortest WAN path."""
        self.__read_buffer_info()

        path = self.get_wan_key_path(src_as, dst_as)
        if not path or len(path) < 2:
            print(f'No WAN path found for AS {src_as}->{dst_as}')
            return

        wan_set = set(map(int, self.topo.get('wan_switches', [])))
        col = 'egress_bytes' if egress else 'ingress_bytes'

        df = self.buffer_info.copy()
        if start_time_s is not None:
            df = df[df['timestamp_ns'] >= start_time_s * 1e9]
        if end_time_s is not None:
            df = df[df['timestamp_ns'] <= end_time_s * 1e9]
        if df.empty:
            print('No buffer_monitor samples in the selected time range')
            return

        unit = str(unit).upper()
        if unit == 'B':
            scale = 1.0
        elif unit == 'KB':
            scale = 1e3
        elif unit == 'MB':
            scale = 1e6
        elif unit == 'GB':
            scale = 1e9
        else:
            print(f'Unknown unit {unit}, fallback to MB')
            scale = 1e6
            unit = 'MB'

        hop_series: dict[str, pd.Series] = {}
        for u, v in zip(path[:-1], path[1:]):
            # only plot WAN switch queues
            if int(u) not in wan_set:
                continue
            hop_df = df[(df['switch_id'] == int(u)) & (df['next_hop'] == int(v))]
            if hop_df.empty:
                continue
            series = (
                hop_df.groupby('timestamp_ns')[col]
                .mean()
                .sort_index()
                / scale
            )
            hop_series[f'{u}->{v}'] = series

        if not hop_series:
            print(f'No WAN-hop buffer data found on path: {path}')
            return

        aligned = pd.concat(hop_series, axis=1).ffill().fillna(0.0)
        total = aligned.sum(axis=1)

        plt.figure(figsize=(10, 5))
        x = aligned.index / 1e9
        for label, series in aligned.items():
            plt.plot(x, series.values, linewidth=1.0, label=label)
        plt.plot(x, total.values, linewidth=2.0, color='black', label='SUM')
        plt.xlabel('Timestamp (s)', fontsize=12)
        plt.ylabel(f'Queue ({unit})', fontsize=12)
        plt.title(f'WAN path buffer: AS {src_as}->{dst_as} | path {path}')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend(fontsize=9, ncol=2)

    def __read_qp_rate_info(self):
        if self.qp_rate_info is None:
            self.qp_rate_info = pd.read_csv(op.join(self.dir,'qp_rate_log'))

    def __read_as_rate_info(self):
        if self.as_rate_info is None:
            self.as_rate_info = pd.read_csv(op.join(self.dir, 'rate_monitor'))

    def read_config(self):
        with open(op.join(self.dir, 'config.txt')) as f:
            lines = f.readlines()
            lines = [l.strip() for l in lines if l.strip()]
            self.config = {}
            for line in lines:
                parts = line.split(maxsplit=1)
                self.config[parts[0]] = parts[1] if len(parts) > 1 else ''

    def rtt_detail(self):
        file_path = op.join(self.dir, 'wan_log')
        time_vals = []
        rtt_vals = []
        sensitive_rtt_vals = []
        # 读取并解析文件
        with open(file_path, 'r') as f:
            for line in f:
                try:
                    parts = line.strip().split(',')
                    now = float(parts[0].split(':')[1])
                    rtt = float(parts[1].split(':')[1])
                    sensitive_rtt = float(parts[2].split(':')[1])
                    # count = int(parts[3].split(':')[1])  # 可选

                    time_vals.append(now)
                    rtt_vals.append(rtt)
                    sensitive_rtt_vals.append(sensitive_rtt)
                except (IndexError, ValueError):
                    print(f"Skipping invalid line: {line}")

        # 绘图
        plt.figure(figsize=(12, 4), dpi=300)
        plt.scatter(time_vals, rtt_vals, label='RTT', s=2)
        plt.plot(time_vals, sensitive_rtt_vals, label='Sensitive RTT', linestyle='--', color='orange')

        plt.xlabel('Time (Now)')
        plt.ylabel('RTT Value')
        plt.title('RTT and Sensitive RTT Over Time')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()

    def analyze_cnp_k(self, w_max=4, start_time=2.01, end_time=2.1):
        """
        Calculates x = prob^0.75 * RefRate and finds optimal k such that k*x falls in [1, w_max].
        """
        self.__read_cnp_trigger_prob_info()
        self.__read_as_rate_info()
        
        t_start_ns = start_time * 1e9
        t_end_ns = end_time * 1e9
        
        # 1. Filter by time
        cnp_df = self.cnp_trigger_prob_info[
            (self.cnp_trigger_prob_info['timestamp_ns'] >= t_start_ns) & 
            (self.cnp_trigger_prob_info['timestamp_ns'] <= t_end_ns)
        ].copy()
        
        rate_df = self.as_rate_info[
            (self.as_rate_info['timestamp_ns'] >= t_start_ns) & 
            (self.as_rate_info['timestamp_ns'] <= t_end_ns)
        ].copy()

        if cnp_df.empty or rate_df.empty:
            print("No data in the specified time range.")
            return

        # 2. Map RefRate to CNP info
        # Map src_as to its DCI switch
        as_to_switch = {}
        for as_obj in self.topo['as_topologies']:
            as_to_switch[as_obj['as_id']] = as_obj['dci_switch']
        
        cnp_df['expected_switch'] = cnp_df['src_as'].map(as_to_switch)
        cnp_df = cnp_df[cnp_df['switch_id'] == cnp_df['expected_switch']]
        
        cnp_df = cnp_df.sort_values('timestamp_ns')
        rate_df = rate_df.sort_values('timestamp_ns')
        
        # Merge using asof
        merged_frames = []
        for (src, dst), group_cnp in cnp_df.groupby(['src_as', 'dst_as']):
            group_rate = rate_df[(rate_df['src_as'] == src) & (rate_df['dst_as'] == dst)]
            if group_rate.empty:
                continue
            
            # Using 2ms tolerance for matching
            # Timestamp is int64 (ns), so tolerance must be int
            merged = pd.merge_asof(
                group_cnp, 
                group_rate[['timestamp_ns', 'ref_rate']], 
                on='timestamp_ns', 
                direction='nearest',
                tolerance=int(2e6)
            )
            merged_frames.append(merged)
            
        if not merged_frames:
            print("Could not merge CNP and Rate data.")
            return
            
        full_df = pd.concat(merged_frames)
        full_df = full_df.dropna(subset=['ref_rate'])
        
        # 3. Calculate x = prob^0.75 * RefRate
        full_df['x'] = (full_df['prob'] ** 0.75) * full_df['ref_rate']
        
        # Filter valid x > 0
        valid_x = full_df[full_df['x'] > 1e-9]['x'].values
        
        if len(valid_x) == 0:
            print("No valid positive x values found.")
            return

        print(f"Total valid samples: {len(valid_x)}")
        
        # 4. Find Optimal k (Max Stabbing Query / Interval Problem)
        # For each x, valid k interval is [1/x, w_max/x]
        events = []
        for x_val in valid_x:
            l = 1.0 / x_val
            r = float(w_max) / x_val
            events.append((l, 1))
            events.append((r, -1))
        
        # Sort events by value, then type (process start (+1) before end (-1) if values equal for closed interval overlap logic, 
        # but actually for max points in [1, w_max], if k is exactly at boundary, it counts.
        # If we encounter End of one interval and Start of another at same K, ideally count should not drop then rise.
        # But standard way is fine for finding max.
        events.sort(key=lambda x: (x[0], -x[1])) 
        
        max_overlap = 0
        best_k = 0
        current_overlap = 0
        
        # We need to potentially check the interval between events, but since optimal k must start at some 1/x,
        # checking event points is sufficient.
        for val, type in events:
            current_overlap += type
            if current_overlap > max_overlap:
                max_overlap = current_overlap
                best_k = val 
        
        print(f"Optimal k: {best_k:.4e}")
        print(f"Max samples in range [1, {w_max}]: {max_overlap} ({max_overlap/len(valid_x)*100:.2f}%)")
        
        # 5. Plotting
        plt.figure(figsize=(12, 6))
        
        # Subplot 1: Distribution of log10(x)
        plt.subplot(1, 2, 1)
        # Use log scale because x = prob * Rate can span orders of magnitude
        log_x = np.log10(valid_x)
        plt.hist(log_x, bins=50, color='skyblue', edgecolor='black', alpha=0.7)
        plt.title('Distribution of log10(x)\n(x = prob^0.75 * RefRate)')
        plt.xlabel('log10(x)')
        plt.ylabel('Count')
        plt.grid(True, linestyle='--', alpha=0.5)
        
        # Subplot 2: Distribution of k*x
        plt.subplot(1, 2, 2)
        adjusted_x = valid_x * best_k
        # Plot in log scale for X axis to see [1, 4] clearly if data spans widely
        # But request implies [1, 4] is the target linear range.
        # Let's clip visual range or just show histogram around [0, w_max*2]
        plt.hist(adjusted_x, bins=100, range=(0, w_max * 2), color='orange', edgecolor='black', alpha=0.7, label='k*x')
        plt.axvline(1, color='red', linestyle='--', linewidth=2, label='Lower (1)')
        plt.axvline(w_max, color='green', linestyle='--', linewidth=2, label=f'Upper ({w_max})')
        plt.title(f'Distribution of k*x (k={best_k:.2e})\nCoverage: {max_overlap/len(valid_x)*100:.1f}%')
        plt.xlabel('k * x')
        plt.ylabel('Count')
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.5)
        
        save_name = f'cnp_k_analysis_{self.id}_w{w_max}.pdf'
        plt.tight_layout()
        plt.savefig(save_name)
        print(f"Plot saved to {save_name}")
        plt.close()
        
        return best_k

_instances: Dict[str, Analyser] = {}
def get_analyser(id) -> Analyser:
    if str(id) not in _instances:
        _instances[str(id)] = Analyser(id)
    return _instances[str(id)]

def convert_str_to_id(config_ids_str: str) -> List[int]:
    ids = []
    for part in config_ids_str.split(','):
        if '-' in part:
            a, b = map(int, part.split('-'))
            ids.extend(range(a, b+1))
        else:
            ids.append(int(part))
    return ids

def analyser_iter(config_ids_str: str) -> Generator[Analyser, None, None]:
    for i in convert_str_to_id(config_ids_str):
        try:
            yield get_analyser(i)
        except Exception as e:
            print(f'{i}号实验数据异常：{e}')
            traceback.print_exc()

def clear_data(config_ids_str: str):
    dirs = []
    for ana in analyser_iter(config_ids_str):
        dirs.append(ana.dir)
        print(ana.dir)
    if input('press y to delete these data') == 'y':
        for d in dirs:
            os.system(f'rm -r {d}')

def show_fct(config_ids_str: str):
    for ana in analyser_iter(config_ids_str):
        ana.print_info()
        avg, intra, inter = ana.get_avg_fct()
        print(f'[{ana.id}]Avg FCT: {avg:.2f}, Intra: {intra:.2f}, Inter: {inter:.2f}')
        p99, p99_intra, p99_inter = ana.get_p99_fct()
        print(f'[{ana.id}]P99 FCT: {p99:.2f}, Intra: {p99_intra:.2f}, Inter: {p99_inter:.2f}')

def batch_operation(config_ids_str: str, func_name: str, *args):
    for ana in analyser_iter(config_ids_str):
        func = getattr(ana, func_name)
        print(f'[{ana.id}] {func_name}({args})')
        func(*args)

def get_basic_result(config_ids_str: str):
    results = []
    for ana in analyser_iter(config_ids_str):
        try:
            msg = ana.config.get('MSG', '')
            if msg == 'MSG':
                msg = ''
            avg_vals, avg_intra, avg_inter = ana.get_avg_fct()
            p99_vals, p99_intra, p99_inter = ana.get_p99_fct()
            results.append({
                'ID': ana.id,
                'MSG': msg,
                'Avg_FCT': avg_vals,
                'Avg_Intra_FCT': avg_intra,
                'Avg_Inter_FCT': avg_inter,
                'P99_FCT': p99_vals,
                'P99_Intra_FCT': p99_intra,
                'P99_Inter_FCT': p99_inter,
            })
        except Exception as e:
            print(f'Error processing {ana.id}: {e}')
    df = pd.DataFrame(results)
    return df
        
def plot_motivation_expr():
    a = get_analyser(40)
    b = get_analyser(41)
    plt.figure(figsize=(5, 4), dpi=300)
    plot_cdf(a.get_inter_df()['fct_slowdown'], label='Disable-ECN')
    plot_cdf(b.get_inter_df()['fct_slowdown'], label='Enable-ECN')
    plt.xscale('log')
    plt.ylim(0, 1)
    plt.xlim(1, 200)
    plt.xlabel('FCT Slowdown', fontsize=22)
    plt.ylabel('CDF', fontsize=22)
    plt.xticks(fontsize=18)
    plt.yticks(fontsize=18)
    plt.legend(fontsize=18)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.savefig('motivation1.pdf', bbox_inches='tight')
    #plt.grid(True, linestyle='--', alpha=0.7)

def plot_motivation_expr2():
    get_analyser(40).plot_qp_rate([467])

if __name__ == '__main__':
    pass
    #print(get_analyser(1).config)

# %%
