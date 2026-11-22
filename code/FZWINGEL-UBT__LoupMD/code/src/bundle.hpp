#pragma once
// Self-describing .loup container (python/bundle.py writes it):
//   "LOUPC001" | u32 n_entries | entries | "LOUPEND\0" (and nothing after it)
//   entry: u16 name_len | name | u8 dtype (0 f32, 1 f64, 2 i32, 3 u8) | u8 ndim | u64 dims[ndim] | data (LE)
// The text entry "meta" holds "key=value" lines (architecture, integer sizes, exporter version). Every accessor checks the
// dtype and the expected shape, so a bundle from another architecture or exporter fails loudly instead of being
// misread.
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace loup {

enum class DType : uint8_t { F32 = 0, F64 = 1, I32 = 2, U8 = 3 };

struct BundleEntry {
    DType dtype = DType::U8;
    std::vector<uint64_t> dims;
    std::vector<uint8_t> data;
    size_t count() const {
        size_t n = 1;
        for (uint64_t d : dims) n *= (size_t)d;
        return n;
    }
};

class Bundle {
public:
    explicit Bundle(const char* path);

    bool has(const std::string& name) const { return entries_.count(name) != 0; }
    // Shape-checked accessors (-1 in `shape` matches any extent; an empty shape skips the check).
    std::vector<float> f32(const std::string& name, const std::vector<int64_t>& shape = {}) const;
    std::vector<double> f64(const std::string& name, const std::vector<int64_t>& shape = {}) const;
    std::vector<int32_t> i32(const std::string& name, const std::vector<int64_t>& shape = {}) const;
    const BundleEntry& entry(const std::string& name) const;

    // meta lookups
    bool has_meta(const std::string& key) const { return meta_.count(key) != 0; }
    const std::string& meta(const std::string& key) const;
    int meta_int(const std::string& key) const;
    std::vector<int> meta_ints(const std::string& key) const;  // comma-separated

private:
    const BundleEntry& checked(const std::string& name, DType dt, const std::vector<int64_t>& shape) const;
    std::map<std::string, BundleEntry> entries_;
    std::map<std::string, std::string> meta_;
    std::string path_;
};

// Integer parsing without strtol (the library must link against older glibc). Floating-point values are stored as
// f64 entries, never as text.
long long parse_int(const std::string& s);

}  // namespace loup
