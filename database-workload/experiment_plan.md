# Database Workload — Experiment Plan & Checklist

## Prerequisites to Install

| Tool | Purpose | Install Command |
|---|---|---|
| **PostgreSQL** | Relational database with buffer pool, background processes | `sudo apt install postgresql postgresql-contrib` |
| **sysbench** | OLTP benchmark tool for generating realistic DB workloads | `sudo apt install sysbench` |
| **perf** | Hardware performance counters | ✅ Already available |
| **Python venv** | Analysis (pandas, matplotlib) | ✅ Can reuse from `synthetic-workload/.venv` |

---

## System Configuration Required

| Step | Command | Purpose |
|---|---|---|
| Start PostgreSQL | `sudo systemctl start postgresql` | Start the database server |
| Create benchmark DB | `sudo -u postgres createdb spe_bench` | Database for experiments |
| Create benchmark user | `sudo -u postgres createuser --superuser uttu` | User for sysbench |
| Set user password | `sudo -u postgres psql -c "ALTER USER uttu PASSWORD 'bench';"` | Password for sysbench connection |
| Allow local auth | Edit `pg_hba.conf` → `md5` for local connections | sysbench needs password auth |
| THP `always` (for 2MB) | `echo always \| sudo tee /sys/kernel/mm/transparent_hugepage/enabled` | System-wide huge pages |
| THP `never` (for 4KB) | `echo never \| sudo tee /sys/kernel/mm/transparent_hugepage/enabled` | Force standard 4KB pages |
| Drop caches (cold) | `sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'` | Clear OS page cache |
| PostgreSQL huge pages | Set `huge_pages = try` in `postgresql.conf` (optional) | Let PG use huge pages if available |

> **Note:** Like nginx, PostgreSQL is a separate process — `madvise()` cannot be called from our scripts. THP must be controlled globally via `/sys/kernel/mm/transparent_hugepage/enabled`, toggling between `always` (2MB) and `never` (4KB) per experiment run.

---

## Files to Create

### Setup & Configuration

| File | Purpose |
|---|---|
| `setup_db.sh` | Automate PostgreSQL setup: create DB, user, configure auth, prepare sysbench tables |

### Automation Scripts

| File | Purpose |
|---|---|
| `run_experiments.sh` | Master script: for each (workload × page_config × cache_state), run sysbench + perf stat |
| `analyze_results.py` | Parse sysbench output + perf stat logs, generate charts and CSV |

### Documentation

| File | Purpose |
|---|---|
| `findings.md` | Full findings with tables, charts, and analysis |

---

## Experiment Matrix

### Workload Types (from sysbench OLTP)

| Workload | sysbench Command | Description |
|---|---|---|
| **Read-only** | `sysbench oltp_read_only` | Point lookups via primary key (SELECT) |
| **Read-write** | `sysbench oltp_read_write` | Mixed SELECT, UPDATE, INSERT, DELETE |
| **Range scan** | `sysbench oltp_read_only --range_size=100` | Range queries over contiguous keys |

### Dimensions

| Dimension | Values |
|---|---|
| **Workload** | Read-only, Read-write, Range scan |
| **Page config** | 4KB (THP=never), 2MB (THP=always) |
| **Cache state** | Cold (caches + PG restarted), Warm (pre-warmed) |
| **Repetitions** | 3 per configuration |

### Total Experiments

**3 workloads × 2 page configs × 2 cache states × 3 reps = 36 runs**

### sysbench Parameters
- **Table count**: 4 tables
- **Table size**: 1,000,000 rows per table (~1–2 GB total DB size, exceeds L3 cache)
- **Threads**: 4
- **Duration**: 60 seconds per run
- **Report interval**: 10 seconds (for time-series data)

---

## Metrics to Collect

### From sysbench (application-level)
- Transactions per second (TPS)
- Queries per second (QPS)
- Latency: average, p95, p99
- Read/write/other operation counts
- Errors (if any)

### From perf stat (system-level, on PostgreSQL processes)
- Page faults (total, minor, major)
- dTLB load misses
- dTLB store misses
- iTLB load misses
- CPU cycles
- Instructions retired
- IPC

### Derived Metrics
- Page faults per transaction
- dTLB misses per transaction
- Throughput change (%) with huge pages
- Latency change (%) with huge pages

---

## Step-by-Step Execution Plan

### Phase 1: Setup
1. Install PostgreSQL and sysbench
2. Start PostgreSQL, create DB and user
3. Run `sysbench oltp_read_write prepare` to populate tables (4 tables × 1M rows)
4. Verify sysbench can run a quick test

### Phase 2: Create Automation
5. Create `run_experiments.sh`:
   - For each page config (4KB, 2MB):
     - Set THP accordingly
     - For each workload (read-only, read-write, range):
       - For cold: drop caches + restart PostgreSQL
       - For warm: run a quick warmup
       - Run `perf stat -p <pg_pids>` in background during sysbench
       - Save sysbench output and perf output to `raw_results/`

### Phase 3: Run Experiments
6. Execute `run_experiments.sh` (estimated runtime: ~40 min)

### Phase 4: Analyze & Document
7. Create and run `analyze_results.py`
8. Write `findings.md` with full analysis

---

## Expected Observations (from README)
- Random-access workloads (point lookups) generate **high TLB pressure**
- Large pages may **reduce TLB misses** but not always improve latency
- PostgreSQL's **buffer pool may mask** some page fault effects
- **Tail latency may increase** with large pages due to THP compaction overhead
- Read-write workloads involve dirty pages → more complex paging behavior

---

## Risks & Considerations
- **PostgreSQL is a multi-process server** — must attach `perf stat` to all backend PIDs
- **Shared buffers**: PostgreSQL maintains its own buffer pool (`shared_buffers`); interaction with OS page cache creates two-level caching
- **WAL writes**: Read-write workloads trigger write-ahead logging, adding I/O noise
- **Sudo required** for: installing packages, THP toggling, cache dropping, PG restart
- **Background processes**: PostgreSQL autovacuum, checkpointer, WAL writer run in background — may affect measurements
- **Recommendation**: Disable autovacuum during benchmarks for cleaner results
