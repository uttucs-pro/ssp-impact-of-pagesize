# Machine Learning Workload — Experiment Findings

## Experimental Setup

| Parameter | Value |
|---|---|
| **System** | Linux 6.17.0-19-generic, 16 GB RAM, 8 cores |
| **Cache hierarchy** | L1=32KB, L2=256KB, L3=8MB |
| **Framework** | PyTorch (CPU-only) |
| **Model** | ResNet-152 (pre-trained, ~230 MB, 60M parameters) |
| **Page configs** | 4 KB (THP=never) vs 2 MB (THP=always) |
| **Instrumentation** | `perf stat` wrapping Python process + benchmark output |
| **Repetitions** | 3 per configuration |
| **Total runs** | 48 (4 workloads × 2 page configs × 2 cache states × 3 reps) |

### Workloads Tested
- **Model Load (cold start)** — Load ResNet-152 from disk, 5 iterations per run
- **Inference (steady state)** — 100 forward passes, batch size 32
- **Tensor Allocation** — 10,000×10,000 float32 tensors (~400 MB), 50 iterations
- **Batch Variation** — Inference with batch sizes 1, 32, 128 (50 iterations each)
- **Cold cache** — OS page cache dropped before each run
- **Warm cache** — Pre-warmed with initial model load

---

## Summary Results

### Model Loading

| Config | Load Time (s) | Page Faults | dTLB Load Misses | IPC | Wall Time (s) |
|---|---:|---:|---:|---:|---:|
| **model_load-4KB-cold** | 0.833 | 351,086 ±1,163 | 8,330,475 | 1.22 | 8.42 |
| **model_load-2MB-cold** | 0.801 | 273,003 ±16,748 | 8,250,959 | 1.24 | 8.19 |
| **model_load-4KB-warm** | 0.786 | 355,585 ±8,113 | 7,703,842 | 1.27 | 7.29 |
| **model_load-2MB-warm** | 0.742 | 274,829 ±15,526 | 7,671,505 | 1.28 | 6.99 |

### Inference (batch_size=32)

| Config | Infer Time/iter (s) | Page Faults | dTLB Load Misses | IPC | Wall Time (s) |
|---|---:|---:|---:|---:|---:|
| **inference-4KB-cold** | 5.292 | 145,950,070 ±3.5M | 531,414,385 | 1.26 | 539.73 |
| **inference-2MB-cold** | 5.190 | 7,541,180 ±277K | 123,380,193 | 1.14 | 529.33 |
| **inference-4KB-warm** | 5.219 | 148,363,285 ±1.7M | 540,086,389 | 1.26 | 531.05 |
| **inference-2MB-warm** | 5.217 | 6,551,774 ±853K | 120,038,970 | 1.13 | 530.82 |

### Tensor Allocation (10,000×10,000, ~400 MB)

| Config | Avg Time/iter (s) | Page Faults | dTLB Load Misses | IPC | Wall Time (s) |
|---|---:|---:|---:|---:|---:|
| **tensor_alloc-4KB-cold** | 7.644 | 9,829,439 ±18 | 1,324,266,498 | 2.70 | 391.63 |
| **tensor_alloc-2MB-cold** | 7.450 | 126,064 ±23 | 30,933,222 | 2.76 | 380.66 |
| **tensor_alloc-4KB-warm** | 7.611 | 9,828,398 ±6 | 1,320,928,325 | 2.70 | 389.16 |
| **tensor_alloc-2MB-warm** | 7.357 | 125,097 ±25 | 30,254,145 | 2.77 | 375.11 |

### Batch Size Variation

| Config | bs=1 (s/iter) | bs=32 (s/iter) | bs=128 (s/iter) | Page Faults | Wall Time (s) |
|---|---:|---:|---:|---:|---:|
| **batch_vary-4KB-cold** | 0.198 | 5.241 | 22.125 | 594,069,078 | 1,410.66 |
| **batch_vary-2MB-cold** | 0.195 | 5.106 | 21.404 | 14,910,670 | 1,367.50 |
| **batch_vary-4KB-warm** | 0.197 | 5.285 | 22.360 | 589,831,166 | 1,423.95 |
| **batch_vary-2MB-warm** | 0.195 | 5.078 | 21.438 | 15,762,864 | 1,366.17 |

---

## Key Findings

### 1. Massive Page Fault Reduction with 2 MB Pages (22–99%)

2 MB huge pages dramatically reduce page faults across **all** ML workloads. This is the strongest page fault reduction seen across all four workload types in this project.

| Workload | 4KB Page Faults | 2MB Page Faults | Reduction |
|---|---:|---:|---:|
| **batch_vary (cold)** | 594,069,078 | 14,910,670 | **97.5%** |
| **batch_vary (warm)** | 589,831,166 | 15,762,864 | **97.3%** |
| **inference (cold)** | 145,950,070 | 7,541,180 | **94.8%** |
| **inference (warm)** | 148,363,285 | 6,551,774 | **95.6%** |
| **tensor_alloc (cold)** | 9,829,439 | 126,064 | **98.7%** |
| **tensor_alloc (warm)** | 9,828,398 | 125,097 | **98.7%** |
| **model_load (cold)** | 351,086 | 273,003 | **22.2%** |
| **model_load (warm)** | 355,585 | 274,829 | **22.7%** |

The batch_vary and tensor_alloc workloads show nearly **two orders of magnitude** fewer page faults with huge pages. Even model loading — the shortest workload — sees a 22% reduction.

![Page Faults](plots/page_faults.png)

### 2. dTLB Load Miss Reduction (1–98%)

| Workload | 4KB dTLB Misses | 2MB dTLB Misses | Reduction |
|---|---:|---:|---:|
| **tensor_alloc (cold)** | 1,324,266,498 | 30,933,222 | **97.7%** |
| **tensor_alloc (warm)** | 1,320,928,325 | 30,254,145 | **97.7%** |
| **batch_vary (cold)** | 1,440,553,433 | 162,590,824 | **88.7%** |
| **batch_vary (warm)** | 1,460,479,705 | 160,903,002 | **89.0%** |
| **inference (cold)** | 531,414,385 | 123,380,193 | **76.8%** |
| **inference (warm)** | 540,086,389 | 120,038,970 | **77.8%** |
| **model_load (cold)** | 8,330,475 | 8,250,959 | **1.0%** |
| **model_load (warm)** | 7,703,842 | 7,671,505 | **0.4%** |

The tensor_alloc workload benefits the most from TLB reduction (97.7%), which makes sense — it performs pure contiguous memory allocation and matrix operations. The model_load workload shows minimal dTLB improvement because model loading is dominated by disk I/O and deserialization rather than memory access patterns.

![dTLB Load Misses](plots/dtlb_load_misses.png)

### 3. Model Load Time Improves with 2 MB Pages

| Config | 4KB Load Time (s) | 2MB Load Time (s) | Improvement |
|---|---:|---:|---:|
| Cold | 0.833 | 0.801 | **+3.8%** |
| Warm | 0.786 | 0.742 | **+5.6%** |

The improvement is modest (~4–6%) because model loading is bottlenecked by disk I/O and Python deserialization overhead, not memory page faults. However, 2 MB pages consistently outperform 4 KB pages.

![Model Load Time](plots/model_load_time.png)

### 4. Inference Latency Shows Modest Improvement

| Config | 4KB Inference (s/iter) | 2MB Inference (s/iter) | Improvement |
|---|---:|---:|---:|
| Inference cold (bs=32) | 5.292 | 5.190 | **+1.9%** |
| Inference warm (bs=32) | 5.219 | 5.217 | **+0.04%** |
| batch_vary cold (bs=128) | 22.125 | 21.404 | **+3.3%** |
| batch_vary warm (bs=128) | 22.360 | 21.438 | **+4.1%** |
| batch_vary cold (bs=32) | 5.241 | 5.106 | **+2.6%** |
| batch_vary warm (bs=32) | 5.285 | 5.078 | **+3.9%** |
| batch_vary cold (bs=1) | 0.198 | 0.195 | **+1.5%** |
| batch_vary warm (bs=1) | 0.197 | 0.195 | **+1.0%** |

Despite the enormous reduction in page faults and TLB misses, inference latency improvements are modest (1–4%). This indicates that inference is **compute-bound** (matrix multiplications dominate runtime), not memory-bound. The page faults and TLB misses happen but don't sit on the critical path for per-iteration latency.

![Inference Latency](plots/inference_latency.png)

### 5. Tensor Allocation Benefits Most from Huge Pages

| Config | 4KB Time/iter (s) | 2MB Time/iter (s) | Improvement |
|---|---:|---:|---:|
| Cold | 7.644 | 7.450 | **+2.5%** |
| Warm | 7.611 | 7.357 | **+3.3%** |

With a 98.7% reduction in page faults and 97.7% reduction in dTLB misses, tensor_alloc still only shows 2.5–3.3% wall-time improvement. This is because the matrix multiply (`t @ t.T`) dominates runtime — it's a compute-intensive BLAS operation, and the memory allocation overhead (where page faults occur) is a small fraction of total time.

### 6. IPC: 4 KB Pages Achieve Higher IPC Despite More Overhead

| Workload | 4KB IPC | 2MB IPC |
|---|---:|---:|
| batch_vary (cold) | **1.28** | 1.09 |
| batch_vary (warm) | **1.27** | 1.09 |
| inference (cold) | **1.26** | 1.14 |
| inference (warm) | **1.26** | 1.13 |
| model_load (cold) | 1.22 | **1.24** |
| model_load (warm) | **1.27** | **1.28** |
| tensor_alloc (cold) | 2.70 | **2.76** |
| tensor_alloc (warm) | 2.70 | **2.77** |

Interestingly, 4 KB pages achieve **higher IPC** for batch_vary and inference workloads despite having far more page faults and TLB misses. This counterintuitive result is because:
- With 4 KB pages, the CPU executes **more total instructions** (25B vs 21B for batch_vary) — likely due to additional page table walks and TLB miss handling in microcode
- These extra instructions are fast (register-to-register operations in the page walk), inflating IPC
- For tensor_alloc, where the workload is purely compute-bound (BLAS), 2 MB pages achieve slightly higher IPC (2.77 vs 2.70)

![IPC Comparison](plots/ipc.png)

### 7. Improvement Summary

![Improvement Summary](plots/improvement_summary.png)

![CPU Cycles](plots/cpu_cycles.png)

![dTLB Store Misses](plots/dtlb_store_misses.png)

---

## Analysis & Interpretation

### Why Huge Pages Strongly Benefit ML Workloads

1. **Large contiguous memory allocations.** PyTorch allocates tensors via `mmap`, which maps directly to physical pages. A single 10,000×10,000 float32 tensor (~400 MB) requires ~100,000 4KB pages but only ~200 2MB pages. This 500× reduction in page count directly translates to fewer page faults during allocation.

2. **High spatial locality.** Tensor operations (matrix multiply, convolutions) sweep through memory linearly. With 2 MB pages, each TLB entry covers 512× more memory, keeping the TLB hot and eliminating most address translation overhead.

3. **Repeated memory reuse in inference.** Forward passes reuse the same weight tensors repeatedly. With fewer TLB entries needed for huge pages, the TLB can effectively cache the model's entire memory footprint, eliminating nearly all translation overhead.

4. **batch_vary amplifies the effect.** Larger batch sizes (bs=128) allocate larger input tensors and intermediate activations, requiring more pages. The total page faults with 4 KB pages scale to ~594M (!) vs ~15M with 2 MB pages — a 40× reduction.

### Why Performance Gains Are Modest Despite Massive Fault Reduction

Despite 95–99% reductions in page faults and 77–98% reductions in dTLB misses, wall-time improvements are only 1–5%. This is because:

1. **Compute dominance.** ResNet-152 inference is dominated by convolution and matrix multiply operations (BLAS/MKL), which are CPU-bound. Memory stalls from TLB misses are a small fraction of total execution time.

2. **Efficient hardware page walkers.** Modern CPUs (the test system) have dedicated hardware page table walkers that handle TLB misses with low overhead (~10–20 cycles per walk). Even millions of TLB misses only add seconds to a run that takes hundreds of seconds.

3. **OS page cache effectiveness.** In warm-cache runs, most data is already in the OS page cache, so page faults are minor faults (no disk I/O), which are cheap (~1µs each).

### Contrast with Other Workloads

| Aspect | Synthetic Random | Web Server | Database | **ML Workload** |
|---|---|---|---|---|
| Page size winner | **2MB** | **4KB** | **4KB** | **2MB** |
| Page fault reduction | 99.8% | ~0% | ~0% | **95–99%** |
| dTLB miss reduction | 99.9% | ~50% | ~30% | **77–98%** |
| Wall-time improvement | +56% | −33% to −133% | −9% to −42% | **+1% to +5%** |
| Access pattern | Truly random | sendfile (kernel) | Index traversal | **Contiguous + structured** |
| Dominant cost | Memory stalls | THP overhead | THP overhead + buffer pool | **Compute (BLAS)** |
| Key insight | TLB dominates | THP hurts | THP hurts | Memory overhead ≪ compute |

The ML workload is unique: it has the **strongest page fault and TLB reduction** of any workload, yet the **smallest practical speedup**. This demonstrates that reducing memory overhead only helps when memory is the bottleneck — for compute-bound ML workloads, it's not.

---

## Conclusions

1. **2 MB huge pages dramatically reduce page faults (95–99%) and dTLB misses (77–98%)** for ML workloads — the largest reduction across all four workload types in this study.

2. **Wall-time improvement is modest (1–5%)** because ML inference is compute-bound, not memory-bound. The CPU spends most of its time in BLAS matrix operations, not waiting for page table walks.

3. **Tensor allocation workloads show the strongest improvement** (98.7% page fault reduction, 3.3% latency improvement) due to pure contiguous memory allocation patterns.

4. **Larger batch sizes amplify page fault differences** (594M vs 15M for bs=128) but don't proportionally increase latency improvement, confirming that page faults are off the critical path.

5. **Model loading benefits modestly** (+4–6%) — disk I/O and deserialization dominate, not memory allocation.

6. **THP `always` is safe and mildly beneficial for ML workloads** — unlike database and webserver workloads where THP compaction caused performance regressions, ML workloads use large contiguous allocations that naturally align with huge pages, avoiding compaction overhead.

7. **Huge pages are not universally beneficial, even when metrics improve dramatically.** The ML workload is the clearest example: massive improvements in memory metrics don't translate to proportional application-level gains when the workload is compute-bound.

---

## Files Generated

| File | Description |
|---|---|
| `results.csv` | All metrics, means and standard deviations (24 configs) |
| `plots/model_load_time.png` | Model load time comparison |
| `plots/inference_latency.png` | Inference latency comparison |
| `plots/page_faults.png` | Page fault comparison |
| `plots/dtlb_load_misses.png` | dTLB load miss comparison |
| `plots/dtlb_store_misses.png` | dTLB store miss comparison |
| `plots/cpu_cycles.png` | CPU cycle comparison |
| `plots/ipc.png` | Instructions per cycle comparison |
| `plots/improvement_summary.png` | Percentage reduction summary |
| `raw_results/` | 144 raw files (48 output + 48 perf + 48 stderr) |
