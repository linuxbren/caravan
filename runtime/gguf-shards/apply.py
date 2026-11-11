#!/usr/bin/env python3
"""Apply the experimental catalog loader to the pinned, LOCAL llama.cpp tree.

Never patches the user's production checkout: creates a new git worktree from
an existing local tree. Builds go in that worktree, leaving running binaries
and all services untouched. No network clone, no model manipulation.
"""
from pathlib import Path
import argparse
import shutil
import subprocess

PIN = '76a67730ffc7d650dffa4db04d96be84a59e7ef3'


def replace_once(text, old, new):
    if text.count(old) != 1: raise ValueError('pinned source anchor missing or ambiguous: '+old[:100])
    return text.replace(old,new,1)


def patch(root):
    root = Path(root)
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=PIN:
        raise ValueError('runtime requires the exact tested llama.cpp revision '+PIN)
    p = root/'src/llama.cpp'; text = p.read_text()
    # Header must come after llama/ggml declarations and before model loading.
    text = replace_once(text, 'struct llama_model * llama_model_load_from_file(\n',
                        '#include "caravan-catalog.h"\n\nstruct llama_model * llama_model_load_from_file(\n')
    anchor = '''    std::vector<std::string> splits = {};
    return llama_model_load_from_file_impl(nullptr, nullptr, nullptr, path_model, splits, /*file*/ nullptr, params);'''
    text = replace_once(text,anchor,'''    const std::string caravan_path(path_model);
    if (caravan_path.size() >= 5 && caravan_path.substr(caravan_path.size()-5) == ".cvgg") {
        try { return caravan_load_catalog(path_model,params); }
        catch (const std::exception & e) {
            LLAMA_LOG_ERROR("Caravan catalog load failed: %s\\n",e.what());
            return nullptr;
        }
    }
'''+anchor)
    p.write_text(text)
    shutil.copyfile(Path(__file__).with_name('caravan-catalog.h'),root/'src/caravan-catalog.h')
    p = root/'src/llama-model-loader.cpp'; text=p.read_text()
    anchor='''        ggml_type type = GGML_TYPE_F32;
        const int64_t tid = gguf_find_tensor(metadata, tn.str().c_str());'''
    text=replace_once(text,anchor,'''        // A catalog enumerates real tensors, unlike a synthetic user model.
        if (set_tensor_data != nullptr && gguf_get_n_tensors(metadata) > 0 &&
            gguf_find_tensor(metadata, tn.str().c_str()) < 0) {
            if (flags & TENSOR_NOT_REQUIRED) return nullptr;
            throw std::runtime_error("Caravan: required tensor absent from catalog: " + tn.str());
        }
'''+anchor)
    p.write_text(text)
    p=root/'ggml/src/ggml-rpc/ggml-rpc.cpp'; text=p.read_text()
    anchor='static void * ggml_backend_rpc_get_proc_address(ggml_backend_reg_t reg, const char * name) {'
    helper='''// Strict local-only weight load: reuses the existing hash RPC for ALL sizes.
// Never accepts source bytes and never falls back to SET_TENSOR on a cache miss.
static bool caravan_rpc_load_hash(ggml_tensor * tensor, uint64_t hash) {
    if (!tensor->buffer || tensor->buffer->iface.set_tensor != ggml_backend_rpc_buffer_set_tensor) return false;
    auto * ctx = (ggml_backend_rpc_buffer_context *)tensor->buffer->context;
    auto request = std::make_shared<rpc_msg_set_tensor_hash_req>();
    request->tensor = serialize_tensor(tensor);
    request->offset = 0;
    request->hash = hash;
    rpc_msg_set_tensor_hash_rsp response;
    ctx->dispatcher->send(RPC_CMD_SET_TENSOR_HASH,request,sizeof(*request),&response,sizeof(response));
    return response.result != 0;
}

'''
    text=replace_once(text,anchor,helper+anchor+'''
    if (std::strcmp(name,"caravan_rpc_load_hash")==0) return (void *)caravan_rpc_load_hash;''')
    anchor='''    size_t size = cached_file.size();'''
    # Occurs only in set_tensor_hash in the pinned source.
    text=replace_once(text,anchor,anchor+'''
    if (getenv("CARAVAN_STRICT_SHARDS") &&
        (request.offset != 0 || size != ggml_nbytes(tensor) || fnv_hash(cached_file.data(),size) != request.hash)) {
        LOG_ERROR("Caravan: corrupt/mis-sized local tensor piece; refusing cache hit\\n");
        response.result = 0;
        return true;
    }''')
    p.write_text(text)
    (root/'caravan-shards-version').write_text('catalog-v1/'+PIN+'\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source'); ap.add_argument('worktree')
    a=ap.parse_args()
    src=Path(a.source).expanduser(); dst=Path(a.worktree).expanduser()
    if dst.exists(): raise ValueError('worktree path must be new')
    subprocess.run(['git','-C',str(src),'worktree','add','--detach',str(dst),PIN],check=True)
    patch(dst)
    print('Patched isolated runtime:',dst)
    print('Build: cmake -S',dst,'-B',dst/'build','-DGGML_RPC=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF')

if __name__=='__main__': main()
