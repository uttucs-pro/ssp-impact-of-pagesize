# Synthetic Workload — Full Experiment Flow

This document describes the **complete end-to-end flow** of the synthetic memory workload experiment, including every command executed, every output produced, and detailed explanations of what each step does and why.

---

## Table of Contents

1. [Objective](#1-objective)
2. [System & Environment Prerequisites](#2-system--environment-prerequisites)
3. [Step 1 — Verify Transparent Huge Pages (THP) Configuration](#step-1--verify-transparent-huge-pages-thp-configuration)
4. [Step 2 — Compile the Benchmark Program (`load.cpp`)](#step-2--compile-the-benchmark-program-loadcpp)
5. [Step 3 — Understand the Benchmark Program](#step-3--understand-the-benchmark-program)
6. [Step 4 — Run a Single Manual Experiment (Optional Sanity Check)](#step-4--run-a-single-manual-experiment-optional-sanity-check)
7. [Step 5 — Run the Full Automated Experiment Suite](#step-5--run-the-full-automated-experiment-suite)
8. [Step 6 — Understand the Raw Output Files](#step-6--understand-the-raw-output-files)
9. [Step 7 — Run the Analysis Script](#step-7--run-the-analysis-script)
10. [Step 8 — Interpret the Results](#step-8--interpret-the-results)
11. [Complete File Inventory](#complete-file-inventory)

---

## 1. Objective

The goal of this experiment is to **measure the impact of page size on memory access performance**. We compare standard **4 KB pages** (`MADV_NOHUGEPAGE`) against **2 MB huge pages** (`MADV_HUGEPAGE`) across different memory access patterns:

| Pattern | Description |
|---|---|
| **Sequential (`seq`)** | Linearly walks through every byte of a 1 GB array. Best spatial locality. |
| **Random (`rand`)** | Randomly accesses bytes within a 1 GB array using `rand()` with a fixed seed (42). Worst spatial locality. |
| **Strided-4096 (`stride 4096`)** | Accesses every 4096th byte — one access per 4 KB page boundary. |
| **Strided-65536 (`stride 65536`)** | Accesses every 65536th byte — one access per 64 KB boundary. |

Each configuration is repeated **3 times** for statistical stability, and instrumented with `perf stat` to capture hardware-level metrics (TLB misses, page faults, CPU cycles, instructions, IPC).

---

## 2. System & Environment Prerequisites

### Hardware Used

| Parameter | Value |
|---|---|
| **CPU** | Intel Core i5-10300H @ 2.50 GHz (4 cores, 8 threads) |
| **RAM** | 16 GB DDR4 |
| **L1d Cache** | 128 KiB (4 instances, 32 KB per core) |
| **L1i Cache** | 128 KiB (4 instances) |
| **L2 Cache** | 1 MiB (4 instances, 256 KB per core) |
| **L3 Cache** | 8 MiB (1 shared instance) |
| **Storage** | 238.5 GB NVMe SSD |

### Software

| Parameter | Value |
|---|---|
| **OS** | Ubuntu 24.04.4 LTS |
| **Kernel** | Linux 6.17.0-19-generic |
| **Compiler** | g++ 13.3.0 |
| **Profiling Tool** | `perf` (linux-tools) |
| **Python** | 3.x (with `matplotlib`, `numpy`) |

### Required Packages

```bash
# Install build tools and perf
sudo apt update
sudo apt install -y build-essential linux-tools-common linux-tools-$(uname -r)

# Install Python dependencies (inside project venv)
cd synthetic-workload
python3 -m venv .venv
source .venv/bin/activate
pip install matplotlib numpy
```

**Explanation**: `build-essential` provides `g++` for compiling the C++ benchmark. `linux-tools` provides the `perf` command for hardware performance counter instrumentation. `matplotlib` and `numpy` are needed by the analysis script to generate charts and compute statistics.

---

## Step 1 — Verify Transparent Huge Pages (THP) Configuration

### Command

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
```

### Expected Output

```
always [madvise] never
```

### Detailed Explanation

This command reads the kernel's Transparent Huge Page (THP) setting. The square brackets `[madvise]` indicate the **currently active** mode. There are three possible modes:

| Mode | Meaning |
|---|---|
| `always` | The kernel automatically promotes all anonymous memory mappings to huge pages whenever possible. This can cause unpredictable latency spikes due to background compaction/defragmentation. |
| `madvise` | Huge pages are **only** used when a program explicitly requests them via the `madvise()` system call with the `MADV_HUGEPAGE` flag. This gives the program full control. |
| `never` | Huge pages are completely disabled for anonymous memory. |

**Why `madvise` is required for this experiment**: Our benchmark program (`load.cpp`) uses `madvise(p, size, MADV_HUGEPAGE)` or `madvise(p, size, MADV_NOHUGEPAGE)` to explicitly control page size on a per-allocation basis. With `madvise` mode, we can run both 4 KB and 2 MB experiments on the same system without rebooting or modifying global kernel settings. If THP were set to `always`, the kernel might silently promote our intended 4 KB pages to 2 MB pages, invalidating the experiment. If set to `never`, our 2 MB hugepage requests would be silently ignored.

### If THP is NOT set to `madvise`, set it:

```bash
sudo sh -c 'echo madvise > /sys/kernel/mm/transparent_hugepage/enabled'
```

Also verify the `defrag` setting:

```bash
cat /sys/kernel/mm/transparent_hugepage/defrag
```

**Expected Output:**

```
always defer defer+madvise [madvise] never
```

The `defrag` setting controls **how aggressively the kernel tries to create huge pages** by compacting memory. With `madvise`, the kernel only attempts compaction when the application explicitly requests huge pages, which is the ideal behavior for controlled experiments.

---

## Step 2 — Compile the Benchmark Program (`load.cpp`)

### Command

```bash
cd synthetic-workload
g++ -O2 -o load load.cpp
```

### Expected Output

```
(no output — successful compilation produces no terminal output)
```

A new binary file `load` is created in the current directory.

### Detailed Explanation

- **`g++`**: The GNU C++ compiler.
- **`-O2`**: Optimization level 2. This enables a significant set of compiler optimizations (inlining, loop unrolling, instruction scheduling, dead code elimination, etc.) without the aggressive optimizations of `-O3` that might alter memory access patterns. We use `-O2` because:
  - It produces realistic, optimized code similar to what real applications use.
  - It doesn't apply aggressive vectorization (`-O3`) which could alter the memory access pattern and confound our measurements.
  - It still compiles the benchmark to be efficient enough that the bottleneck is clearly in the memory subsystem (TLB, page table, cache), not in the CPU instruction pipeline.
- **`-o load`**: Names the output binary `load`.
- **`load.cpp`**: The source file containing our benchmark.

### Verifying Compilation

```bash
file load
```

**Expected Output:**

```
load: ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked, ...
```

This confirms we have a valid 64-bit Linux executable.

---

## Step 3 — Understand the Benchmark Program

The compiled binary `load` accepts the following arguments:

```
Usage: ./load <size_mb> <iterations> <seq|rand|stride> [stride_bytes]
  Environment: USE_HUGEPAGES=1 to enable 2MB huge pages via madvise()
```

### Arguments

| Argument | Description |
|---|---|
| `size_mb` | Size of the memory region to allocate, in megabytes. We use **1024** (1 GB), which is 128× the L3 cache size (8 MB). This ensures the working set far exceeds all cache levels, forcing the CPU to access main memory through the page table/TLB. |
| `iterations` | Number of times to repeat the access pattern over the entire array. We use **3** iterations per run. More iterations increase the total work, making the timing more stable and the effect of TLB misses more pronounced. |
| `pattern` | One of `seq`, `rand`, or `stride`. Determines how the array is traversed. |
| `stride_bytes` | Required only when `pattern=stride`. The number of bytes between successive accesses. |
| `USE_HUGEPAGES` | Environment variable. Set to `1` to request 2 MB huge pages via `madvise(MADV_HUGEPAGE)`. If unset or `0`, the program requests `madvise(MADV_NOHUGEPAGE)` to force standard 4 KB pages. |

### How the Program Works Internally

1. **Memory Allocation**: The program allocates `size_mb` megabytes of memory using `mmap()` with `MAP_PRIVATE | MAP_ANONYMOUS`. This creates a private, anonymous memory mapping backed by physical RAM (no file).

2. **Page Size Configuration**: Based on the `USE_HUGEPAGES` environment variable:
   - If `USE_HUGEPAGES=1`: calls `madvise(p, size, MADV_HUGEPAGE)` — this tells the kernel "please back this memory region with 2 MB huge pages."
   - Otherwise: calls `madvise(p, size, MADV_NOHUGEPAGE)` — this tells the kernel "do NOT use huge pages for this region, use standard 4 KB pages only."

3. **Prefaulting**: Before timing begins, the program touches every page by writing to every 4096th byte:
   ```c
   for (size_t i = 0; i < size; i += 4096) p[i] = 1;
   ```
   This forces the kernel to allocate physical pages and populate page table entries for the entire region. Without prefaulting, the first access to each page would trigger a page fault, mixing page fault overhead with the access pattern timing. By prefaulting, we pay the page fault cost upfront (before the timer starts) and measure only the access pattern performance.

4. **Timed Execution**: The program records a high-resolution timestamp using `clock_gettime(CLOCK_MONOTONIC)`, runs the chosen access pattern for the specified number of iterations, then records another timestamp. The difference is the execution time.

5. **Output**: Produces a structured `RESULT:` line on stdout (for machine parsing) and a human-readable line on stderr.

### Access Pattern Functions

#### Sequential (`seq`)
```c
void sequential(volatile uint8_t* p, size_t size) {
    for (size_t i = 0; i < size; i++) p[i]++;
}
```
Walks through every byte linearly from beginning to end. This is the **best case** for the hardware prefetcher and TLB: once a page is loaded into the TLB, all subsequent accesses within that page are TLB hits. With 4 KB pages, each TLB entry covers 4,096 byte accesses; with 2 MB pages, each entry covers 2,097,152 byte accesses.

#### Random (`rand`)
```c
void random_access(volatile uint8_t* p, size_t size) {
    srand(42); // Fixed seed for reproducibility
    for (size_t i = 0; i < size; i++) {
        size_t idx = rand() % size;
        p[idx]++;
    }
}
```
Generates random indices and accesses them. The fixed seed `42` ensures reproducibility across runs. This is the **worst case** for TLB performance: each random access can potentially land on a different page. With 1 GB of memory mapped in 4 KB pages, there are 262,144 distinct pages. A typical CPU has ~1,500 TLB entries, so the TLB hit rate is effectively near zero for random access.

#### Strided (`stride`)
```c
void strided(volatile uint8_t* p, size_t size, size_t stride) {
    for (size_t i = 0; i < size; i += stride) p[i]++;
}
```
Accesses every `stride`-th byte. With `stride=4096`, this touches exactly one byte per 4 KB page — this is a deliberate worst case for 4 KB pages (maximum page table entries touched per byte of data) while being friendly to 2 MB pages (each huge page covers 512 such accesses). With `stride=65536`, it touches even fewer locations (one per 64 KB).

---

## Step 4 — Run a Single Manual Experiment (Optional Sanity Check)

Before running the full automated suite, you can verify everything works with a single manual run.

### Command: Sequential Access, 4 KB Pages, with perf stat

```bash
sync
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
USE_HUGEPAGES=0 perf stat -e page-faults,minor-faults,major-faults,dTLB-load-misses,dTLB-store-misses,iTLB-load-misses,cycles,instructions ./load 1024 3 seq
```

### Expected Output (stderr — from program):

```
Config: size=1024MB iterations=3 pattern=seq stride=1 pages=4KB
Time: 1.086648 seconds
```

### Expected Output (stdout — structured result):

```
RESULT: pattern=seq page_config=4KB size_mb=1024 iterations=3 stride=1 time_sec=1.086648
```

### Expected Output (perf stat output):

```
 Performance counter stats for './load 1024 3 seq':

           262,278      page-faults
           262,278      minor-faults
                 0      major-faults
           796,780      dTLB-load-misses
         2,531,408      dTLB-store-misses
           270,654      iTLB-load-misses
     5,824,367,500      cycles
    21,049,030,869      instructions                     #    3.61  insn per cycle

       1.370639491 seconds time elapsed

       1.130236000 seconds user
       0.240050000 seconds sys
```

### Detailed Explanation of Each Command Component

#### `sync`
Flushes all pending filesystem writes to disk. This ensures that any dirty buffers are written out before we drop caches, so the experiment starts with a clean state.

#### `sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'`
Drops all kernel caches:
- **1** = Free pagecache (file data cached in RAM)
- **2** = Free dentries and inodes (filesystem metadata caches)
- **3** = Free all of the above

This ensures a **cold-start** condition. Without dropping caches, the kernel might reuse previously cached page table entries or TLB-related structures, making results inconsistent between runs. Requires `sudo` because writing to `/proc/sys/vm/drop_caches` requires root privileges.

#### `USE_HUGEPAGES=0`
Sets the environment variable to `0` for this command only. The program reads this variable and calls `madvise(MADV_NOHUGEPAGE)`, explicitly telling the kernel to use standard 4 KB pages.

#### `perf stat -e <events>`
The `perf stat` command runs the given program and collects hardware performance counter statistics. The `-e` flag specifies which events to monitor:

| Event | Description |
|---|---|
| `page-faults` | Total page faults (minor + major). A page fault occurs when the CPU accesses a virtual address that has no corresponding physical page in the page table. The kernel must then allocate a physical page and create the mapping. |
| `minor-faults` | Page faults that are resolved without disk I/O. For our anonymous memory (`MAP_ANONYMOUS`), all faults are minor: the kernel simply allocates a zero-filled physical page. |
| `major-faults` | Page faults requiring disk I/O (e.g., reading a swapped-out page from swap). In our experiment, this should always be 0 since we have enough RAM and the memory is anonymous. |
| `dTLB-load-misses` | Misses in the data Translation Lookaside Buffer for load (read) operations. When the CPU performs a memory read, it first checks the dTLB to translate the virtual address to a physical address. If the dTLB doesn't have the translation cached, it's a miss and the CPU must walk the page table — a process that takes 10-100+ cycles. |
| `dTLB-store-misses` | Misses in the data TLB for store (write) operations. Same concept as above, but for write operations. Our benchmark increments bytes (`p[i]++`), which involves both a load and a store. |
| `iTLB-load-misses` | Misses in the instruction TLB. This tracks TLB misses for fetching instructions (the program's own code). Typically much lower than dTLB misses since the program code is small and fits in a few pages. |
| `cycles` | Total CPU cycles consumed. This includes cycles spent executing instructions AND cycles stalled waiting for memory (TLB misses, cache misses, etc.). |
| `instructions` | Total retired instructions. This counts useful work done by the CPU. |
| `insn per cycle` (derived) | **IPC (Instructions Per Cycle)** = instructions / cycles. This is the single best indicator of CPU efficiency. Higher IPC means the CPU is spending more cycles doing useful work and less time stalled. |

### Detailed Explanation of the perf stat Output

Let's analyze each metric from the actual output:

#### `262,278 page-faults` and `262,278 minor-faults`
With 4 KB pages and a 1 GB (1,073,741,824 bytes) allocation:
- **Theoretical pages**: 1,073,741,824 / 4,096 = **262,144** pages
- **Observed**: 262,278 (262,144 data pages + ~134 overhead pages for program's stack, heap metadata, shared libraries, etc.)
- All faults are **minor** (no disk I/O needed) — the kernel simply allocated zero-filled physical pages.
- **0 major-faults** confirms no swapping occurred, meaning the system had sufficient free RAM.

#### `796,780 dTLB-load-misses`
During the 3 iterations of sequential access over 1 GB:
- Total byte accesses = 1,073,741,824 × 3 = **3,221,225,472** accesses
- dTLB load misses = 796,780
- **dTLB miss rate** = 796,780 / 3,221,225,472 = **0.025%** (extremely low)
- This is because sequential access has excellent spatial locality: once a page's TLB entry is loaded, the next ~4,096 byte accesses are TLB hits. The small number of misses corresponds roughly to the number of page boundaries crossed.

#### `2,531,408 dTLB-store-misses`
Higher than load misses because the `p[i]++` operation is a read-modify-write: the store part has additional TLB overhead related to write permissions and dirty page tracking.

#### `5,824,367,500 cycles` and `21,049,030,869 instructions`
- **IPC = 21,049,030,869 / 5,824,367,500 = 3.61**
- An IPC of 3.61 indicates the CPU pipeline is running very efficiently. Modern Intel CPUs can issue up to 4-5 µops per cycle, so 3.61 is near the theoretical maximum for compute-bound workloads.
- This high IPC means the sequential access pattern is **not bottlenecked by TLB or memory** — the hardware prefetcher is successfully predicting and pre-loading data.

#### `1.370639491 seconds time elapsed`
The total wall-clock time including all overhead (process startup, perf instrumentation, etc.).

#### `1.130236000 seconds user` / `0.240050000 seconds sys`
- **User time**: CPU time spent executing the program's code (the access patterns).
- **System time**: CPU time spent in kernel code — primarily handling page faults (262K page faults × kernel page fault handler). This is the cost of setting up page table entries.

---

## Step 5 — Run the Full Automated Experiment Suite

### Command

```bash
cd synthetic-workload
sudo bash run_experiments.sh
```

(`sudo` is needed because the script drops caches via `/proc/sys/vm/drop_caches` before each run.)

### Full Expected Output

```
=== Compiling load.cpp ===
Compiled successfully.

=== Running Experiments ===
Memory: 1024MB | Iterations: 3 | Repetitions: 3

--- Sequential Access ---
  Running: seq_stride1_4KB_rep1
    Done: seq_stride1_4KB_rep1
  Running: seq_stride1_2MB_rep1
    Done: seq_stride1_2MB_rep1
  Running: seq_stride1_4KB_rep2
    Done: seq_stride1_4KB_rep2
  Running: seq_stride1_2MB_rep2
    Done: seq_stride1_2MB_rep2
  Running: seq_stride1_4KB_rep3
    Done: seq_stride1_4KB_rep3
  Running: seq_stride1_2MB_rep3
    Done: seq_stride1_2MB_rep3
--- Random Access ---
  Running: rand_stride1_4KB_rep1
    Done: rand_stride1_4KB_rep1
  Running: rand_stride1_2MB_rep1
    Done: rand_stride1_2MB_rep1
  Running: rand_stride1_4KB_rep2
    Done: rand_stride1_4KB_rep2
  Running: rand_stride1_2MB_rep2
    Done: rand_stride1_2MB_rep2
  Running: rand_stride1_4KB_rep3
    Done: rand_stride1_4KB_rep3
  Running: rand_stride1_2MB_rep3
    Done: rand_stride1_2MB_rep3
--- Strided Access (stride=4096) ---
  Running: stride_stride4096_4KB_rep1
    Done: stride_stride4096_4KB_rep1
  Running: stride_stride4096_2MB_rep1
    Done: stride_stride4096_2MB_rep1
  Running: stride_stride4096_4KB_rep2
    Done: stride_stride4096_4KB_rep2
  Running: stride_stride4096_2MB_rep2
    Done: stride_stride4096_2MB_rep2
  Running: stride_stride4096_4KB_rep3
    Done: stride_stride4096_4KB_rep3
  Running: stride_stride4096_2MB_rep3
    Done: stride_stride4096_2MB_rep3
--- Strided Access (stride=65536) ---
  Running: stride_stride65536_4KB_rep1
    Done: stride_stride65536_4KB_rep1
  Running: stride_stride65536_2MB_rep1
    Done: stride_stride65536_2MB_rep1
  Running: stride_stride65536_4KB_rep2
    Done: stride_stride65536_4KB_rep2
  Running: stride_stride65536_2MB_rep2
    Done: stride_stride65536_2MB_rep2
  Running: stride_stride65536_4KB_rep3
    Done: stride_stride65536_4KB_rep3
  Running: stride_stride65536_2MB_rep3
    Done: stride_stride65536_2MB_rep3

=== All experiments complete ===
Raw results saved to: raw_results/

Generated files:
(listing of all 72 output files)
```

### Detailed Explanation of What the Script Does

The `run_experiments.sh` script automates the entire experiment matrix:

**Configuration Parameters:**
```bash
SIZE_MB=1024        # 1 GB working set (>> 8MB L3 cache)
ITERATIONS=3        # iterations per run
REPETITIONS=3       # repeat each experiment for statistical stability
STRIDES=(4096 65536)
```

- **Working set = 1024 MB (1 GB)**: This is 128× the L3 cache size. This ensures that the working set far exceeds any CPU cache, so memory accesses must go through the TLB and page table to reach RAM. If the working set fit in L3 cache, TLB performance differences would be masked by cache hits.

- **Iterations = 3**: Each access pattern is repeated 3 times over the array per run. This increases the total number of memory accesses, making timing more stable and TLB effects more measurable.

- **Repetitions = 3**: Each unique configuration is run 3 independent times. This allows computing mean and standard deviation, which quantifies measurement noise and system variability.

**Experiment Matrix:**
The script runs every combination:

| # | Pattern | Page Config | Stride | Repetitions | Label Format |
|---|---|---|---|---|---|
| 1-6 | `seq` | 4KB, 2MB | 1 | 3 each | `seq_stride1_{4KB,2MB}_rep{1,2,3}` |
| 7-12 | `rand` | 4KB, 2MB | 1 | 3 each | `rand_stride1_{4KB,2MB}_rep{1,2,3}` |
| 13-18 | `stride` | 4KB, 2MB | 4096 | 3 each | `stride_stride4096_{4KB,2MB}_rep{1,2,3}` |
| 19-24 | `stride` | 4KB, 2MB | 65536 | 3 each | `stride_stride65536_{4KB,2MB}_rep{1,2,3}` |

**Total runs: 4 patterns × 2 page configs × 3 repetitions = 24 runs**, producing **72 output files** (3 files per run: `_output.txt`, `_perf.txt`, `_stderr.txt`).

**Before each run, the script:**
1. **`sync`** — Flushes filesystem buffers.
2. **`sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches'`** — Drops all kernel caches for cold-start consistency. The `-n` flag makes `sudo` non-interactive (fails silently if no passwordless sudo). If cache dropping fails, it falls back to `sleep 1`.

**Each run executes:**
```bash
USE_HUGEPAGES=$env_hp perf stat -e "$PERF_EVENTS" -o "$RAW_DIR/${label}_perf.txt" \
    ./load $cmd_args > "$RAW_DIR/${label}_output.txt" 2> "$RAW_DIR/${label}_stderr.txt"
```

- `USE_HUGEPAGES=$env_hp` — Sets to `0` for 4KB or `1` for 2MB.
- `perf stat -e ... -o ${label}_perf.txt` — Captures performance counters to a file instead of stderr.
- `> ${label}_output.txt` — Captures the RESULT line from stdout.
- `2> ${label}_stderr.txt` — Captures config string and timing from stderr.

### Approximate Runtime

| Pattern | 4KB Time per Run | 2MB Time per Run | Subtotal (6 runs) |
|---|---|---|---|
| Sequential | ~1.4 s | ~1.1 s | ~7.5 s |
| Random | ~269 s (~4.5 min) | ~172 s (~2.9 min) | ~22 min |
| Stride-4096 | ~0.33 s | ~0.11 s | ~1.3 s |
| Stride-65536 | ~0.33 s | ~0.10 s | ~1.3 s |
| **Total** | | | **~32 min** |

The random access pattern dominates total runtime because it triggers billions of TLB misses, each costing 10-100+ CPU cycles for a page table walk.

---

## Step 6 — Understand the Raw Output Files

Each run produces **3 files** in the `raw_results/` directory. Here is a detailed breakdown using actual outputs from the experiment:

### 6.1 — Perf Stat Output (`*_perf.txt`)

**Example: `seq_stride1_4KB_rep1_perf.txt`** (Sequential, 4KB pages):

```
# started on Fri Mar 20 02:34:02 2026


 Performance counter stats for './load 1024 3 seq':

           262,278      page-faults
           262,278      minor-faults
                 0      major-faults
           796,780      dTLB-load-misses
         2,531,408      dTLB-store-misses
           270,654      iTLB-load-misses
     5,824,367,500      cycles
    21,049,030,869      instructions                     #    3.61  insn per cycle

       1.370639491 seconds time elapsed

       1.130236000 seconds user
       0.240050000 seconds sys
```

**Compare with `seq_stride1_2MB_rep1_perf.txt`** (Sequential, 2MB pages):

```
# started on Fri Mar 20 02:34:04 2026


 Performance counter stats for './load 1024 3 seq':

              642      page-faults
              642      minor-faults
                0      major-faults
            4,192      dTLB-load-misses
           28,933      dTLB-store-misses
            4,867      iTLB-load-misses
    4,828,253,877      cycles
   19,378,556,708      instructions                     #    4.01  insn per cycle

       1.134573693 seconds time elapsed

       1.085154000 seconds user
       0.049052000 seconds sys
```

**Detailed Metric-by-Metric Comparison for Sequential Access:**

| Metric | 4KB Pages | 2MB Pages | Change | Explanation |
|---|---:|---:|---|---|
| **page-faults** | 262,278 | 642 | **99.8% reduction** | With 4KB pages: 1 GB / 4 KB = 262,144 pages (+ ~134 overhead). With 2MB pages: 1 GB / 2 MB = 512 pages (+ ~130 overhead). Each page requires one initial fault during the prefault loop. |
| **minor-faults** | 262,278 | 642 | Same as above | All page faults are minor because the memory is anonymous (no disk backing). The kernel allocates zero-filled physical pages from its free lists. |
| **major-faults** | 0 | 0 | No change | No swapping to disk occurred. The system has sufficient free RAM (16 GB total, ~10 GB available). |
| **dTLB-load-misses** | 796,780 | 4,192 | **99.5% reduction** | With 4KB pages, the TLB can cache ~1,500 page translations (typical Intel TLB size). For sequential access over 262,144 pages, the TLB thrashes modestly. With 2MB pages, only 512 pages exist — they fit more easily in the TLB. |
| **dTLB-store-misses** | 2,531,408 | 28,933 | **98.9% reduction** | Store-side TLB misses are typically higher than load misses because stores require additional permission checks (dirty bit setting) and can trigger second-level TLB lookups. |
| **iTLB-load-misses** | 270,654 | 4,867 | **98.2% reduction** | Instruction TLB misses relate to fetching the program's own code. The dramatic reduction with 2MB pages suggests the program's code + runtime was also backed by huge pages, leading to fewer iTLB misses. |
| **cycles** | 5,824,367,500 | 4,828,253,877 | **17.1% reduction** | Fewer total CPU cycles because fewer TLB misses means fewer expensive page table walks stalling the pipeline. |
| **instructions** | 21,049,030,869 | 19,378,556,708 | **7.9% reduction** | Slightly fewer instructions with 2MB pages because the prefault loop (`for i+=4096`) touches fewer pages (642 vs 262,278 loop iterations). |
| **IPC** | 3.61 | 4.01 | **+11.1%** | Higher IPC with 2MB pages because the CPU spends less time stalled on TLB misses and more time executing useful instructions. An IPC of 4.01 is near the theoretical maximum for this CPU. |
| **sys time** | 0.240s | 0.049s | **79.6% reduction** | System (kernel) time is dominated by page fault handling. With 642 faults vs 262,278 faults, the kernel spends far less time allocating pages. |

---

**Example: `rand_stride1_4KB_rep1_perf.txt`** (Random, 4KB pages):

```
 Performance counter stats for './load 1024 3 rand':

           262,277      page-faults
           262,277      minor-faults
                 0      major-faults
     2,979,808,512      dTLB-load-misses
       238,719,133      dTLB-store-misses
         4,413,433      iTLB-load-misses
 1,115,521,478,674      cycles
   229,644,207,485      instructions                     #    0.21  insn per cycle

     268.083184519 seconds time elapsed

     267.674377000 seconds user
       0.299906000 seconds sys
```

**Compare with `rand_stride1_2MB_rep1_perf.txt`** (Random, 2MB pages):

```
 Performance counter stats for './load 1024 3 rand':

              644      page-faults
              644      minor-faults
                0      major-faults
        6,508,668      dTLB-load-misses
        1,225,612      dTLB-store-misses
          794,594      iTLB-load-misses
  667,502,151,778      cycles
  227,007,941,047      instructions                     #    0.34  insn per cycle

     162.151743955 seconds time elapsed

     159.846632000 seconds user
       0.121889000 seconds sys
```

**Detailed Metric-by-Metric Comparison for Random Access:**

| Metric | 4KB Pages | 2MB Pages | Change | Explanation |
|---|---:|---:|---|---|
| **dTLB-load-misses** | 2,979,808,512 | 6,508,668 | **99.8% reduction** | This is the most dramatic metric. With random access over 262,144 (4KB) pages and ~1,500 TLB entries, nearly every access misses the TLB — resulting in ~3 billion TLB misses for ~3.2 billion total accesses. With 2MB pages, only 512 pages exist; many fit in the TLB, reducing misses by 99.8%. |
| **cycles** | 1,115,521,478,674 | 667,502,151,778 | **40.2% reduction** | Nearly half the CPU cycles were consumed by TLB miss penalty (page table walks). Each page table walk on a 4-level page table takes 10-100+ cycles, and with 3 billion TLB misses, this amounts to hundreds of billions of wasted cycles. |
| **IPC** | 0.21 | 0.34 | **+62% improvement** | An IPC of 0.21 means the CPU is executing only 1 instruction every ~5 cycles — it's stalled 80% of the time waiting for TLB/memory. With 2MB pages, IPC improves to 0.34, but remains low because random access still causes many cache misses (the data doesn't fit in L3 cache). |
| **wall_time** | 268.08 s | 162.15 s | **39.5% faster** | Direct consequence of the cycle reduction. Random access goes from ~4.5 minutes to ~2.7 minutes with huge pages. |

**Why Random Access Has Such Extreme TLB Miss Counts:**
In the random access pattern, the program makes `size` (1,073,741,824) random accesses per iteration, for a total of ~3.2 billion accesses across 3 iterations. Each random access generates an address uniformly distributed across 1 GB. With 4 KB pages, there are 262,144 possible pages. Since a typical Intel CPU TLB holds ~1,500 entries (L1 dTLB: 64, L2 sTLB: ~1,500), the probability of a TLB hit for any random access is only ~1,500/262,144 = **0.57%**. This means ~99.4% of all 3.2 billion accesses miss the TLB, resulting in ~3 billion TLB misses. With 2 MB pages, there are only 512 pages, all of which fit in the L2 sTLB (~1,500 entries), so the TLB hit rate jumps to nearly 100%.

---

**Example: `stride_stride4096_4KB_rep1_perf.txt`** (Stride 4096, 4KB pages):

```
 Performance counter stats for './load 1024 3 stride 4096':

           262,277      page-faults
           262,277      minor-faults
                 0      major-faults
           556,951      dTLB-load-misses
         2,772,422      dTLB-store-misses
           268,267      iTLB-load-misses
     1,369,239,471      cycles
     1,710,406,783      instructions                     #    1.25  insn per cycle

       0.330118025 seconds time elapsed

       0.044863000 seconds user
       0.285132000 seconds sys
```

**Compare with `stride_stride4096_2MB_rep1_perf.txt`** (Stride 4096, 2MB pages):

```
 Performance counter stats for './load 1024 3 stride 4096':

              645      page-faults
              645      minor-faults
                0      major-faults
            3,472      dTLB-load-misses
           26,081      dTLB-store-misses
            2,803      iTLB-load-misses
       437,736,568      cycles
        48,075,573      instructions                     #    0.11  insn per cycle

       0.107098608 seconds time elapsed

       0.013011000 seconds user
       0.094085000 seconds sys
```

**Key Observation — The Strided IPC Anomaly:**

The IPC *drops* from 1.25 (4KB) to 0.11 (2MB) with huge pages. This seems counterintuitive. The explanation is:

- With 4KB pages, **262,277 page faults** are handled by the kernel. Page fault handling involves executing many kernel instructions (allocating pages, updating page tables). These kernel instructions inflate both the `cycles` and `instructions` counts, resulting in an artificially elevated IPC of 1.25.
- With 2MB pages, only **645 page faults** occur, so the kernel contributes far fewer instructions. The remaining work (the actual stride loop) does very few operations (~262,144 accesses × 3 iterations = ~786,000 accesses), and the IPC of 0.11 reflects that each access involves a load-modify-store on a widely separated memory location, causing many cache misses relative to the number of instructions.
- **The IPC metric is misleading for strided access** because the workload does so little computational work that the overhead (page faults, perf instrumentation) dominates. The meaningful metric here is **wall clock time**, which shows 0.33s → 0.11s (**67% reduction**).

---

**Example: `stride_stride65536_4KB_rep1_perf.txt`** (Stride 65536, 4KB pages):

```
 Performance counter stats for './load 1024 3 stride 65536':

           262,276      page-faults
           262,276      minor-faults
                 0      major-faults
            57,332      dTLB-load-misses
         2,531,797      dTLB-store-misses
           267,740      iTLB-load-misses
     1,334,372,433      cycles
     1,695,985,368      instructions                     #    1.27  insn per cycle

       0.326760741 seconds time elapsed

       0.032058000 seconds user
       0.294534000 seconds sys
```

**Compare with `stride_stride65536_2MB_rep1_perf.txt`** (Stride 65536, 2MB pages):

```
 Performance counter stats for './load 1024 3 stride 65536':

              644      page-faults
              644      minor-faults
                0      major-faults
            2,326      dTLB-load-misses
           26,475      dTLB-store-misses
            2,565      iTLB-load-misses
       403,949,445      cycles
        42,963,733      instructions                     #    0.11  insn per cycle

       0.098921940 seconds time elapsed

       0.004999000 seconds user
       0.093994000 seconds sys
```

**Key Observations for Stride-65536:**
- **dTLB-load-misses**: 57,332 → 2,326 (95.9% reduction). The reduction is less dramatic than stride-4096 because with stride=65536, only ~16,384 unique addresses are accessed per iteration (1 GB / 65536 = 16,384), which already fits partially in the TLB with 4KB pages.
- **User vs Sys time for 4KB**: 0.032s user vs 0.295s sys — the kernel (sys) time dominates entirely! The actual computation finishes in 32 ms, but handling 262,276 page faults takes 295 ms. With 2MB pages: 0.005s user vs 0.094s sys — still kernel-dominated but much less.

---

### 6.2 — Program Output (`*_output.txt`)

**Example: `seq_stride1_4KB_rep1_output.txt`:**

```
RESULT: pattern=seq page_config=4KB size_mb=1024 iterations=3 stride=1 time_sec=1.086648
```

**Explanation:** This structured output line is designed for machine parsing by the analysis script. It contains:
- `pattern=seq` — Which access pattern was used.
- `page_config=4KB` — Whether 4KB or 2MB pages were used.
- `size_mb=1024` — Total memory allocation size.
- `iterations=3` — How many full passes over the array.
- `stride=1` — The stride distance (1 for seq/rand, the actual stride for stride pattern).
- `time_sec=1.086648` — The precise execution time measured by `clock_gettime(CLOCK_MONOTONIC)`, which excludes process startup, prefaulting, and perf overhead. This is the "clean" timing of just the access pattern.

**Example: `rand_stride1_4KB_rep1_output.txt`:**

```
RESULT: pattern=rand page_config=4KB size_mb=1024 iterations=3 stride=1 time_sec=267.750835
```

Note that `time_sec` (267.75s) is slightly less than the perf-reported wall time (268.08s) because the program's timer excludes process startup and the prefault phase.

### 6.3 — Program Stderr (`*_stderr.txt`)

**Example: `seq_stride1_4KB_rep1_stderr.txt`:**

```
Config: size=1024MB iterations=3 pattern=seq stride=1 pages=4KB
Time: 1.086648 seconds
```

**Explanation:** These are human-readable diagnostic messages. The first line confirms the configuration that was actually used (as a sanity check — e.g., verifying that `pages=4KB` was correctly set). The second line echoes the execution time. This is useful for monitoring progress during long runs (especially the ~4.5 min random access runs).

---

## Step 7 — Run the Analysis Script

### Command

```bash
cd synthetic-workload
source .venv/bin/activate
python3 analyze_results.py
```

### Expected Output

```
Discovering experiments...
Found 8 configurations, 24 total runs

Aggregating results...

Saving CSV...
Saved CSV: /home/uttu/Desktop/spe-proj/synthetic-workload/results.csv

Generating charts...
Generated: page_faults.png
Generated: dtlb_load_misses.png
Generated: execution_time.png
Generated: ipc.png
Generated: cpu_cycles.png
Generated: dtlb_store_misses.png
Generated: improvement_summary.png

====================================================================================================
SYNTHETIC WORKLOAD RESULTS SUMMARY
====================================================================================================
Config                   Page Faults  dTLB-Load-Miss    dTLB-Store-Miss          IPC    Time(s)
----------------------------------------------------------------------------------------------------
rand (2MB)                    644 ±0       7,981,998          1,465,161         0.32   172.4231
rand (4KB)               262,276 ±0   2,977,257,118        240,865,284         0.21   268.8765
seq (2MB)                     643 ±1           4,550             28,896         3.87     1.1203
seq (4KB)                 262,278 ±0         797,978          2,541,205         3.56     1.1080
stride-4096 (2MB)             645 ±0           3,456             25,244         0.11     0.0093
stride-4096 (4KB)         262,276 ±1         560,041          2,762,558         1.24     0.0096
stride-65536 (2MB)            644 ±0           2,703             26,251         0.11     0.0007
stride-65536 (4KB)        262,276 ±0          59,341          2,522,223         1.26     0.0015
====================================================================================================

All outputs saved to:
  CSV:   /home/uttu/Desktop/spe-proj/synthetic-workload/results.csv
  Plots: /home/uttu/Desktop/spe-proj/synthetic-workload/plots/
```

### Detailed Explanation of What the Analysis Script Does

The `analyze_results.py` script performs the following steps:

#### 1. Discovery Phase (`discover_experiments()`)

The script scans the `raw_results/` directory for all files matching the pattern `*_perf.txt`. For each file, it:
- Extracts the **label** from the filename (e.g., `seq_stride1_4KB_rep1`).
- Parses the label to extract the **config key** (e.g., `seq_stride1_4KB`) and **repetition number** (e.g., `1`).
- Groups all repetitions under the same config key.

It finds **8 configurations** (4 patterns × 2 page configs) with **24 total runs** (8 × 3 repetitions).

#### 2. Parsing Phase (`parse_perf_file()` + `parse_output_file()`)

For each run, the script parses:
- **Perf file**: Extracts all numeric metrics (page-faults, dTLB-load-misses, etc.) using regex matching of lines like `262,278      page-faults`. Also extracts wall time and IPC.
- **Output file**: Extracts the RESULT line's key-value pairs to get the program-measured `time_sec`.

#### 3. Aggregation Phase (`aggregate()`)

For each configuration, the script computes the **mean** and **standard deviation** across the 3 repetitions for every numeric metric:
```python
row[f'{key}_mean'] = np.mean(vals)
row[f'{key}_std'] = np.std(vals)
```

The standard deviation quantifies run-to-run variability. Low std (e.g., `±0` or `±1` for page faults) indicates highly reproducible results. Higher std (e.g., for dTLB misses) may indicate system background noise.

#### 4. CSV Generation (`save_csv()`)

Saves all aggregated data to `results.csv` — a complete flat table with one row per configuration, containing means and standard deviations for every metric. This file can be imported into spreadsheet tools or other analysis scripts.

**CSV Structure (columns):**
`config, pattern, stride, page_config, page-faults_mean, page-faults_std, minor-faults_mean, minor-faults_std, major-faults_mean, major-faults_std, dTLB-load-misses_mean, dTLB-load-misses_std, dTLB-store-misses_mean, dTLB-store-misses_std, iTLB-load-misses_mean, iTLB-load-misses_std, cycles_mean, cycles_std, instructions_mean, instructions_std, wall_time_sec_mean, wall_time_sec_std, IPC_mean, IPC_std, time_sec_mean, time_sec_std`

#### 5. Chart Generation (`create_comparison_charts()`)

The script generates **7 charts** comparing 4 KB vs 2 MB pages:

| Chart | File | Description |
|---|---|---|
| Page Faults | `plots/page_faults.png` | Bar chart comparing total page faults per pattern. Uses log scale since 4KB values are ~400× larger. |
| dTLB Load Misses | `plots/dtlb_load_misses.png` | Bar chart showing data TLB load misses. Reveals the ~3 billion misses for random/4KB. |
| dTLB Store Misses | `plots/dtlb_store_misses.png` | Bar chart for store-side TLB misses. |
| Execution Time | `plots/execution_time.png` | Wall-clock execution time comparison. Log scale to show both sub-second strided and multi-minute random tests. |
| IPC | `plots/ipc.png` | Instructions Per Cycle — the CPU efficiency metric. Linear scale to show the range from 0.11 to 3.87. |
| CPU Cycles | `plots/cpu_cycles.png` | Total CPU cycles consumed. Log scale. |
| Improvement Summary | `plots/improvement_summary.png` | Two side-by-side charts showing percentage reduction in page faults and dTLB load misses when switching from 4KB to 2MB pages. |

All charts use:
- **Blue bars** for 4 KB pages
- **Red bars** for 2 MB pages
- **Error bars** showing ± 1 standard deviation
- **Log scale** (where appropriate) to handle the large dynamic range

#### 6. Summary Table

Prints a formatted ASCII table to stdout showing key metrics for all 8 configurations.

---

## Step 8 — Interpret the Results

### 8.1 — Aggregated Results Summary

| Config | Page Faults | dTLB Load Misses | dTLB Store Misses | IPC | Time (s) |
|---|---:|---:|---:|---:|---:|
| seq (4KB) | 262,278 | 797,978 | 2,541,205 | 3.56 | 1.108 |
| seq (2MB) | 643 | 4,550 | 28,896 | 3.87 | 1.120 |
| rand (4KB) | 262,276 | 2,977,257,118 | 240,865,284 | 0.21 | 268.876 |
| rand (2MB) | 644 | 7,981,998 | 1,465,161 | 0.32 | 172.423 |
| stride-4096 (4KB) | 262,276 | 560,041 | 2,762,558 | 1.24 | 0.010 |
| stride-4096 (2MB) | 645 | 3,456 | 25,244 | 0.11 | 0.009 |
| stride-65536 (4KB) | 262,276 | 59,341 | 2,522,223 | 1.26 | 0.002 |
| stride-65536 (2MB) | 644 | 2,703 | 26,251 | 0.11 | 0.001 |

### 8.2 — Page Faults (Universal ~99.8% Reduction)

**Key Finding**: Across ALL access patterns, page faults drop from ~262,276 to ~644 — a **407× reduction**.

**Mathematical explanation**:
- 4KB pages: 1,073,741,824 bytes / 4,096 bytes per page = **262,144 pages** (+ ~134 overhead pages = ~262,278)
- 2MB pages: 1,073,741,824 bytes / 2,097,152 bytes per page = **512 pages** (+ ~132 overhead pages = ~644)

This result is **pattern-independent** because page faults occur during the prefault phase (before the timed access loop), not during the access pattern itself. The prefault loop (`for i += 4096; p[i] = 1`) touches every page, triggering one minor page fault per page regardless of the access pattern that follows.

### 8.3 — dTLB Load Misses (Pattern-Dependent Reduction)

| Pattern | 4KB Misses | 2MB Misses | Reduction % |
|---|---:|---:|---:|
| Sequential | 797,978 | 4,550 | 99.4% |
| Random | 2,977,257,118 | 7,981,998 | 99.7% |
| Stride-4096 | 560,041 | 3,456 | 99.4% |
| Stride-65536 | 59,341 | 2,703 | 95.4% |

**Why random access has 3 billion TLB misses with 4KB pages:**
- Total accesses = 1,073,741,824 × 3 iterations = 3,221,225,472 random addresses
- Each address is uniformly random across 262,144 possible 4KB pages
- TLB capacity ≈ 1,500 entries (Intel L1 dTLB: 64, L2 sTLB: ~1,500)
- TLB hit probability ≈ 1,500 / 262,144 = 0.57%
- Expected TLB misses ≈ 3,221,225,472 × 0.9943 ≈ **3.2 billion** (observed: 2.98 billion)

**Why random access has only 8 million TLB misses with 2MB pages:**
- Same 3.2 billion random accesses, but now across only 512 huge pages
- TLB capacity ≈ 1,500 entries > 512 pages → all pages can fit in the TLB!
- The 8 million residual misses are caused by:
  - Initial TLB warm-up (cold-start misses on first access to each page)
  - TLB eviction pressure from instruction TLB and OS kernel interrupts
  - Some TLB entries may be evicted due to TLB associativity limitations

**Why stride-65536 has fewer 4KB TLB misses (59K vs 560K for stride-4096):**
- Stride-4096 accesses 262,144 unique addresses per iteration (one per page), crossing every page boundary.
- Stride-65536 accesses only 16,384 unique addresses per iteration (one per 64 KB), crossing only every 16th page boundary. Fewer unique pages means the TLB can cache a larger fraction of them.

### 8.4 — Execution Time Impact

| Pattern | 4KB Time | 2MB Time | Speedup | Why |
|---|---:|---:|---|---|
| Sequential | 1.108s | 1.120s | **0.99×** (no improvement) | TLB is already efficient due to excellent spatial locality |
| Random | 268.876s | 172.423s | **1.56×** (36% faster) | Massive TLB miss reduction directly translates to time savings |
| Stride-4096 | 0.010s | 0.009s | **1.06×** (marginal) | Very little work; page fault reduction helps but absolute time is tiny |
| Stride-65536 | 0.002s | 0.001s | **~2.21×** | Sub-millisecond already; relative improvement looks large but absolute improvement is 0.8 ms |

**The key insight**: Huge pages deliver meaningful **absolute** time savings only when the workload has **high TLB miss pressure** (random access). For access patterns with good spatial locality (sequential) or very little total work (strided), the improvement is negligible in absolute terms.

### 8.5 — IPC (Instructions Per Cycle)

IPC is the ratio of **useful instructions executed** to **total CPU cycles consumed**:

- **IPC = 3.56 (seq/4KB) → 3.87 (seq/2MB)**: Both are near the CPU maximum (~4-5). Sequential access runs near peak efficiency regardless of page size.
- **IPC = 0.21 (rand/4KB) → 0.32 (rand/2MB)**: The pipeline is stalled 80-95% of the time waiting for TLB/memory lookups. Even with 2MB pages, random access still thrashes the CPU caches (L1 = 32KB, L2 = 256KB, L3 = 8MB vs 1GB working set).
- **IPC = 1.24 (stride/4KB) → 0.11 (stride/2MB)**: The seeming decrease is an artifact. With 4KB pages, the kernel executes millions of instructions handling 262K page faults, inflating the instruction count. With 2MB pages, only 645 page faults occur, and the actual loop does very few instructions, so the IPC appears low but the total time is actually faster.

---

## Complete File Inventory

After running the full experiment pipeline, the `synthetic-workload/` directory contains:

```
synthetic-workload/
├── load.cpp                          # Source code for the benchmark
├── load                              # Compiled benchmark binary
├── run_experiments.sh                # Automation script
├── analyze_results.py                # Data analysis and charting script
├── results.csv                       # Aggregated results (mean ± std)
├── results.md                        # Markdown report with findings
├── flow.md                           # This document
├── .venv/                            # Python virtual environment
├── raw_results/                      # 72 raw output files (24 runs × 3 files each)
│   ├── seq_stride1_4KB_rep1_perf.txt       # perf stat output
│   ├── seq_stride1_4KB_rep1_output.txt     # RESULT line (structured data)
│   ├── seq_stride1_4KB_rep1_stderr.txt     # Config & timing (human-readable)
│   ├── seq_stride1_4KB_rep2_perf.txt
│   ├── ...
│   ├── seq_stride1_2MB_rep1_perf.txt
│   ├── ...
│   ├── rand_stride1_4KB_rep1_perf.txt
│   ├── ...
│   ├── rand_stride1_2MB_rep1_perf.txt
│   ├── ...
│   ├── stride_stride4096_4KB_rep1_perf.txt
│   ├── ...
│   ├── stride_stride4096_2MB_rep1_perf.txt
│   ├── ...
│   ├── stride_stride65536_4KB_rep1_perf.txt
│   ├── ...
│   └── stride_stride65536_2MB_rep3_stderr.txt
└── plots/                            # 7 generated charts
    ├── page_faults.png               # Page faults: 4KB vs 2MB
    ├── dtlb_load_misses.png          # dTLB load misses comparison
    ├── dtlb_store_misses.png         # dTLB store misses comparison
    ├── execution_time.png            # Wall-clock execution time
    ├── ipc.png                       # Instructions Per Cycle
    ├── cpu_cycles.png                # Total CPU cycles
    └── improvement_summary.png       # Percentage reduction summary
```

### Naming Convention for Raw Files

Each raw result file follows the naming pattern:

```
{pattern}_stride{stride_bytes}_{page_config}_rep{repetition}_{type}.txt
```

| Component | Values | Example |
|---|---|---|
| `pattern` | `seq`, `rand`, `stride` | `rand` |
| `stride_bytes` | `1` (for seq/rand), `4096`, `65536` | `stride4096` |
| `page_config` | `4KB`, `2MB` | `4KB` |
| `repetition` | `1`, `2`, `3` | `rep2` |
| `type` | `perf` (perf stat), `output` (RESULT line), `stderr` (diagnostics) | `perf` |

**Full example**: `rand_stride1_4KB_rep2_perf.txt` = Random access, stride 1, using 4KB pages, repetition 2, perf stat output.
