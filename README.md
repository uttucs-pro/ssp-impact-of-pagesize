# Project Proposal: Analyzing the Performance Impact of Page Faults and Page Size on Applications

Modern operating systems rely on virtual memory to efficiently manage physical memory and provide isolation across applications. A key design parameter in virtual memory systems is page size, which directly influences page fault behavior, Translation Lookaside Buffer (TLB) efficiency, and memory access latency. While smaller pages reduce internal fragmentation, they increase TLB pressure and page table overhead, whereas larger pages reduce TLB misses but may negatively impact memory utilization and latency predictability. Linux supports multiple page sizes through base pages and huge pages, yet the performance implications of page size selection remain highly workload-dependent. This project aims to experimentally analyze how page size affects page fault behavior and application performance across representative real-world workloads.

The objective of this project is to systematically study the relationship between page size, page faults, and end-to-end performance metrics such as latency and throughput. The study focuses on understanding how different memory access patterns interact with page size choices and how these interactions vary across application domains. The project evaluates both kernel-level metrics, such as minor and major page faults and TLB miss rates, and application-level performance outcomes to derive workload-aware insights into memory management trade-offs.

The experimental evaluation will be conducted on a Linux-based system with a fixed hardware and software configuration to ensure reproducibility. Page size configurations will be controlled using Linux Transparent Huge Pages (THP), allowing comparison between default 4 KB pages and 2 MB huge pages. Application-directed page size behavior will also be explored using the madvise() system call with MADV_HUGEPAGE and MADV_NOHUGEPAGE. Kernel memory behavior and page size settings will be managed and observed using the /sys and /proc filesystem interfaces.

Performance measurement and instrumentation will primarily be performed using the Linux perf tool, which provides access to hardware and kernel performance counters. Metrics collected include total page faults, minor and major page faults, data and instruction TLB misses, CPU cycles, and instructions retired. System-level memory activity will be monitored using vmstat to capture paging behavior and memory pressure. Experimental data will be analyzed and visualized using Python with pandas and matplotlib to identify trends, compare configurations, and present results clearly.

To establish baseline behavior and isolate the effects of page size, the project will begin with a synthetic memory benchmark implemented in C/C++. This benchmark will generate controlled memory access patterns, including sequential, random, and strided accesses, over working set sizes that exceed cache capacity. For this workload, the project will measure page fault rates, TLB miss rates, and execution time under different page size configurations, providing a ground-truth understanding of how access patterns interact with page size.

Database workloads will be evaluated using SQLite or PostgreSQL, with the sysbench OLTP benchmark used to generate realistic database access patterns. Both read-only and read-write workloads will be executed to represent point lookups, index traversal, and buffer pool usage. For database workloads, the project will measure queries per second, latency percentiles (including tail latency), and page fault behavior to assess how page size impacts random-access-heavy applications.

Web server workloads will be evaluated using nginx configured for static file serving, with load generated using the wrk benchmarking tool. Experiments will include serving both small and large static files under varying levels of concurrency. For this workload, the project will measure request throughput, latency distributions, and page fault rates to analyze how page size interacts with the operating system page cache and web-serving access patterns.

Machine learning workloads will be evaluated using PyTorch-based benchmarks focusing on large model loading and inference execution. These workloads are representative of applications that allocate large contiguous memory regions and exhibit high memory bandwidth demands. Metrics collected for machine learning workloads include model load time, inference latency, and page fault and TLB miss behavior, allowing evaluation of the benefits of large pages for memory-intensive applications.

Each experiment will be conducted under identical system conditions, with page size configuration being the only controlled variable. Benchmarks will be repeated multiple times to ensure statistical robustness, and both warm-cache and cold-start scenarios will be considered where applicable. Results will be analyzed comparatively across workloads to identify when larger page sizes provide measurable benefits and when they introduce performance regressions.

The expected outcome of this project is a comprehensive, workload-aware characterization of how page size influences page fault behavior and application performance. The study aims to demonstrate that large pages are not universally beneficial and that page size tuning must be informed by workload memory access patterns. The project will conclude with practical insights into memory management decisions in modern operating systems and their implications for performance engineering.

# Objectives

- The primary objectives of this project are:

- To quantify page fault behavior under different page size configurations

- To evaluate the impact of page size on TLB efficiency

- To measure application-level performance changes (latency and throughput)

- To compare behavior across different application domains

- To identify scenarios where large pages are beneficial or detrimental

# Exhaustive List of Measurements

## 1. Virtual Memory & Page Fault Metrics (Core Focus)

- Total page faults

- Minor (soft) page faults

- Pages already in memory, mapped on demand

- Major (hard) page faults

- Disk I/O required

- Page faults per second

- Page faults per request / per operation

- Page faults per GB of memory accessed

Used to quantify how page size affects fault frequency and fault cost.

## 2. TLB (Translation Lookaside Buffer) Metrics

- These explain why page faults change with page size.

- Data TLB load misses

- Instruction TLB load misses

- TLB miss rate (misses / memory accesses)

- TLB misses per second

- TLB misses per request / iteration

- Used to study TLB pressure and page table traversal overhead.
  
## 3. CPU Execution & Efficiency Metrics

These capture indirect performance impact.

- CPU cycles

- Instructions retired

- Instructions per cycle (IPC)

- Cycles per instruction (CPI)

- CPU utilization (%)

- Context switches (optional)

- Used to link memory behavior to CPU efficiency.

## 4. Memory System Metrics

These provide system-level context.

- Resident Set Size (RSS)

- Virtual memory size (VSZ)

- Memory bandwidth (where applicable)

- Page-ins and page-outs

- Swap activity (if any)

- Working set size

- Cache warm vs cold state indicators

Used to rule out memory pressure or swapping as confounding factors.

## 5. Application-Level Performance Metrics (Critical)

These make the project application-relevant.

- General (all workloads)

- Execution time

- Throughput

- Latency (mean, median)

- Tail latency (p95, p99)

- Operations per second

## 6. Workload-Specific Metrics

- Synthetic Memory Benchmark
  
  - Execution time per access pattern
  
  - Memory access rate
  
  - Page faults per access pattern
  
  - TLB misses per access pattern

- Database Workloads
  
  - Queries per second (QPS)
  
  - Transaction latency
  
  - Tail latency (p99)
  
  - Page faults per transaction
  
  - Page faults per query

- Web Server Workloads
  
  - Requests per second
  
  - Request latency distribution
  
  - Tail latency under high concurrency
  
  - Page faults per request
  
  - Page faults per MB served

- Machine Learning Workloads
  
  - Model load time
  
  - Page faults during model loading
  
  - Inference latency
  
  - Page faults per inference
  
  - TLB misses during inference loops
  
## 7. Comparative & Derived Metrics (Very Important for Analysis)
- These are computed, not directly measured.

- Percentage reduction/increase in page faults

- Percentage reduction/increase in TLB misses

- Performance speedup/slowdown

- Latency improvement or regression

- Fault density (faults per unit work)

- TLB reach (effective memory coverage)

These enable cross-workload comparisons.

## 8. Experimental Control Metrics (For Rigor)

These ensure results are valid.

- Page size configuration (4 KB vs 2 MB)

- THP state (enabled / disabled)

- Cache state (warm / cold)

- Number of repetitions

- Variance / standard deviation

## 9. What You Are Not Measuring (Explicitly State This)

This actually strengthens your project.

- No kernel source modifications

- No HPC workloads

- No energy/power metrics

- No NUMA migration effects (unless explicitly enabled)

# Workload Summary
## 1. Synthetic Memory Workloads (C/C++ Benchmark)

These are your baseline, controlled experiments.

Sequential memory access

Random memory access

Strided memory access

Large working set (>> cache size)

## 2. Database Workloads

Using SQLite or PostgreSQL + sysbench

OLTP Read-only workload (point queries)

OLTP Read-write workload (mixed operations)

Index-based lookups

Range queries / scans

## 3. Web Server Workloads

Using nginx + wrk

Static small file serving (e.g., HTML)

Static large file serving (e.g., images/videos)

Low concurrency requests

High concurrency requests

## 4. Machine Learning Workloads

Using PyTorch

Large model loading (cold start)

Repeated inference (steady state)

Large tensor allocation workloads

Batch size variation (small vs large batches)

## Final Workload Set (what you’ll actually run)

If you want the exact execution set, it becomes:

Synthetic: sequential, random, strided

Database: sysbench read-only + read-write

Web: small vs large files under load

ML: model load + inference loop

### Synthetic Memory Workloads — Detailed Explanation

- **Purpose:**
  - Establish a controlled baseline to study how page size affects page faults, TLB behavior, and performance  
  - Remove noise from complex applications and isolate memory access effects  

- **Core Idea:**
  - Allocate a large memory region (1–4 GB)  
  - Access it using different patterns  
  - Ensure working set exceeds cache to force main memory and paging activity  

- **Memory Allocation:**
  - Use large contiguous allocation (e.g., `malloc` or `posix_memalign`)  
  - Prefer page-aligned allocation for cleaner behavior  
  - Initialize memory before measurement to avoid counting allocation faults  

- **Access Patterns:**

  - **Sequential Access:**
    - Iterate linearly over the array  
    - High spatial locality  
    - Each page is fully utilized before moving to the next  
    - Low TLB pressure and minimal page faults after warm-up  
    - Large pages provide limited but consistent improvement  

  - **Random Access:**
    - Access elements using random indices  
    - No spatial or temporal locality  
    - Each access may touch a different page  
    - High TLB miss rate and frequent page table walks  
    - Large pages significantly reduce TLB misses and improve performance  

  - **Strided Access:**
    - Access elements at fixed intervals (e.g., every k-th element)  
    - Behavior depends on stride size  
    - Small stride maintains locality; large stride causes page jumps  
    - Moderate TLB pressure and page faults  
    - Mixed sensitivity to page size  

- **Experimental Setup:**
  - Run each access pattern independently  
  - Use memory sizes exceeding cache capacity  
  - Repeat experiments multiple times for stability  
  - Consider both cold-start and warm-cache conditions  

- **Page Size Configurations:**
  - Default pages (4 KB) with THP disabled  
  - Huge pages (2 MB) with THP enabled  
  - Optional use of `madvise()` for explicit control  

- **Metrics to Measure:**
  - Total page faults  
  - Minor and major page faults  
  - TLB misses (data and instruction)  
  - Execution time  
  - CPU cycles and instructions  

- **Expected Observations:**
  - Sequential access shows minimal difference across page sizes  
  - Random access benefits significantly from large pages  
  - Strided access shows intermediate behavior depending on stride  

- **Implementation Considerations:**
  - Prevent compiler optimizations using `volatile`
  - Ensure consistent environment across runs
  - Use `perf stat` for measurement

- **Role in the Project:**
  - Provides ground-truth understanding of memory behavior  
  - Helps explain results in database, web, and ML workloads  
  - Forms the foundation for causal analysis of page size effects  
  
### Database Workloads — Detailed Explanation

- **Purpose:**
  - Evaluate how page size impacts performance in **random-access, data-intensive systems**
  - Study interaction between **buffer pools, indexing, and virtual memory**
  - Observe how page faults and TLB behavior affect real-world transactional workloads  

- **Core Idea:**
  - Use a relational database system to generate realistic access patterns  
  - Simulate workloads involving point queries, updates, and scans  
  - Ensure dataset size exceeds cache to force memory pressure  

- **Database Systems:**
  - SQLite (lightweight, file-backed, easy setup)  
  - PostgreSQL (optional, more realistic with buffer pool and background processes)  

- **Benchmark Tool:**
  - `sysbench` (for PostgreSQL or MySQL-compatible setups)  
  - Custom SQL queries (for SQLite)  

- **Workloads:**

  - **Read-Only (Point Lookup):**
    - Queries targeting indexed rows (e.g., primary key lookups)  
    - Simulates high-frequency transactional systems  
    - Produces random memory access patterns  

  - **Read-Write (Mixed OLTP):**
    - Combination of SELECT, UPDATE, INSERT, DELETE  
    - Simulates real-world transactional load  
    - Involves both reads and memory modifications  

  - **Range Queries / Scans:**
    - Queries over contiguous key ranges  
    - Higher spatial locality compared to point lookups  
    - Useful for comparing sequential vs random behavior  

- **Dataset Configuration:**
  - Large tables (millions of rows)  
  - Total database size ≥ 1–2 GB  
  - Ensure dataset exceeds last-level cache  

- **Memory Behavior:**
  - Heavy use of buffer pool / page cache  
  - Frequent random access to pages  
  - Index traversal causes non-contiguous memory access  
  - Page faults occur when pages are not in memory  

- **Page Size Configurations:**
  - Default pages (4 KB) with THP disabled  
  - Huge pages (2 MB) with THP enabled  
  - Optional use of `madvise()` where applicable  

- **Metrics to Measure:**
  - Queries per second (QPS)  
  - Transaction latency (average, median)  
  - Tail latency (p95, p99)  
  - Total page faults  
  - Minor and major page faults  
  - Page faults per query  
  - TLB misses (data and instruction)  
  - CPU cycles and instructions  

- **Experimental Setup:**
  - Run each workload independently  
  - Use identical dataset and configuration across runs  
  - Repeat experiments multiple times for consistency  
  - Separate cold-cache and warm-cache runs  

- **Expected Observations:**
  - Random-access workloads generate high TLB pressure  
  - Large pages may reduce TLB misses but not always improve latency  
  - Buffer pool behavior may mask some page fault effects  
  - Tail latency may increase with large pages due to memory overhead  

- **Implementation Considerations:**
  - Ensure database is properly initialized before benchmarking  
  - Avoid background system noise  
  - Control cache state between runs  
  - Use `perf stat` alongside benchmark execution  

- **Role in the Project:**
  - Represents real-world memory-intensive applications  
  - Highlights differences between synthetic and complex workloads  
  - Demonstrates how page size impacts transactional systems differently from linear workloads  
  
### Web Server Workloads — Detailed Explanation

- **Purpose:**
  - Evaluate how page size affects performance in **I/O-heavy, cache-driven workloads**
  - Study interaction between **OS page cache, file serving, and memory access patterns**
  - Analyze how page faults impact latency and throughput under concurrent load  

- **Core Idea:**
  - Use a web server to serve static files from disk  
  - Generate client load with varying request sizes and concurrency levels  
  - Observe how memory mapping and page cache interact with page size  

- **Server & Tools:**
  - Web server: `nginx`
  - Load generator: `wrk`
  - Files served from local filesystem (SSD-backed)

- **Workloads:**

  - **Small File Serving:**
    - Files of size ~1–10 KB (HTML, JSON)
    - High request rate, low data per request
    - Simulates API responses or lightweight web pages
    - High request count → frequent metadata and cache access

  - **Large File Serving:**
    - Files of size ~10–100 MB (images, binaries)
    - Lower request rate, high data transfer per request
    - Simulates media/content delivery
    - Sequential memory access dominates

  - **Concurrency Variation:**
    - Low concurrency (e.g., 10 clients)
    - High concurrency (e.g., 100–200 clients)
    - Helps study contention and memory pressure under load

- **Dataset Configuration:**
  - Multiple files of varying sizes stored locally
  - Total dataset size large enough to stress page cache
  - Ensure some runs exceed available memory for cold-cache behavior

- **Memory Behavior:**
  - Heavy reliance on OS page cache
  - File data loaded into memory via demand paging
  - Repeated accesses may hit cached pages (warm cache)
  - Page faults occur during initial file access or cache eviction

- **Page Size Configurations:**
  - Default pages (4 KB) with THP disabled
  - Huge pages (2 MB) with THP enabled
  - Optional tuning via `madvise()` if applicable

- **Metrics to Measure:**
  - Requests per second (throughput)
  - Latency (average, median)
  - Tail latency (p95, p99)
  - Total page faults
  - Minor and major page faults
  - Page faults per request
  - TLB misses (data and instruction)
  - CPU cycles and instructions

- **Experimental Setup:**
  - Run server locally to avoid network variability
  - Use identical files and configuration across runs
  - Perform both cold-cache and warm-cache experiments
  - Repeat runs multiple times for consistency

- **Expected Observations:**
  - Small file workloads may show limited benefit from large pages
  - Large file workloads benefit more due to sequential access
  - Page cache reduces faults in warm runs
  - High concurrency increases memory pressure and fault rates

- **Implementation Considerations:**
  - Clear OS page cache between cold runs (`echo 3 > /proc/sys/vm/drop_caches`)
  - Ensure no other services interfere with measurements
  - Pin CPU usage if needed for consistency
  - Use `perf stat` alongside `wrk`

- **Role in the Project:**
  - Represents real-world server workloads with mixed memory patterns
  - Highlights interaction between page size and OS caching mechanisms
  - Complements database and synthetic benchmarks by adding I/O-driven behavior
  
### Machine Learning Workloads — Detailed Explanation

- **Purpose:**
  - Evaluate how page size impacts **memory-intensive, contiguous allocation workloads**
  - Study behavior of **large tensor allocations, model loading, and repeated computation**
  - Analyze how page faults and TLB efficiency affect ML performance  

- **Core Idea:**
  - Use a deep learning framework to allocate and process large tensors  
  - Simulate real-world ML tasks such as model loading and inference  
  - Focus on memory footprint and access patterns rather than model accuracy  

- **Framework & Tools:**
  - PyTorch (CPU-based execution)  
  - Python scripts for workload execution  
  - `perf` and `vmstat` for measurement  

- **Workloads:**

  - **Model Loading (Cold Start):**
    - Load a large pre-trained model from disk (e.g., ResNet, Transformer)  
    - Triggers significant memory allocation and page faults  
    - Represents startup overhead in ML systems  

  - **Inference Loop (Steady State):**
    - Run repeated forward passes on input tensors  
    - Simulates production inference workloads  
    - Access patterns are relatively structured and reused  

  - **Large Tensor Allocation:**
    - Allocate large tensors (e.g., 10k × 10k or higher dimensions)  
    - Stress-test memory allocation and paging behavior  
    - Minimal computation, primarily memory-focused  

  - **Batch Size Variation:**
    - Run inference with different batch sizes (e.g., 1, 32, 128)  
    - Larger batches increase memory footprint and locality  
    - Helps analyze scaling behavior  

- **Dataset / Model Configuration:**
  - Use pre-trained models or synthetic large tensors  
  - Ensure total memory usage is large (≥ 1–2 GB)  
  - Avoid GPU usage to keep focus on CPU memory behavior  

- **Memory Behavior:**
  - Large contiguous memory allocations  
  - High spatial locality during tensor operations  
  - Repeated reuse of memory in inference loops  
  - Page faults primarily during allocation and model loading  

- **Page Size Configurations:**
  - Default pages (4 KB) with THP disabled  
  - Huge pages (2 MB) with THP enabled  
  - Optional use of `madvise()` for fine-grained control  

- **Metrics to Measure:**
  - Model load time  
  - Inference latency (per iteration)  
  - Total page faults  
  - Minor and major page faults  
  - Page faults during model loading  
  - Page faults per inference iteration  
  - TLB misses (data and instruction)  
  - CPU cycles and instructions  

- **Experimental Setup:**
  - Run workloads on CPU to avoid GPU interference  
  - Keep model and input data constant across runs  
  - Repeat experiments multiple times  
  - Separate cold-start (first run) and steady-state measurements  

- **Expected Observations:**
  - Large pages reduce TLB misses due to contiguous memory usage  
  - Model loading benefits significantly from large pages  
  - Inference shows moderate improvement due to memory reuse  
  - Larger batch sizes amplify benefits of huge pages  

- **Implementation Considerations:**
  - Disable gradient computation for inference (`torch.no_grad()`)  
  - Ensure consistent input sizes and model configuration  
  - Avoid background system load  
  - Use `perf stat` around Python execution  

- **Role in the Project:**
  - Represents modern memory-intensive workloads  
  - Highlights benefits of large pages in contiguous memory scenarios  
  - Complements database and web workloads by showing contrasting behavior  
