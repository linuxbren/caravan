/* Read-only FNV-1a of GGUF byte ranges, matching llama.cpp's native RPC cache.
 * stdin: offset size per tensor. stdout: 16 lowercase hex digits per tensor.
 * No output model files; bounded memory and strict EOF/range checks. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/stat.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 2;
    struct stat st;
    if (fstat(fileno(f), &st)) return 2;
    unsigned char buf[1 << 20];
    unsigned long long off, size;
    while (scanf("%llu %llu", &off, &size) == 2) {
        if (!size || off > (uint64_t)st.st_size || size > (uint64_t)st.st_size-off ||
            fseeko(f, (off_t)off, SEEK_SET)) return 3;
        uint64_t h = UINT64_C(0xcbf29ce484222325), left = size;
        while (left) {
            size_t n = left > sizeof(buf) ? sizeof(buf) : (size_t)left;
            if (fread(buf, 1, n, f) != n) return 4;
            for (size_t i=0; i<n; ++i) h = (h ^ buf[i]) * UINT64_C(0x100000001b3);
            left -= n;
        }
        printf("%016llx\n", (unsigned long long)h);
    }
    fclose(f);
    return feof(stdin) ? 0 : 5;
}
