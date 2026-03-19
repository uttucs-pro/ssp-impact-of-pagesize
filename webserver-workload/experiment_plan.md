# Web Server Workload — Experiment Plan & Checklist

## Prerequisites to Install

| Tool | Purpose | Install Command |
|---|---|---|
| **nginx** | HTTP server for static file serving | `sudo apt install nginx` |
| **wrk** | HTTP benchmarking / load generation tool | `sudo apt install wrk` |
| **perf** | Hardware performance counters (already installed) | ✅ Already available |
| **Python venv** | Analysis (pandas, matplotlib) | Can reuse from `synthetic-workload/.venv` or create new |

---

## System Configuration Required

| Step | Command | Purpose |
|---|---|---|
| Ensure `perf` access | `sudo sysctl kernel.perf_event_paranoid=-1` | ✅ Already done |
| THP in `madvise` mode | Already set (`always [madvise] never`) | ✅ No action needed |
| Switch THP to `always` (for 2MB tests) | `echo always \| sudo tee /sys/kernel/mm/transparent_hugepage/enabled` | Enable system-wide huge pages for nginx |
| Switch THP to `never` (for 4KB tests) | `echo never \| sudo tee /sys/kernel/mm/transparent_hugepage/enabled` | Force 4KB pages for nginx |
| Drop page cache (cold tests) | `sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'` | Clear OS page cache between cold runs |
| Stop conflicting services | `sudo systemctl stop apache2` (if running) | Ensure no port conflicts |

> **Note:** Since nginx is a separate process (not our own code), we cannot use `madvise()` directly. THP must be controlled globally via `/sys/kernel/mm/transparent_hugepage/enabled` — toggling between `always` (2MB) and `never` (4KB) for each experiment.

---

## Files to Create

### Configuration Files

| File | Purpose |
|---|---|
| `nginx.conf` | Custom nginx config: static file serving, worker processes, logging off, optimized for benchmarking |
| `generate_test_files.sh` | Script to create test data files (small: 1KB, 5KB, 10KB; large: 10MB, 50MB, 100MB) |

### Test Data (generated, not committed)

| Directory | Contents |
|---|---|
| `test_data/small/` | Multiple small HTML/JSON files (1–10KB each), ~1000 files |
| `test_data/large/` | Multiple large binary files (10–100MB each), ~20 files |

### Automation Scripts

| File | Purpose |
|---|---|
| `run_experiments.sh` | Master script: for each (file_size × concurrency × page_config), run wrk + perf stat, collect results |
| `analyze_results.py` | Parse wrk output + perf stat logs, generate comparison charts and CSV |

### Documentation

| File | Purpose |
|---|---|
| `results.md` | Full findings, tables, charts, analysis (created below as skeleton) |

---

## Experiment Matrix

### Dimensions

| Dimension | Values |
|---|---|
| **File size** | Small (~5KB), Large (~50MB) |
| **Concurrency** | Low (10 clients), High (200 clients) |
| **Page config** | 4KB (THP=never), 2MB (THP=always) |
| **Cache state** | Cold (caches dropped), Warm (pre-loaded) |

### Total Experiments

**2 file sizes × 2 concurrency levels × 2 page configs × 2 cache states × 3 repetitions = 48 runs**

### wrk Parameters
- **Duration:** 30 seconds per run
- **Threads:** 4 (to match available cores)
- **Connections:** 10 (low) or 200 (high)

---

## Metrics to Collect

### From wrk (application-level)
- Requests per second (throughput)
- Latency: average, stdev, max
- Latency percentiles: p50, p75, p90, p99
- Transfer rate (MB/s)
- Total requests completed
- Errors (socket errors, timeouts, non-2xx)

### From perf stat (system-level, on nginx process)
- Page faults (total, minor, major)
- dTLB load misses
- dTLB store misses
- iTLB load misses
- CPU cycles
- Instructions retired
- IPC

### Derived Metrics
- Page faults per request
- dTLB misses per request
- Throughput change (%) with huge pages
- Latency change (%) with huge pages

---

## Step-by-Step Execution Plan

### Phase 1: Setup
1. Install nginx and wrk (`sudo apt install nginx wrk`)
2. Create `generate_test_files.sh` and run it to populate `test_data/`
3. Create custom `nginx.conf` optimized for benchmarking:
   - `worker_processes auto`
   - `access_log off` and `error_log /dev/null`
   - `sendfile on`, `tcp_nopush on`
   - Root pointing to `test_data/`
   - Listen on `127.0.0.1:8088` (non-standard port to avoid conflicts)
4. Test nginx starts and serves files correctly

### Phase 2: Create Automation
5. Create `run_experiments.sh`:
   - For each page config (4KB, 2MB):
     - Set THP accordingly
     - Restart nginx to pick up new memory mappings
     - For each file size (small, large):
       - For each concurrency (10, 200):
         - For cold-cache: drop caches, then run
         - For warm-cache: pre-load files, then run
         - Run `perf stat -p <nginx_pid>` in background during wrk run
         - Save wrk output and perf output to `raw_results/`

### Phase 3: Run Experiments
6. Execute `run_experiments.sh` (estimated runtime: ~30 min)

### Phase 4: Analyze & Document
7. Create and run `analyze_results.py`
8. Fill in `results.md` with findings

---

## Expected Observations (from README)
- Small file workloads may show **limited benefit** from large pages (metadata-heavy)
- Large file workloads **benefit more** due to sequential access patterns
- Page cache reduces faults in warm runs
- High concurrency increases memory pressure and fault rates
- Large pages may improve throughput for large file serving under high concurrency

---

## Risks & Considerations
- **nginx is a separate process** — we cannot call `madvise()`, must use global THP setting
- **Port conflicts** — use non-standard port (8088) to avoid interfering with existing services
- **Sudo required** for: installing packages, THP toggling, cache dropping, nginx control
- **Network variability** — running everything on localhost eliminates this
- **Background noise** — should minimize other processes during experiments
