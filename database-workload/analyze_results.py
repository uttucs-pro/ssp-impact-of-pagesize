#!/usr/bin/env python3
"""
analyze_results.py — Parse sysbench + perf stat output for database experiments,
aggregate across repetitions, generate comparison charts and CSV.
"""

import os
import re
import csv
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw_results')
PLOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plots')
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.csv')

os.makedirs(PLOTS_DIR, exist_ok=True)


def parse_sysbench_file(filepath):
    """Parse sysbench output into metrics."""
    metrics = {}
    with open(filepath) as f:
        text = f.read()

    # Transactions per second
    m = re.search(r'transactions:\s+\d+\s+\(([\d.]+) per sec\.\)', text)
    if m:
        metrics['tps'] = float(m.group(1))

    # Queries per second
    m = re.search(r'queries:\s+\d+\s+\(([\d.]+) per sec\.\)', text)
    if m:
        metrics['qps'] = float(m.group(1))

    # Total transactions
    m = re.search(r'total number of events:\s+(\d+)', text)
    if m:
        metrics['total_events'] = int(m.group(1))

    # Latency
    m = re.search(r'min:\s+([\d.]+)', text)
    if m:
        metrics['lat_min_ms'] = float(m.group(1))

    m = re.search(r'avg:\s+([\d.]+)', text)
    if m:
        metrics['lat_avg_ms'] = float(m.group(1))

    m = re.search(r'max:\s+([\d.]+)', text)
    if m:
        metrics['lat_max_ms'] = float(m.group(1))

    m = re.search(r'95th percentile:\s+([\d.]+)', text)
    if m:
        metrics['lat_p95_ms'] = float(m.group(1))

    # Read/write counts
    m = re.search(r'read:\s+(\d+)', text)
    if m:
        metrics['read_queries'] = int(m.group(1))

    m = re.search(r'write:\s+(\d+)', text)
    if m:
        metrics['write_queries'] = int(m.group(1))

    return metrics


def parse_perf_file(filepath):
    """Parse perf stat output."""
    metrics = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^([\d,]+)\s+(\S+)', line)
            if m:
                metrics[m.group(2)] = int(m.group(1).replace(',', ''))
            m2 = re.search(r'#\s+([\d.]+)\s+insn per cycle', line)
            if m2:
                metrics['IPC'] = float(m2.group(1))
    return metrics


def discover_experiments():
    """Discover and group experiment files."""
    experiments = defaultdict(list)

    for fname in os.listdir(RAW_DIR):
        if not fname.endswith('_sysbench.txt'):
            continue

        label = fname.replace('_sysbench.txt', '')
        parts = label.rsplit('_rep', 1)
        if len(parts) != 2:
            continue

        config_key = parts[0]
        rep = int(parts[1])

        sb_file = os.path.join(RAW_DIR, fname)
        perf_file = os.path.join(RAW_DIR, label + '_perf.txt')

        sb_data = parse_sysbench_file(sb_file)
        perf_data = parse_perf_file(perf_file) if os.path.exists(perf_file) else {}

        data = {**sb_data, **perf_data, 'rep': rep, 'config_key': config_key}
        experiments[config_key].append(data)

    return experiments


def parse_config_key(config_key):
    """Parse e.g. 'read_only_4KB_cold' -> workload, page_config, cache_state."""
    # Handle multi-word workload names
    if config_key.startswith('read_only_'):
        workload = 'read_only'
        rest = config_key[len('read_only_'):]
    elif config_key.startswith('read_write_'):
        workload = 'read_write'
        rest = config_key[len('read_write_'):]
    elif config_key.startswith('range_'):
        workload = 'range'
        rest = config_key[len('range_'):]
    else:
        workload = config_key.split('_')[0]
        rest = '_'.join(config_key.split('_')[1:])

    parts = rest.split('_')
    return {
        'workload': workload,
        'page_config': parts[0],
        'cache_state': parts[1],
    }


def aggregate(experiments):
    """Compute mean and std for each config."""
    results = []
    numeric_keys = [
        'tps', 'qps', 'total_events',
        'lat_min_ms', 'lat_avg_ms', 'lat_max_ms', 'lat_p95_ms',
        'page-faults', 'minor-faults', 'major-faults',
        'dTLB-load-misses', 'dTLB-store-misses', 'iTLB-load-misses',
        'cycles', 'instructions', 'IPC'
    ]

    for config_key, reps in sorted(experiments.items()):
        row = {'config': config_key}
        row.update(parse_config_key(config_key))

        for key in numeric_keys:
            vals = [r.get(key) for r in reps if r.get(key) is not None]
            if vals:
                row[f'{key}_mean'] = np.mean(vals)
                row[f'{key}_std'] = np.std(vals)

        # Derived: faults per transaction
        pf = row.get('page-faults_mean', 0)
        tx = row.get('total_events_mean', 1)
        row['faults_per_tx'] = pf / tx if tx else 0

        results.append(row)

    return results


def save_csv(results, path):
    if not results:
        return
    all_keys = set()
    for r in results:
        all_keys.update(r.keys())
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=sorted(all_keys))
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved: {path}")


def make_label(row):
    return f"{row['workload']}-{row['cache_state']}"


def create_charts(results):
    """Generate comparison charts."""
    colors_4kb = '#4A90D9'
    colors_2mb = '#E74C3C'

    # Group by (workload, cache_state) for x-axis
    groups = defaultdict(dict)
    for r in results:
        label = make_label(r)
        groups[label][r['page_config']] = r

    labels = sorted(groups.keys())

    def chart(metric_key, ylabel, title, filename, log_scale=False):
        fig, ax = plt.subplots(figsize=(12, 6))
        x = np.arange(len(labels))
        width = 0.35

        vals_4kb = [groups[l].get('4KB', {}).get(f'{metric_key}_mean', 0) or 0 for l in labels]
        vals_2mb = [groups[l].get('2MB', {}).get(f'{metric_key}_mean', 0) or 0 for l in labels]
        errs_4kb = [groups[l].get('4KB', {}).get(f'{metric_key}_std', 0) or 0 for l in labels]
        errs_2mb = [groups[l].get('2MB', {}).get(f'{metric_key}_std', 0) or 0 for l in labels]

        ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
        ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

        ax.set_xlabel('Workload - Cache State', fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10, rotation=20, ha='right')
        ax.legend(fontsize=10)
        if log_scale:
            ax.set_yscale('log')
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
        plt.close()
        print(f"Generated: {filename}")

    chart('tps', 'Transactions/sec', 'Throughput (TPS): 4KB vs 2MB Pages', 'tps.png')
    chart('lat_avg_ms', 'Avg Latency (ms)', 'Average Latency: 4KB vs 2MB Pages', 'latency_avg.png')
    chart('lat_p95_ms', 'p95 Latency (ms)', 'Tail Latency (p95): 4KB vs 2MB Pages', 'latency_p95.png')
    chart('page-faults', 'Page Faults', 'Page Faults: 4KB vs 2MB Pages', 'page_faults.png')
    chart('dTLB-load-misses', 'dTLB Load Misses', 'dTLB Load Misses: 4KB vs 2MB Pages', 'dtlb_load_misses.png', log_scale=True)
    chart('cycles', 'CPU Cycles', 'CPU Cycles: 4KB vs 2MB Pages', 'cpu_cycles.png', log_scale=True)
    chart('IPC', 'Instructions Per Cycle', 'IPC: 4KB vs 2MB Pages', 'ipc.png')

    # TPS change summary
    fig, ax = plt.subplots(figsize=(12, 6))
    changes = []
    for l in labels:
        v4 = groups[l].get('4KB', {}).get('tps_mean', 1)
        v2 = groups[l].get('2MB', {}).get('tps_mean', 1)
        pct = (v2 - v4) / v4 * 100 if v4 else 0
        changes.append(pct)

    colors = ['#2ECC71' if c > 0 else '#E74C3C' for c in changes]
    bars = ax.bar(labels, changes, color=colors, edgecolor='black', linewidth=0.5)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_ylabel('TPS Change (%)', fontsize=12)
    ax.set_title('Throughput Change: 4KB → 2MB Pages', fontsize=13, fontweight='bold')
    ax.set_xticklabels(labels, fontsize=10, rotation=20, ha='right')
    for bar, val in zip(bars, changes):
        ypos = bar.get_height() + 0.3 if val >= 0 else bar.get_height() - 1.5
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'{val:+.1f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'tps_change.png'), dpi=150)
    plt.close()
    print("Generated: tps_change.png")


def print_summary(results):
    print("\n" + "=" * 110)
    print("DATABASE WORKLOAD RESULTS SUMMARY")
    print("=" * 110)
    fmt = "{:<30} {:>10} {:>10} {:>12} {:>12} {:>15} {:>8}"
    print(fmt.format("Config", "TPS", "QPS", "AvgLat(ms)", "p95Lat(ms)", "PageFaults", "IPC"))
    print("-" * 110)
    for r in results:
        label = f"{r['workload']}-{r['page_config']}-{r['cache_state']}"
        print(fmt.format(
            label,
            f"{r.get('tps_mean', 0):,.0f}",
            f"{r.get('qps_mean', 0):,.0f}",
            f"{r.get('lat_avg_ms_mean', 0):.2f}",
            f"{r.get('lat_p95_ms_mean', 0):.2f}",
            f"{r.get('page-faults_mean', 0):,.0f}",
            f"{r.get('IPC_mean', 0):.2f}"
        ))
    print("=" * 110)


def main():
    print("Discovering experiments...")
    experiments = discover_experiments()
    print(f"Found {len(experiments)} configurations, {sum(len(v) for v in experiments.values())} total runs")

    print("\nAggregating...")
    results = aggregate(experiments)

    print("\nSaving CSV...")
    save_csv(results, CSV_PATH)

    print("\nGenerating charts...")
    create_charts(results)

    print_summary(results)

    print(f"\nOutputs: CSV={CSV_PATH}  Plots={PLOTS_DIR}/")


if __name__ == '__main__':
    main()
