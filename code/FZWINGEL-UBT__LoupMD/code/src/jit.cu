// Run-time kernel compiler: see jit.hpp and JIT_DESIGN.md.
#include "jit.hpp"

#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>

#include <nvrtc.h>

namespace loup {
namespace jit {

namespace {

// Embedded kernel headers (Makefile: $(OBJDIR)/jit_src/<name>.inc, each one raw string literal of the header).
const char kKernelsCommon[] =
#include "jit_src/kernels_common.cuh.inc"
    ;
const char kSh16[] =
#include "jit_src/generated_sh16.cuh.inc"
    ;
const char kLayer0[] =
#include "jit_src/layer0_kernels.cuh.inc"
    ;
const char kConv[] =
#include "jit_src/generated_conv.cuh.inc"
    ;

// The cache file format; bump when the key or the file layout changes.
constexpr const char kMagic[8] = {'L', 'O', 'U', 'P', 'J', 'I', 'T', '1'};

struct Nvrtc {
    void* lib = nullptr;
    int major = 0, minor = 0;
    nvrtcResult (*version)(int*, int*) = nullptr;
    nvrtcResult (*create)(nvrtcProgram*, const char*, const char*, int, const char* const*, const char* const*) = nullptr;
    nvrtcResult (*destroy)(nvrtcProgram*) = nullptr;
    nvrtcResult (*compile)(nvrtcProgram, int, const char* const*) = nullptr;
    nvrtcResult (*log_size)(nvrtcProgram, size_t*) = nullptr;
    nvrtcResult (*log)(nvrtcProgram, char*) = nullptr;
    nvrtcResult (*cubin_size)(nvrtcProgram, size_t*) = nullptr;
    nvrtcResult (*cubin)(nvrtcProgram, char*) = nullptr;
    nvrtcResult (*add_name)(nvrtcProgram, const char*) = nullptr;
    nvrtcResult (*lowered)(nvrtcProgram, const char*, const char**) = nullptr;
    std::string why;  // why loading failed

    template <typename F>
    bool sym(F& f, const char* name) {
        f = reinterpret_cast<F>(dlsym(lib, name));
        return f != nullptr;
    }
    bool load() {
        // LOUP_NVRTC, when set, is the only library tried (a path or a soname)
        const char* env = std::getenv("LOUP_NVRTC");
        const bool own = env && env[0];
        const char* names[] = {own ? env : "libnvrtc.so.13", own ? nullptr : "libnvrtc.so.12",
                               own ? nullptr : "libnvrtc.so"};
        for (const char* n : names) {
            if (!n) continue;
            lib = dlopen(n, RTLD_NOW | RTLD_LOCAL);
            if (lib) break;
        }
        if (!lib) {
            why = own ? std::string("NVRTC not loaded from LOUP_NVRTC=") + env
                      : "NVRTC not found (libnvrtc.so.13 / .12; LOUP_NVRTC names the library)";
            return false;
        }
        if (!sym(version, "nvrtcVersion") || !sym(create, "nvrtcCreateProgram") ||
            !sym(destroy, "nvrtcDestroyProgram") || !sym(compile, "nvrtcCompileProgram") ||
            !sym(log_size, "nvrtcGetProgramLogSize") || !sym(log, "nvrtcGetProgramLog") ||
            !sym(cubin_size, "nvrtcGetCUBINSize") || !sym(cubin, "nvrtcGetCUBIN") ||
            !sym(add_name, "nvrtcAddNameExpression") || !sym(lowered, "nvrtcGetLoweredName")) {
            why = "NVRTC lacks a symbol this library needs";
            dlclose(lib);
            lib = nullptr;
            return false;
        }
        version(&major, &minor);
        return true;
    }
};

Nvrtc& nvrtc() {
    static Nvrtc n;
    static const bool ok = n.load();
    (void)ok;
    return n;
}

std::mutex g_mu;
std::map<uint64_t, std::vector<const void*>> g_mem;  // key -> kernels (modules are never unloaded)
Stats g_stats;

// FNV-1a 64 over length-prefixed parts (a cache key, not a security boundary: the cache folder is the user's own)
struct Hasher {
    uint64_t h = 1469598103934665603ull;
    void bytes(const void* p, size_t n) {
        const unsigned char* c = static_cast<const unsigned char*>(p);
        for (size_t i = 0; i < n; ++i) {
            h ^= c[i];
            h *= 1099511628211ull;
        }
    }
    void str(const std::string& s) {
        const uint64_t n = s.size();
        bytes(&n, sizeof(n));
        bytes(s.data(), s.size());
    }
};

std::string cache_dir() {
    const char* c = std::getenv("LOUP_CACHE_DIR");
    if (c && c[0]) return std::string(c) + "/jit";
    if (const char* hm = std::getenv("HOME")) return std::string(hm) + "/.cache/loupmd/jit";
    return std::string();
}

void mkdirs(const std::string& path) {
    for (size_t pos = 1; (pos = path.find('/', pos)) != std::string::npos; ++pos) mkdir(path.substr(0, pos).c_str(), 0755);
    mkdir(path.c_str(), 0755);
}

// File: magic, u32 count, count x (u32 length, lowered name), u64 cubin size, cubin.
bool read_cache(const std::string& path, std::vector<std::string>& names, std::string& cubin, size_t want) {
    FILE* fp = fopen(path.c_str(), "rb");
    if (!fp) return false;
    bool ok = false;
    char magic[8];
    uint32_t cnt = 0;
    if (fread(magic, 1, 8, fp) == 8 && memcmp(magic, kMagic, 8) == 0 && fread(&cnt, 4, 1, fp) == 1 && cnt == want) {
        ok = true;
        for (uint32_t i = 0; i < cnt && ok; ++i) {
            uint32_t n = 0;
            if (fread(&n, 4, 1, fp) != 1 || n > 4096) { ok = false; break; }
            std::string s(n, '\0');
            if (n && fread(&s[0], 1, n, fp) != n) { ok = false; break; }
            names.push_back(s);
        }
        uint64_t sz = 0;
        if (ok && fread(&sz, 8, 1, fp) == 1 && sz > 0 && sz < (256ull << 20)) {
            cubin.resize(sz);
            ok = fread(&cubin[0], 1, sz, fp) == sz;
        } else {
            ok = false;
        }
    }
    fclose(fp);
    return ok;
}

void write_cache(const std::string& dir, const std::string& path, const std::vector<std::string>& names,
                 const std::string& cubin) {
    mkdirs(dir);
    const std::string tmp = path + ".tmp." + std::to_string((long long)getpid());
    FILE* fp = fopen(tmp.c_str(), "wb");
    if (!fp) return;
    bool ok = fwrite(kMagic, 1, 8, fp) == 8;
    const uint32_t cnt = (uint32_t)names.size();
    ok = ok && fwrite(&cnt, 4, 1, fp) == 1;
    for (const auto& s : names) {
        const uint32_t n = (uint32_t)s.size();
        ok = ok && fwrite(&n, 4, 1, fp) == 1 && fwrite(s.data(), 1, n, fp) == n;
    }
    const uint64_t sz = cubin.size();
    ok = ok && fwrite(&sz, 8, 1, fp) == 1 && fwrite(cubin.data(), 1, sz, fp) == sz;
    ok = (fclose(fp) == 0) && ok;
    if (ok) rename(tmp.c_str(), path.c_str());
    else unlink(tmp.c_str());
}

bool debug() {
    static const bool d = [] {
        const char* e = std::getenv("LOUP_DEBUG_JIT");
        return e && e[0] == '1';
    }();
    return d;
}

}  // namespace

const std::vector<Header>& embedded_headers() {
    static const std::vector<Header> h = {
        {"kernels_common.cuh", kKernelsCommon},
        {"generated_sh16.cuh", kSh16},
        {"layer0_kernels.cuh", kLayer0},
        {"generated_conv.cuh", kConv},
    };
    return h;
}

int level() {
    static const int lv = [] {
        const char* e = std::getenv("LOUP_JIT");
        if (e && e[0] == '0') return 0;
        if (e && e[0] == '1') return 2;
        return 1;
    }();
    return lv;
}

Stats stats() {
    std::lock_guard<std::mutex> lk(g_mu);
    return g_stats;
}

std::vector<const void*> build(const std::string& tag, const std::string& src, const std::vector<Header>& headers,
                               const std::vector<std::string>& name_exprs, std::string* err) {
    auto fail = [&](const std::string& why) {
        if (err) *err = why;
        if (debug()) fprintf(stderr, "[loupmd jit] %s: %s\n", tag.c_str(), why.c_str());
        ++g_stats.failures;
        return std::vector<const void*>();
    };
    std::lock_guard<std::mutex> lk(g_mu);
    Nvrtc& nv = nvrtc();
    if (!nv.lib) return fail(nv.why);

    int dev = 0, major = 0, minor = 0;
    if (cudaGetDevice(&dev) != cudaSuccess ||
        cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, dev) != cudaSuccess ||
        cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, dev) != cudaSuccess)
        return fail("no CUDA device");
    const std::string arch = "-arch=sm_" + std::to_string(major * 10 + minor);
    const std::vector<std::string> opts = {arch, "-std=c++17", "-diag-suppress=1046"};

    Hasher hs;
    hs.bytes(kMagic, 8);
    hs.str(std::to_string(nv.major) + "." + std::to_string(nv.minor));
    for (const auto& o : opts) hs.str(o);
    for (const auto& h : headers) {
        hs.str(h.name);
        hs.str(h.text);
    }
    hs.str(src);
    for (const auto& n : name_exprs) hs.str(n);
    const uint64_t key = hs.h;

    auto it = g_mem.find(key);
    if (it != g_mem.end()) {
        ++g_stats.memory_hits;
        return it->second;
    }

    char kbuf[40];
    snprintf(kbuf, sizeof(kbuf), "%016llx", (unsigned long long)key);
    const std::string dir = cache_dir();
    const std::string path = dir.empty() ? std::string() : dir + "/" + tag + "_" + kbuf + ".bin";

    std::vector<std::string> lowered;
    std::string cubin;
    bool from_disk = !path.empty() && read_cache(path, lowered, cubin, name_exprs.size());
    if (!from_disk) {
        lowered.clear();
        nvrtcProgram prog = nullptr;
        std::vector<const char*> hn, ht;
        for (const auto& h : headers) {
            hn.push_back(h.name);
            ht.push_back(h.text);
        }
        if (nv.create(&prog, src.c_str(), (tag + ".cu").c_str(), (int)headers.size(), ht.data(), hn.data()) !=
            NVRTC_SUCCESS)
            return fail("nvrtcCreateProgram failed");
        for (const auto& n : name_exprs) nv.add_name(prog, n.c_str());
        std::vector<const char*> ov;
        for (const auto& o : opts) ov.push_back(o.c_str());
        const nvrtcResult r = nv.compile(prog, (int)ov.size(), ov.data());
        size_t ls = 0;
        nv.log_size(prog, &ls);
        std::string log(ls, '\0');
        if (ls) nv.log(prog, &log[0]);
        if (r != NVRTC_SUCCESS) {
            nv.destroy(&prog);
            return fail("compile failed:\n" + log);
        }
        for (const auto& n : name_exprs) {
            const char* ln = nullptr;
            if (nv.lowered(prog, n.c_str(), &ln) != NVRTC_SUCCESS || !ln) {
                nv.destroy(&prog);
                return fail("no lowered name for " + n);
            }
            lowered.push_back(ln);
        }
        size_t cs = 0;
        nv.cubin_size(prog, &cs);
        cubin.resize(cs);
        if (!cs || nv.cubin(prog, &cubin[0]) != NVRTC_SUCCESS) {
            nv.destroy(&prog);
            return fail("no cubin");
        }
        nv.destroy(&prog);
        if (!path.empty()) write_cache(dir, path, lowered, cubin);
    }

    cudaLibrary_t lib = nullptr;
    if (cudaLibraryLoadData(&lib, cubin.data(), nullptr, nullptr, 0, nullptr, nullptr, 0) != cudaSuccess) {
        cudaGetLastError();
        return fail("cudaLibraryLoadData failed");
    }
    std::vector<const void*> ks;
    for (const auto& ln : lowered) {
        cudaKernel_t k = nullptr;
        if (cudaLibraryGetKernel(&k, lib, ln.c_str()) != cudaSuccess || !k) {
            cudaGetLastError();
            cudaLibraryUnload(lib);
            return fail("kernel " + ln + " not in the cubin");
        }
        ks.push_back(reinterpret_cast<const void*>(k));
    }
    if (from_disk) ++g_stats.disk_hits;
    else ++g_stats.compiled;
    if (debug())
        fprintf(stderr, "[loupmd jit] %s: %zu kernel(s) %s (%s, NVRTC %d.%d)\n", tag.c_str(), ks.size(),
                from_disk ? "from the disk cache" : "compiled", arch.c_str() + 6, nv.major, nv.minor);
    g_mem[key] = ks;
    return ks;
}

}  // namespace jit
}  // namespace loup
