#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <string.h>

static inline void app_string_copy(char *dest, size_t dest_size, const char *source) {
    if (!dest || dest_size == 0) {
        return;
    }

    if (!source) {
        dest[0] = '\0';
        return;
    }

    const size_t source_len = strlen(source);
    const size_t copy_len = source_len < dest_size ? source_len : dest_size - 1;
    memcpy(dest, source, copy_len);
    dest[copy_len] = '\0';
}

static inline bool app_string_append(char *dest, size_t dest_size, const char *source) {
    if (!dest || dest_size == 0 || !source) {
        return false;
    }

    const size_t used = strnlen(dest, dest_size);
    if (used >= dest_size) {
        return false;
    }

    const size_t source_len = strlen(source);
    const size_t available = dest_size - used;
    const size_t copy_len = source_len < available ? source_len : available - 1;
    memcpy(dest + used, source, copy_len);
    dest[used + copy_len] = '\0';
    return copy_len == source_len;
}
