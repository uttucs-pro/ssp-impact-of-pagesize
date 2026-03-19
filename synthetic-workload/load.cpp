#define _GNU_SOURCE
#include <bits/stdc++.h>
#include <sys/mman.h>
#include <unistd.h>
#include <time.h>
using namespace std;

static inline uint64_t now_ns() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}

void sequential(volatile uint8_t* p, size_t size) {
    for (size_t i = 0; i < size; i++) p[i]++;
}

void random_access(volatile uint8_t* p, size_t size) {
    srand(42); // Fixed seed for reproducibility
    for (size_t i = 0; i < size; i++) {
        size_t idx = rand() % size;
        p[idx]++;
    }
}

void strided(volatile uint8_t* p, size_t size, size_t stride) {
    for (size_t i = 0; i < size; i += stride) p[i]++;
}

void usage(const char* prog) {
    fprintf(stderr, "Usage: %s <size_mb> <iterations> <seq|rand|stride> [stride_bytes]\n", prog);
    fprintf(stderr, "  Environment: USE_HUGEPAGES=1 to enable 2MB huge pages via madvise()\n");
    exit(1);
}

int main(int argc, char* argv[]) {
    if (argc < 4) usage(argv[0]);

    size_t size = atol(argv[1]) * 1024ULL * 1024ULL;
    int iterations = atoi(argv[2]);
    string pattern = argv[3];
    size_t stride = 1;

    if (pattern == "stride") {
        if (argc < 5) {
            fprintf(stderr, "Error: stride pattern requires stride_bytes argument\n");
            usage(argv[0]);
        }
        stride = atol(argv[4]);
    }

    // Check if hugepages requested
    const char* hp_env = getenv("USE_HUGEPAGES");
    bool use_hugepages = (hp_env && strcmp(hp_env, "1") == 0);

    const char* page_config = use_hugepages ? "2MB" : "4KB";

    fprintf(stderr, "Config: size=%zuMB iterations=%d pattern=%s stride=%zu pages=%s\n",
            size / (1024*1024), iterations, pattern.c_str(), stride, page_config);

    // Allocate memory via mmap
    uint8_t* p = (uint8_t*) mmap(NULL, size, PROT_READ | PROT_WRITE,
                                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);

    if (p == MAP_FAILED) {
        perror("mmap failed");
        return 1;
    }

    // Apply hugepage advice
    if (use_hugepages) {
        if (madvise(p, size, MADV_HUGEPAGE) != 0) {
            perror("madvise MADV_HUGEPAGE failed");
        }
    } else {
        if (madvise(p, size, MADV_NOHUGEPAGE) != 0) {
            perror("madvise MADV_NOHUGEPAGE failed");
        }
    }

    // Prefault all pages
    for (size_t i = 0; i < size; i += 4096) p[i] = 1;

    uint64_t start = now_ns();

    for (int i = 0; i < iterations; i++) {
        if (pattern == "seq") sequential((volatile uint8_t*)p, size);
        else if (pattern == "rand") random_access((volatile uint8_t*)p, size);
        else if (pattern == "stride") strided((volatile uint8_t*)p, size, stride);
        else { fprintf(stderr, "Unknown pattern: %s\n", pattern.c_str()); return 1; }
    }

    uint64_t end = now_ns();

    double sec = (end - start) / 1e9;

    // Structured output for parsing
    printf("RESULT: pattern=%s page_config=%s size_mb=%zu iterations=%d stride=%zu time_sec=%.6f\n",
           pattern.c_str(), page_config, size / (1024*1024), iterations, stride, sec);

    fprintf(stderr, "Time: %.6f seconds\n", sec);

    munmap(p, size);
    return 0;
}
