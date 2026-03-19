#!/usr/bin/env python3
"""
analyze_results.py — Parse wrk + perf stat output for web server experiments,
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


def parse_wrk_file(filepath):
    """Parse wrk output into metrics."""
    metrics = {}
    with open(filepath) as f:
        text = f.read()

    # Requests/sec
    m = re.search(r'Requests/sec:\s+([\d.]+)', text)
    if m:
        metrics['req_per_sec'] = float(m.group(1))

    # Transfer/sec
    m = re.search(r'Transfer/sec:\s+([\d.]+)(\w+)', text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == 'GB':
            val *= 1024
        metrics['transfer_mb_per_sec'] = val

    # Latency stats
    m = re.search(r'Latency\s+([\d.]+)(us|ms|s)\s+([\d.]+)(us|ms|s)\s+([\d.]+)(us|ms|s)', text)
    if m:
        def to_us(val, unit):
            val = float(val)
            if unit == 'ms':
                return val * 1000
            elif unit == 's':
                return val * 1000000
            return val
        metrics['latency_avg_us'] = to_us(m.group(1), m.group(2))
        metrics['latency_stdev_us'] = to_us(m.group(3), m.group(4))
        metrics['latency_max_us'] = to_us(m.group(5), m.group(6))

    # Latency percentiles
    pcts = re.findall(r'(\d+)%\s+([\d.]+)(us|ms|s)', text)
    for pct, val, unit in pcts:
        val = float(val)
        if unit == 'ms':
            val *= 1000
        elif unit == 's':
            val *= 1000000
        metrics[f'p{pct}_us'] = val

    # Total requests
    m = re.search(r'(\d+) requests in', text)
    if m:
        metrics['total_requests'] = int(m.group(1))

    # Socket errors
    m = re.search(r'timeout\s+(\d+)', text)
    if m:
        metrics['timeouts'] = int(m.group(1))
    else:
        metrics['timeouts'] = 0

    return metrics


def parse_perf_file(filepath):
    """Parse perf stat output."""
    metrics = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^([\d,]+)\s+(\S+)', line)
            if m:
                val_str = m.group(1).replace(',', '')
                name = m.group(2)
                metrics[name] = int(val_str)
            m2 = re.search(r'#\s+([\d.]+)\s+insn per cycle', line)
            if m2:
                metrics['IPC'] = float(m2.group(1))
    return metrics


def discover_experiments():
    """Discover and group all experiment files."""
    experiments = defaultdict(list)

    for fname in os.listdir(RAW_DIR):
        if not fname.endswith('_wrk.txt'):
            continue

        label = fname.replace('_wrk.txt', '')
        parts = label.rsplit('_rep', 1)
        if len(parts) != 2:
            continue

        config_key = parts[0]
        rep = int(parts[1])

        wrk_file = os.path.join(RAW_DIR, fname)
        perf_file = os.path.join(RAW_DIR, label + '_perf.txt')

        wrk_data = parse_wrk_file(wrk_file)
        perf_data = parse_perf_file(perf_file) if os.path.exists(perf_file) else {}

        data = {**wrk_data, **perf_data, 'rep': rep, 'config_key': config_key}
        experiments[config_key].append(data)

    return experiments


def parse_config_key(config_key):
    """Parse config key like 'small_c10_4KB_cold' into components."""
    parts = config_key.split('_')
    return {
        'file_size': parts[0],
        'concurrency': parts[1],  # c10 or c200
        'page_config': parts[2],  # 4KB or 2MB
        'cache_state': parts[3],  # cold or warm
    }


def aggregate(experiments):
    """Compute mean and std for each config."""
    results = []
    numeric_keys = [
        'req_per_sec', 'transfer_mb_per_sec',
        'latency_avg_us', 'latency_stdev_us', 'latency_max_us',
        'p50_us', 'p75_us', 'p90_us', 'p99_us',
        'total_requests', 'timeouts',
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

        # Derived: faults per request
        pf = row.get('page-faults_mean', 0)
        rq = row.get('total_requests_mean', 1)
        row['faults_per_request'] = pf / rq if rq else 0

        results.append(row)

    return results


def save_csv(results, path):
    if not results:
        return
    all_keys = set()
    for r in results:
        all_keys.update(r.keys())
    all_keys = sorted(all_keys)

    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved: {path}")


def make_label(row):
    """Short display label."""
    return f"{row['file_size']}-{row['concurrency']}-{row['cache_state']}"


def create_charts(results):
    """Generate comparison charts."""
    colors_4kb = '#4A90D9'
    colors_2mb = '#E74C3C'

    # Group: for each (file_size, concurrency, cache_state), compare 4KB vs 2MB
    groups = defaultdict(dict)
    for r in results:
        label = make_label(r)
        groups[label][r['page_config']] = r

    labels = sorted(groups.keys())

    def chart(metric_key, ylabel, title, filename, log_scale=False):
        fig, ax = plt.subplots(figsize=(14, 6))
        x = np.arange(len(labels))
        width = 0.35

        vals_4kb = [groups[l].get('4KB', {}).get(f'{metric_key}_mean', 0) or 0 for l in labels]
        vals_2mb = [groups[l].get('2MB', {}).get(f'{metric_key}_mean', 0) or 0 for l in labels]
        errs_4kb = [groups[l].get('4KB', {}).get(f'{metric_key}_std', 0) or 0 for l in labels]
        errs_2mb = [groups[l].get('2MB', {}).get(f'{metric_key}_std', 0) or 0 for l in labels]

        ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=3)
        ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=3)

        ax.set_xlabel('Configuration (filesize-concurrency-cache)', fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9, rotation=30, ha='right')
        ax.legend(fontsize=10)
        if log_scale:
            ax.set_yscale('log')
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
        plt.close()
        print(f"Generated: {filename}")

    chart('req_per_sec', 'Requests/sec', 'Throughput: 4KB vs 2MB Pages', 'throughput.png')
    chart('latency_avg_us', 'Avg Latency (µs)', 'Average Latency: 4KB vs 2MB Pages', 'latency_avg.png', log_scale=True)
    chart('p99_us', 'p99 Latency (µs)', 'Tail Latency (p99): 4KB vs 2MB Pages', 'latency_p99.png', log_scale=True)
    chart('page-faults', 'Page Faults', 'Page Faults: 4KB vs 2MB Pages', 'page_faults.png')
    chart('dTLB-load-misses', 'dTLB Load Misses', 'dTLB Load Misses: 4KB vs 2MB Pages', 'dtlb_load_misses.png', log_scale=True)
    chart('iTLB-load-misses', 'iTLB Load Misses', 'iTLB Load Misses: 4KB vs 2MB Pages', 'itlb_load_misses.png', log_scale=True)
    chart('cycles', 'CPU Cycles', 'CPU Cycles: 4KB vs 2MB Pages', 'cpu_cycles.png', log_scale=True)
    chart('IPC', 'Instructions Per Cycle', 'IPC: 4KB vs 2MB Pages', 'ipc.png')

    # === Throughput change summary ===
    fig, ax = plt.subplots(figsize=(14, 6))
    changes = []
    for l in labels:
        v4 = groups[l].get('4KB', {}).get('req_per_sec_mean', 1)
        v2 = groups[l].get('2MB', {}).get('req_per_sec_mean', 1)
        pct = (v2 - v4) / v4 * 100 if v4 else 0
        changes.append(pct)

    colors = ['#2ECC71' if c > 0 else '#E74C3C' for c in changes]
    bars = ax.bar(labels, changes, color=colors, edgecolor=[c.replace('2E', '27').replace('E7', 'C0') for c in colors], linewidth=1.5)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_ylabel('Throughput Change (%)', fontsize=12)
    ax.set_title('Throughput Change: 4KB → 2MB Pages', fontsize=13, fontweight='bold')
    ax.set_xticklabels(labels, fontsize=9, rotation=30, ha='right')
    for bar, val in zip(bars, changes):
        ypos = bar.get_height() + 0.5 if val >= 0 else bar.get_height() - 2.5
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'{val:+.1f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'throughput_change.png'), dpi=150)
    plt.close()
    print("Generated: throughput_change.png")


def print_summary(results):
    print("\n" + "=" * 120)
    print("WEB SERVER WORKLOAD RESULTS SUMMARY")
    print("=" * 120)
    fmt = "{:<30} {:>12} {:>14} {:>14} {:>12} {:>15} {:>8}"
    print(fmt.format("Config", "Req/sec", "Avg Lat(µs)", "p99 Lat(µs)", "Page Faults", "dTLB-Load-Miss", "IPC"))
    print("-" * 120)
    for r in results:
        label = f"{r['file_size']}-{r['concurrency']}-{r['page_config']}-{r['cache_state']}"
        print(fmt.format(
            label,
            f"{r.get('req_per_sec_mean', 0):,.0f}",
            f"{r.get('latency_avg_us_mean', 0):,.0f}",
            f"{r.get('p99_us_mean', 0):,.0f}",
            f"{r.get('page-faults_mean', 0):,.0f}",
            f"{r.get('dTLB-load-misses_mean', 0):,.0f}",
            f"{r.get('IPC_mean', 0):.2f}"
        ))
    print("=" * 120)


def main():
    print("Discovering experiments...")
    experiments = discover_experiments()
    print(f"Found {len(experiments)} configurations, {sum(len(v) for v in experiments.values())} total runs")

    print("\nAggregating results...")
    results = aggregate(experiments)

    print("\nSaving CSV...")
    save_csv(results, CSV_PATH)

    print("\nGenerating charts...")
    create_charts(results)

    print_summary(results)

    print(f"\nOutputs saved:")
    print(f"  CSV:   {CSV_PATH}")
    print(f"  Plots: {PLOTS_DIR}/")


if __name__ == '__main__':
    main()
