// Experimental Caravan external-weight catalog. Included only by llama.cpp.
// It is not a sparse/partial GGUF: CVGGUF1 wraps metadata, and all weights
// must exist as explicit local pieces or verified peer cache hits.
#include "gguf.h"
#include <fstream>
#include <sstream>
#include <map>
#include <stdexcept>

struct caravan_piece {
    uint64_t hash;
    size_t size;
    int owner;
};
struct caravan_catalog {
    std::string root;
    std::map<std::string, caravan_piece> pieces;
};

static uint64_t caravan_fnv(const uint8_t * p, size_t n) {
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    for (size_t i=0; i<n; ++i) h = (h ^ p[i]) * UINT64_C(0x100000001b3);
    return h;
}

static void caravan_set_piece(ggml_tensor * tensor, void * ud) {
    auto & catalog = *(caravan_catalog *)ud;
    auto it = catalog.pieces.find(tensor->name);
    if (it == catalog.pieces.end()) {
        throw std::runtime_error(std::string("Caravan: no piece for tensor ") + tensor->name);
    }
    const auto & piece = it->second;
    if (piece.size != ggml_nbytes(tensor)) {
        throw std::runtime_error(std::string("Caravan: tensor size mismatch: ") + tensor->name);
    }
    auto buft = ggml_backend_buffer_get_type(tensor->buffer);
    auto dev = ggml_backend_buft_get_device(buft);
    auto reg = dev ? ggml_backend_dev_backend_reg(dev) : nullptr;
    using load_fn = bool (*)(ggml_tensor *, uint64_t);
    auto load = reg ? (load_fn)ggml_backend_reg_get_proc_address(reg, "caravan_rpc_load_hash") : nullptr;
    if (load) {
        if (piece.owner == 0 || !load(tensor,piece.hash)) {
            throw std::runtime_error(std::string("Caravan: missing/misplaced peer piece (no weight-transfer fallback): ") + tensor->name);
        }
        LLAMA_LOG_INFO("caravan shard: remote-local %s %zu bytes\n",tensor->name,piece.size);
        return;
    }
    if (piece.owner != 0) {
        throw std::runtime_error(std::string("Caravan: peer tensor placed locally; split plan differs: ") + tensor->name);
    }
    char key[17]; snprintf(key,sizeof(key),"%016llx",(unsigned long long)piece.hash);
    std::ifstream file(catalog.root + "/rpc/" + key, std::ios::binary | std::ios::ate);
    if (!file || file.tellg() != (std::streamoff)piece.size) {
        throw std::runtime_error(std::string("Caravan: local piece missing/wrong size: ") + tensor->name);
    }
    file.seekg(0);
    std::vector<uint8_t> data(piece.size);
    if (!file.read((char *)data.data(), data.size()) || caravan_fnv(data.data(),data.size()) != piece.hash) {
        throw std::runtime_error(std::string("Caravan: local piece corrupt: ") + tensor->name);
    }
    ggml_backend_tensor_set(tensor,data.data(),0,data.size());
    LLAMA_LOG_INFO("caravan shard: local %s %zu bytes\n",tensor->name,piece.size);
}

static llama_model * caravan_load_catalog(const char * path, llama_model_params params) {
    // Only this new extension opts in. Ordinary GGUF behavior is unchanged.
    caravan_catalog catalog;
    const std::string filename(path);
    const auto slash = filename.find_last_of("/\\");
    catalog.root = slash == std::string::npos ? "." : filename.substr(0,slash);
    std::ifstream table(catalog.root + "/weights.tsv");
    std::string line;
    while (std::getline(table,line)) {
        std::istringstream row(line);
        std::string name,key;
        size_t size; int owner;
        if (!(row >> name >> key >> size >> owner) || key.size()!=16 || size==0 || owner<0) {
            throw std::runtime_error("Caravan: invalid weights table");
        }
        if (!catalog.pieces.emplace(name,caravan_piece{std::stoull(key,nullptr,16),size,owner}).second) {
            throw std::runtime_error("Caravan: duplicate tensor in weights table");
        }
    }
    if (catalog.pieces.empty()) throw std::runtime_error("Caravan: empty weights table");
    FILE * file = fopen(path,"rb");
    if (!file) throw std::runtime_error("Caravan: catalog not found");
    char magic[8];
    if (fread(magic,1,8,file)!=8 || memcmp(magic,"CVGGUF1\n",8)) {
        fclose(file); throw std::runtime_error("Caravan: invalid catalog magic");
    }
    gguf_init_params gp = { true, nullptr };
    auto meta = gguf_init_from_file_ptr(file,gp);
    fclose(file);
    if (!meta) throw std::runtime_error("Caravan: invalid catalog metadata");
    // init_from_user is synchronous; catalog lifetime covers every callback.
    auto model = llama_model_init_from_user(meta,caravan_set_piece,&catalog,params);
    // metadata is referenced by model vocabulary during initialization only.
    gguf_free(meta);
    return model;
}
