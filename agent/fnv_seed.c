/* Caravan GGUF stage 2: seed llama.cpp's rpc-server tensor cache from a local GGUF.
 * stdin: lines "<offset> <size>"; argv: <gguf> <cache_dir>.
 * For each tensor: FNV-1a 64 of its bytes (same as ggml-rpc fnv_hash), then write
 * <cache_dir>/<%016llx> unless a file of that size already exists.
 * stdout: "<hash> new|have <size>". Build: cc -O2 -o caravan-fnv-seed fnv_seed.c */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s gguf cache_dir\n", argv[0]); return 2; }
    FILE *g = fopen(argv[1], "rb");
    if (!g) { perror(argv[1]); return 2; }
    size_t cap = 1 << 20; unsigned char *buf = malloc(cap);
    unsigned long long off, size;
    while (scanf("%llu %llu", &off, &size) == 2) {
        if (size > cap) { cap = size; buf = realloc(buf, cap); if (!buf) return 3; }
        if (fseeko(g, (off_t)off, SEEK_SET) || fread(buf, 1, size, g) != size) { fprintf(stderr, "read fail at %llu\n", off); return 4; }
        uint64_t h = 0xcbf29ce484222325ULL;
        for (unsigned long long i = 0; i < size; i++) { h ^= buf[i]; h *= 0x100000001b3ULL; }
        char path[4096]; snprintf(path, sizeof path, "%s/%016llx", argv[2], (unsigned long long)h);
        struct stat st;
        if (stat(path, &st) == 0 && (unsigned long long)st.st_size == size) { printf("%016llx have %llu\n", (unsigned long long)h, size); fflush(stdout); continue; }
        char tmp[4200]; snprintf(tmp, sizeof tmp, "%s.caravan-tmp", path);
        FILE *o = fopen(tmp, "wb");
        if (!o || fwrite(buf, 1, size, o) != size || fclose(o)) { perror(tmp); return 5; }
        if (rename(tmp, path)) { perror(path); return 5; }
        printf("%016llx new %llu\n", (unsigned long long)h, size); fflush(stdout);
    }
    return 0;
}
