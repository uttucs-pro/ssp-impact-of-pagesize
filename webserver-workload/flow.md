# Web Server Workload — Full Experiment Flow

This document describes the **complete end-to-end flow** of the web server workload experiment. It details the tools used, the tuning applied, every command executed, raw outputs produced, and in-depth explanations of what each metric means in the context of serving HTTP requests.

---

## Table of Contents

1. [Objective](#1-objective)
2. [System & Environment Prerequisites](#2-system--environment-prerequisites)
3. [Step 1 — Generate Test Data](#step-1--generate-test-data)
4. [Step 2 — Configure Nginx](#step-2--configure-nginx)
5. [Step 3 — Run a Manual Sanity Check](#step-3--run-a-manual-sanity-check)
6. [Step 4 — Understand the Automation Script](#step-4--understand-the-automation-script)
7. [Step 5 — Execute the Full Benchmark Suite](#step-5--execute-the-full-benchmark-suite)
8. [Step 6 — Understand the Raw Output Files (wrk & perf)](#step-6--understand-the-raw-output-files-wrk--perf)
9. [Step 7 — Run the Analysis Script](#step-7--run-the-analysis-script)
10. [Step 8 — Complete File Inventory](#complete-file-inventory)

---

## 1. Objective

The goal of this experiment is to evaluate **how page size (4 KB vs 2 MB) affects the performance of an I/O-heavy, network-bound application**: the **Nginx** web server. 

Unlike the synthetic workload (which performed user-space memory manipulation), Nginx uses the `sendfile()` system call to ask the Linux kernel to stream files directly from the OS page cache to network sockets via DMA (Direct Memory Access), bypassing user-space memory copies entirely.

We test across four dimensions:
1. **File Size**: Small (~7 KB HTML) vs Large (50 MB binary).
2. **Concurrency**: Low (10 concurrent clients) vs High (200 concurrent clients).
3. **Page Size**: 4 KB (`THP=never`) vs 2 MB (`THP=always`).
4. **Cache State**: Cold (caches dropped) vs Warm (data pre-loaded in memory).

---

## 2. System & Environment Prerequisites

### Tools
- **Nginx**: A high-performance asynchronous web server.
- **wrk**: A modern HTTP benchmarking tool capable of generating significant load from a single multi-core CPU.
- **perf**: Linux profiling tool with access to hardware performance counters.

### Installation

```bash
sudo apt update
sudo apt install -y nginx wrk linux-tools-common linux-tools-$(uname -r)
```

No custom kernel modules or compilation of the server are needed; we use the standard Ubuntu packages.

---

## Step 1 — Generate Test Data

We need realistic files to serve. The script `generate_test_files.sh` creates them.

### Command
```bash
cd webserver-workload
bash generate_test_files.sh
```

### Expected Output
```
=== Generating test data ===
Creating small files (1-10 KB)...
  Created 500 small files (~5KB each)
Creating large files (50 MB)...
  Created 10 large files (50MB each)

=== Test data summary ===
Small files: 500 files, total 3.5M
Large files: 10 files, total 501M
Total: 504M
```

### Explanation
- **Small files**: 500 files of random base64 data (~6.9 KB each on disk). This simulates serving many small static assets (HTML, JSON, CSS) where connection overhead and metadata lookups are significant. 
- **Large files**: 10 files of exactly 50 MB each (binary zeroes/random data). This simulates video streaming or large software downloads where raw sequential throughput is the bottleneck.
- **Total size**: ~504 MB. This fits entirely within the 16 GB of system RAM, meaning the "warm cache" tests will be purely memory-bound (no disk I/O).

---

## Step 2 — Configure Nginx

We use a custom, minimal `nginx.conf` designed specifically for maximum performance benchmarking, bypassing standard OS limits.

### Nginx Configuration Highlights
```nginx
worker_processes auto;
pid /tmp/nginx_bench.pid;
error_log /dev/null crit;

events {
    worker_connections 1024;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    access_log off;

    server {
        listen 127.0.0.1:8088;
        # ... locations pointing to test_data/ ...
    }
}
```

### Detailed Explanation of Tuning Parameters:
- **`worker_processes auto`**: Nginx spawns one worker process per CPU core (8 cores = 8 workers).
- **`access_log off`**: Writing a log line for every request (150,000+ per second) would instantly bottleneck the disk and CPU. We disable it.
- **`sendfile on`**: **Crucial for this experiment.** Instead of reading file data into user-space memory and writing it to the network socket, Nginx tells the kernel to copy data directly from the page cache to the network interface.
- **`tcp_nopush` & `tcp_nodelay`**: Optimizes how TCP packets are stuffed/flushed, minimizing protocol overhead for both small and large files.
- **Port `8088`**: A non-privileged, non-standard port to avoid clashing with any existing web servers on the host machine.

---

## Step 3 — Run a Manual Sanity Check

Before running the automated 48-run matrix, we verify Nginx and `wrk` are functioning manually.

### 3.1 Start Nginx manually

```bash
sudo nginx -c $(pwd)/nginx.conf
```
Verify it's running:
```bash
curl -I http://127.0.0.1:8088/small/file_1.html
```
*Expected: `HTTP/1.1 200 OK`*

### 3.2 Run a quick `wrk` test

```bash
wrk -t2 -c10 -d5s http://127.0.0.1:8088/small/file_1.html
```

**Expected Output:**
```
Running 5s test @ http://127.0.0.1:8088/small/file_1.html
  2 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    57.10us   30.56us   1.14ms   93.26%
    Req/Sec    81.33k     6.34k  100.91k    76.00%
  809279 requests in 5.00s, 5.37GB read
Requests/sec: 161852.17
Transfer/sec:      1.07GB
```
*Observe the astonishing ~160K requests per second. The system is working.*

### 3.3 Stop Nginx
```bash
sudo killall nginx
```

---

## Step 4 — Understand the Automation Script

The script `run_experiments.sh` requires `sudo` because it must:
1. Start/stop `nginx`.
2. Drop kernel caches (`/proc/sys/vm/drop_caches`).
3. Toggle system-wide Transparent Huge Pages (`/sys/kernel/mm/transparent_hugepage/enabled`).
4. Attach `perf stat` to running `nginx` worker processes.

**Because Nginx is an independent daemon process, we cannot use `madvise()` inside its code to request huge pages** (unlike our custom `load.cpp` synthetic benchmark). Instead, we must change the global THP policy for the entire Linux kernel:

```bash
# To test 2MB pages:
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled

# To test 4KB pages:
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

**Workflow for a single run loop inside the script:**
1. Drop caches.
2. If "warm" cache is requested, run `wrk` for 5 seconds to load files into RAM.
3. Find Nginx worker PIDs: `pgrep -P <master_pid>`.
4. Start `perf stat -p <worker1,worker2...>` in the background.
5. Run `wrk` for exactly 30 seconds.
6. Kill the `perf stat` process to flush the hardware counters to a file.

**A note on small file testing**:
The script uses a Lua script (`random_small.lua`) injected into `wrk` to ensure `wrk` randomly requests all 500 small files, rather than requesting `file_1.html` repeatedly. This prevents the CPU's L1/L2 caches from trivially caching a single 7 KB file.

---

## Step 5 — Execute the Full Benchmark Suite

### Command
```bash
sudo bash run_experiments.sh
```

### Condensed Output
```
=== Web Server Workload Experiments ===
Duration: 30s | Threads: 4 | Repetitions: 3

--- Setting THP to 'never' (4KB pages) ---
  THP set to: always madvise [never]

=== small files | concurrency=10 | 4KB | cold ===
  Running: small_c10_4KB_cold_rep1
    Done: small_c10_4KB_cold_rep1
... (runs fast, caching logic drops/warms caches as needed)
...
--- Setting THP to 'always' (2MB huge pages) ---
  THP set to: [always] madvise never

=== small files | concurrency=10 | 2MB | cold ===
  Running: small_c10_2MB_cold_rep1
    Done: small_c10_2MB_cold_rep1
...
--- Restoring THP to 'madvise' ---
  THP set to: always [madvise] never

=== All experiments complete ===
Raw results saved to: /home/uttu/Desktop/spe-proj/webserver-workload/raw_results/
```
*(Execution takes approximately 35 minutes).*

---

## Step 6 — Understand the Raw Output Files (wrk & perf)

For each of the 48 runs, two files are produced: `*_wrk.txt` and `*_perf.txt`. Let's analyze a specific, contrasting pair to understand exactly what the hardware and software are doing.

### 6.1 — High Concurrency Small File Serving (4 KB vs 2 MB)

**File: `small_c200_4KB_cold_rep1_wrk.txt` (4 KB Pages)**
```
Running 30s test @ http://127.0.0.1:8088
  4 threads and 200 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.31ms    1.40ms  18.10ms   85.69%
    Req/Sec    39.32k    12.13k   73.46k    72.31%
  Latency Distribution
     50%  623.00us
     99%    6.28ms
  4701933 requests in 30.10s, 31.38GB read
Requests/sec: 156212.82
```

**File: `small_c200_2MB_cold_rep1_wrk.txt` (2 MB Pages)**
```
Running 30s test @ http://127.0.0.1:8088
  4 threads and 200 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.99ms    2.03ms  35.71ms   85.88%
    Req/Sec    24.51k     7.83k   57.24k    75.61%
  Latency Distribution
     50%    1.23ms
     99%    8.97ms
  2930573 requests in 30.09s, 19.56GB read
Requests/sec:  97392.67
```

**Interpretation of `wrk` metrics:**
- **Requests/sec**: 156,212 req/s with 4KB pages vs 97,392 req/s with 2MB pages. **4KB pages are roughly 60% faster**.
- **Average Latency**: 1.31 ms (4KB) vs 1.99 ms (2MB). Huge pages caused requests to take 50% longer on average.
- **p99 Latency (Tail)**: 6.28 ms (4KB) vs 8.97 ms (2MB). Huge pages made the slowest 1% of requests significantly worse.

**Why did 2MB pages perform so much worse? The `perf stat` output holds the answer.**

**File: `small_c200_4KB_cold_rep1_perf.txt` (4 KB Pages)**
```
 Performance counter stats for process id '...':
               157      page-faults                                                           
        54,822,828      dTLB-load-misses                                                      
         6,238,101      dTLB-store-misses                                                     
       285,243,909      iTLB-load-misses                                                      
   475,036,031,861      cycles                                                                
   238,288,482,425      instructions                     #    0.50  insn per cycle
```

**File: `small_c200_2MB_cold_rep1_perf.txt` (2 MB Pages)**
```
 Performance counter stats for process id '...':
               152      page-faults                                                           
        46,605,676      dTLB-load-misses                                                      
         5,506,643      dTLB-store-misses                                                     
       177,913,663      iTLB-load-misses                                                      
   352,035,418,768      cycles                                                                
   149,176,123,626      instructions                     #    0.42  insn per cycle            
```

*(Note: Cycle/Instruction counts are over ~30 seconds for 8 worker processes).*

**Interpretation of `perf` metrics:**
- **Page Faults**: ~150 in both cases. Page faults are practically nonexistent, debunking the idea that OS faulting is the bottleneck. The page cache is handling mapping efficiently.
- **dTLB Misses**: ~54M (4KB) vs ~46M (2MB). Huge pages *did* slightly decrease data TLB misses, but the absolute numbers are very low relative to the request count (~11 misses per request).
- **iTLB Misses**: Huge numbers in both cases (285M vs 177M). Nginx is a complex C program with many branches; instruction cache/TLB misses are a massive tax here. 
- **Instructions & Cycles**: The 4KB run executed substantially *more* instructions overall (238B vs 149B). Why? Because it handled 1.7 million *more* HTTP requests in the same 30-second window!
- **IPC (Instructions Per Cycle)**: 0.50 for 4KB vs 0.42 for 2MB. This is the smoking gun. With 2MB pages, the CPU's efficiency dropped by 16%.

**The "THP always" Tax**: When we set global THP to `always`, the kernel `khugepaged` daemon wakes up and aggressively scans memory, attempting to compact 4KB pages into 2MB adjacent blocks. This daemon runs globally, stealing CPU cycles, locking memory regions, and stalling the Nginx workers. Furthermore, Nginx handles small files utilizing `sendfile()`, meaning there is very little user-space memory manipulation where a 2MB page TLB entry would actually help.

### 6.2 — Low Concurrency Large File Serving (4 KB vs 2 MB)

Perhaps large files (50 MB) benefit from huge pages? Let's look.

**File: `large_c10_4KB_cold_rep1_wrk.txt`**
```
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    31.97ms   14.22ms 342.43ms   79.02%
  6480 requests in 30.09s, 316.43GB read
Requests/sec:    215.33
Transfer/sec:     10.51GB
```

**File: `large_c10_2MB_cold_rep1_wrk.txt`**
```
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    59.87ms   24.40ms 252.55ms   77.27%
  3621 requests in 30.08s, 176.90GB read
Requests/sec:    120.40
Transfer/sec:      5.88GB
```

**Interpretation:**
- **Requests/sec**: 215 req/s (4KB) vs 120 req/s (2MB).
- **Throughput**: 10.51 GB/s (4KB) vs 5.88 GB/s (2MB). 
- **4KB pages are nearly 2× faster for streaming 50MB files.**

**Why? Perf stat holds the key (`large_c10_4KB_cold_rep1_perf.txt` vs `large_c10_2MB_cold_rep1_perf.txt`):**
- **IPC**: 0.80 (4KB) vs 0.62 (2MB).
- **dTLB-load-misses**: 29.0M (4KB) vs 12.0M (2MB). Huge pages *did* cut TLB misses in half.
- However, since `sendfile()` is doing direct DMA streaming from the page cache to the socket, the data TLB (which translates user-space virtual memory) isn't the primary bottleneck. The background THP allocation overhead associated with reserving and mapping 2MB contiguous blocks in the kernel cache completely wiped out any minor TLB advantages, HALVING overall throughput.

---

## Step 7 — Run the Analysis Script

### Command
```bash
python3 analyze_results.py
```

### Script Workflow
1. Scans `raw_results/` for all `*_wrk.txt` and `*_perf.txt` pairs.
2. Uses regex to extract parsing metrics: 
   - `wrk`: Req/sec, Avg Latency (converting text "us/ms" to clean floats).
   - `perf`: Extracts page-faults, TLB misses, cycles, instructions, IPC.
3. Averages the 3 repetitions for every configuration.
4. Generates a master `results.csv`.
5. Spawns `matplotlib` to generate 9 intuitive bar charts comparing the 4KB and 2MB runs across throughput, latency, and hardware metrics.

---

## Step 8 — Complete File Inventory

Following the run and analysis, the directory contains:

```
webserver-workload/
├── experiment_plan.md        # The test design and predictions
├── findings.md               # Extensive technical report on the results
├── flow.md                   # This detailed commands and explanation document
├── generate_test_files.sh    # Script to create dummy data
├── nginx.conf                # The benchmark-tuned Nginx configuration
├── run_experiments.sh        # The master bash automation script
├── analyze_results.py        # Python parser and plotting script
├── results.csv               # Merged dataset containing means/std-devs
├── test_data/                # (Generated) 504MB of dummy files
│   ├── small/                # file_1.html to file_500.html
│   └── large/                # file_1.bin to file_10.bin
├── plots/                    # Output from Python script
│   ├── throughput.png
│   ├── throughput_change.png
│   ├── latency_avg.png
│   ├── latency_p99.png
│   ├── page_faults.png
│   ├── dtlb_load_misses.png
│   ├── itlb_load_misses.png
│   ├── cpu_cycles.png
│   └── ipc.png
└── raw_results/              # 96 raw output files
    ├── small_c10_4KB_cold_rep1_wrk.txt
    ├── small_c10_4KB_cold_rep1_perf.txt
    ├── ... (and so on for all 48 combinations)
```
