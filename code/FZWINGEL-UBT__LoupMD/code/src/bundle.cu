#include "bundle.hpp"

#include <cstdio>
#include <cstring>
#include <memory>

namespace loup {

long long parse_int(const std::string& s) {
    size_t i = 0;
    bool neg = false;
    if (i < s.size() && (s[i] == '-' || s[i] == '+')) neg = s[i++] == '-';
    if (i == s.size()) throw std::runtime_error("bundle meta: not an integer: '" + s + "'");
    long long v = 0;
    for (; i < s.size(); ++i) {
        if (s[i] < '0' || s[i] > '9') throw std::runtime_error("bundle meta: not an integer: '" + s + "'");
        v = v * 10 + (s[i] - '0');
        if (v > (1LL << 53)) throw std::runtime_error("bundle meta: integer out of range: '" + s + "'");
    }
    return neg ? -v : v;
}

namespace {
struct FileCloser {
    void operator()(FILE* f) const { if (f) fclose(f); }
};

size_t dtype_size(DType d) {
    switch (d) {
        case DType::F32: return 4;
        case DType::F64: return 8;
        case DType::I32: return 4;
        case DType::U8: return 1;
    }
    return 0;
}
const char* dtype_name(DType d) {
    switch (d) {
        case DType::F32: return "f32";
        case DType::F64: return "f64";
        case DType::I32: return "i32";
        case DType::U8: return "u8";
    }
    return "?";
}
}  // namespace

Bundle::Bundle(const char* path) : path_(path ? path : "") {
    std::unique_ptr<FILE, FileCloser> fp(fopen(path_.c_str(), "rb"));
    if (!fp) throw std::runtime_error("Cannot open .loup file: " + path_);
    if (fseek(fp.get(), 0, SEEK_END) != 0) throw std::runtime_error("Cannot seek .loup file: " + path_);
    const long size = ftell(fp.get());
    rewind(fp.get());
    if (size < 0) throw std::runtime_error("Cannot size .loup file: " + path_);
    uint64_t remaining = (uint64_t)size;
    auto read = [&](void* dst, size_t n, const char* what) {
        if (n > remaining || (n && fread(dst, 1, n, fp.get()) != n))
            throw std::runtime_error(path_ + ": truncated .loup bundle (reading " + what + ")");
        remaining -= n;
    };
    char magic[8];
    read(magic, 8, "magic");
    if (memcmp(magic, "LOUPC001", 8) != 0)
        throw std::runtime_error(path_ + ": not a LOUPC001 bundle (re-export it with python/loupmd.py)");
    uint32_t n_entries = 0;
    read(&n_entries, 4, "entry count");
    if (n_entries > 100000) throw std::runtime_error(path_ + ": implausible entry count");
    for (uint32_t e = 0; e < n_entries; ++e) {
        uint16_t name_len = 0;
        read(&name_len, 2, "entry name length");
        std::string name(name_len, '\0');
        read(&name[0], name_len, "entry name");
        uint8_t dt = 0, ndim = 0;
        read(&dt, 1, "dtype");
        read(&ndim, 1, "ndim");
        if (dt > 3) throw std::runtime_error(path_ + ": entry '" + name + "' has an unknown dtype");
        if (ndim > 8) throw std::runtime_error(path_ + ": entry '" + name + "' has too many dimensions");
        BundleEntry ent;
        ent.dtype = (DType)dt;
        ent.dims.resize(ndim);
        if (ndim) read(ent.dims.data(), 8 * (size_t)ndim, "dims");
        uint64_t bytes = dtype_size(ent.dtype);
        for (uint64_t d : ent.dims) {
            if (d != 0 && bytes > remaining / d) throw std::runtime_error(path_ + ": truncated .loup bundle (entry '" + name + "')");
            bytes *= d;
        }
        ent.data.resize((size_t)bytes);
        read(ent.data.data(), (size_t)bytes, name.c_str());
        if (!entries_.emplace(name, std::move(ent)).second)
            throw std::runtime_error(path_ + ": duplicate entry '" + name + "'");
    }
    char trailer[8];
    read(trailer, 8, "end marker");
    if (memcmp(trailer, "LOUPEND\0", 8) != 0) throw std::runtime_error(path_ + ": bad end marker");
    if (remaining != 0) throw std::runtime_error(path_ + ": trailing bytes after the end marker");

    auto it = entries_.find("meta");
    if (it == entries_.end() || it->second.dtype != DType::U8) throw std::runtime_error(path_ + ": no meta entry");
    const std::string text(it->second.data.begin(), it->second.data.end());
    size_t pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        const std::string line = text.substr(pos, end - pos);
        pos = end + 1;
        if (line.empty()) continue;
        const size_t eq = line.find('=');
        if (eq == std::string::npos) throw std::runtime_error(path_ + ": malformed meta line '" + line + "'");
        meta_[line.substr(0, eq)] = line.substr(eq + 1);
    }
}

const BundleEntry& Bundle::entry(const std::string& name) const {
    auto it = entries_.find(name);
    if (it == entries_.end()) throw std::runtime_error(path_ + ": missing entry '" + name + "'");
    return it->second;
}

const BundleEntry& Bundle::checked(const std::string& name, DType dt, const std::vector<int64_t>& shape) const {
    const BundleEntry& e = entry(name);
    if (e.dtype != dt)
        throw std::runtime_error(path_ + ": entry '" + name + "' is " + dtype_name(e.dtype) + ", expected " + dtype_name(dt));
    if (!shape.empty()) {
        bool ok = shape.size() == e.dims.size();
        for (size_t i = 0; ok && i < shape.size(); ++i) ok = shape[i] < 0 || (uint64_t)shape[i] == e.dims[i];
        if (!ok) {
            std::string got, want;
            for (uint64_t d : e.dims) got += std::to_string(d) + ",";
            for (int64_t d : shape) want += std::to_string(d) + ",";
            throw std::runtime_error(path_ + ": entry '" + name + "' has shape [" + got + "], expected [" + want + "]");
        }
    }
    return e;
}

template <typename T>
static std::vector<T> as_vec(const BundleEntry& e) {
    std::vector<T> v(e.count());
    if (!v.empty()) memcpy(v.data(), e.data.data(), v.size() * sizeof(T));
    return v;
}

std::vector<float> Bundle::f32(const std::string& name, const std::vector<int64_t>& shape) const {
    return as_vec<float>(checked(name, DType::F32, shape));
}
std::vector<double> Bundle::f64(const std::string& name, const std::vector<int64_t>& shape) const {
    return as_vec<double>(checked(name, DType::F64, shape));
}
std::vector<int32_t> Bundle::i32(const std::string& name, const std::vector<int64_t>& shape) const {
    return as_vec<int32_t>(checked(name, DType::I32, shape));
}

const std::string& Bundle::meta(const std::string& key) const {
    auto it = meta_.find(key);
    if (it == meta_.end()) throw std::runtime_error(path_ + ": missing meta key '" + key + "'");
    return it->second;
}
int Bundle::meta_int(const std::string& key) const { return (int)parse_int(meta(key)); }
std::vector<int> Bundle::meta_ints(const std::string& key) const {
    std::vector<int> out;
    const std::string& s = meta(key);
    size_t pos = 0;
    while (pos <= s.size() && !s.empty()) {
        size_t end = s.find(',', pos);
        if (end == std::string::npos) end = s.size();
        out.push_back((int)parse_int(s.substr(pos, end - pos)));
        pos = end + 1;
    }
    return out;
}

}  // namespace loup
