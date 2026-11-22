Zstandard library : usage examples
==================================

- [Simple compression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/simple_compression.c) :
  Compress a single file.
  Introduces usage of : `ZSTD_compress()`

- [Simple decompression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/simple_decompression.c) :
  Decompress a single file.
  Only compatible with simple compression.
  Result remains in memory.
  Introduces usage of : `ZSTD_decompress()`

- [Streaming memory usage](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/streaming_memory_usage.c) :
  Provides amount of memory used by streaming context
  Introduces usage of : `ZSTD_sizeof_CStream()`

- [Streaming compression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/streaming_compression.c) :
  Compress a single file.
  Introduces usage of : `ZSTD_compressStream()`

- [Multiple Streaming compression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/multiple_streaming_compression.c) :
  Compress multiple files in a single command line.
  Introduces memory usage preservation technique,
  reducing impact of malloc()/free() and memset() by re-using existing resources.

- [Streaming decompression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/streaming_decompression.c) :
  Decompress a single file compressed by zstd.
  Compatible with both simple and streaming compression.
  Result is sent to stdout.
  Introduces usage of : `ZSTD_decompressStream()`

- [Dictionary compression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/dictionary_compression.c) :
  Compress multiple files using the same dictionary.
  Introduces usage of : `ZSTD_createCDict()` and `ZSTD_compress_usingCDict()`

- [Dictionary decompression](https://github.com/steineggerlab/foldseek/blob/HEAD/lib/mmseqs/lib/zstd/examples/dictionary_decompression.c) :
  Decompress multiple files using the same dictionary.
  Result remains in memory.
  Introduces usage of : `ZSTD_createDDict()` and `ZSTD_decompress_usingDDict()`
