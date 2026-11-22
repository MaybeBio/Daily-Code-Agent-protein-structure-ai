#pragma once
// The engine's error channel (include/loupmd.h: loup_last_error).
//
// Code that refuses a call or meets a CUDA error records one message for the calling thread with set_error and
// returns -1; code that throws needs nothing more. guarded() in engine.cu clears the message when an exported call
// starts and, when the call fails, moves it (or the exception's text) into the handle. Nothing here prints.
#include <cstdarg>
#include <cstdio>
#include <string>

namespace loup {

// The message of the failure in progress on this thread; empty while no failure is recorded.
inline std::string& pending_error() {
    static thread_local std::string msg;
    return msg;
}

// Records the reason of a failure. The first message of a call wins: the code that detects a problem knows it best,
// and the callers it returns through only pass the -1 on.
#if defined(__GNUC__)
__attribute__((format(printf, 1, 2)))
#endif
inline void set_error(const char* fmt, ...) {
    std::string& msg = pending_error();
    if (!msg.empty()) return;
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    msg = buf;
}

}  // namespace loup
