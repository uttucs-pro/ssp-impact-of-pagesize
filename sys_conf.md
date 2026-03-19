## Experimental Setup

### System Configuration

- **Machine:** Ubuntu Desktop  
- **OS:** Ubuntu 24.04.4 LTS  
- **Kernel:** Linux 6.17.0-19-generic (x86_64)  

---

### CPU Details

- **Processor:** Intel Core i5-10300H @ 2.50 GHz  
- **Cores / Threads:** 4 cores / 8 threads  
- **CPU Frequency:** 0.8 GHz – 4.5 GHz  
- **Architecture:** x86_64 (64-bit)  

---

### Cache Hierarchy

- **L1 Cache:** 128 KB (per core, instruction + data)  
- **L2 Cache:** 1 MB (per core)  
- **L3 Cache:** 8 MB (shared)  

---

### Memory Configuration

- **Total RAM:** 16 GB  
- **Available RAM:** ~9.7 GB  
- **Swap:** 4 GB (unused during experiments)  

---

### Virtual Memory Configuration

- **Default Page Size:** 4 KB  
- **Huge Page Size:** 2 MB  
- **Transparent Huge Pages (THP):** `madvise` mode  

---

### NUMA Configuration

- **NUMA Nodes:** 1 (uniform memory access)  

---

### Storage

- **Primary Storage:** NVMe SSD (≈ 238 GB)  
- **Filesystem:** ext4  
- **Available Space:** ~206 GB free  

---

### Notes on Experimental Environment

- All experiments were conducted on a fixed hardware and software configuration  
- No significant background workloads were present during measurements  
- Swap was not utilized, ensuring memory-resident workloads  
- THP configuration was explicitly controlled during experiments  
