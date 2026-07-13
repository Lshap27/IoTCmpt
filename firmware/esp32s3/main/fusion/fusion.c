#include "fusion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "app_string.h"

static void append_reason(char *dest, size_t dest_size, const char *format, ...) {
    if (!dest || dest_size == 0) {
        return;
    }

    const size_t used = strnlen(dest, dest_size);
    if (used >= dest_size - 1) {
        return;
    }

    va_list args;
    va_start(args, format);
    const int written = vsnprintf(dest + used, dest_size - used, format, args);
    va_end(args);

    /* 截断时回退到最近的 UTF-8 字符边界，避免把 3 字节汉字切成非法字节混进 JSON */
    if (written < 0 || (size_t)written >= dest_size - used) {
        size_t end = dest_size - 1;
        while (end > used && (dest[end - 1] & 0xC0) == 0x80) {
            end--;
        }
        if (end > used && (dest[end - 1] & 0xC0) == 0xC0) {
            end--;
        }
        dest[end] = '\0';
    }
}

esp_err_t fusion_evaluate(const sensor_sample_t *sample, fusion_state_t *out_state) {
    if (!sample || !out_state) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_state, 0, sizeof(*out_state));
    out_state->air_quality = FUSION_AIR_QUALITY_UNKNOWN;

    if (!sample->air_valid && !sample->climate_valid && !sample->light_valid) {
        app_string_copy(out_state->reason, sizeof(out_state->reason), "没有有效传感器数据");
        return ESP_OK;
    }

    bool bad = false;
    bool watch = false;
    bool ventilation_needed = false;

    if (sample->climate_valid) {
        if (sample->temperature_c > 32.0f) {
            bad = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "温度严重偏高 %.1fC；", sample->temperature_c);
        } else if (sample->temperature_c > 28.0f) {
            watch = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "温度偏高 %.1fC；", sample->temperature_c);
        }

        if (sample->humidity_percent > 75.0f || sample->humidity_percent < 30.0f) {
            watch = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "湿度异常 %.1f%%；", sample->humidity_percent);
        }
    }

    if (sample->air_valid) {
        if (sample->tvoc_ppb > 600) {
            bad = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "TVOC 严重偏高 %u；", sample->tvoc_ppb);
        } else if (sample->tvoc_ppb > 300) {
            watch = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "TVOC 偏高 %u；", sample->tvoc_ppb);
        }

        if (sample->hcho_ug_m3 > 100) {
            bad = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "HCHO 严重偏高 %u；", sample->hcho_ug_m3);
        } else if (sample->hcho_ug_m3 > 60) {
            watch = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "HCHO 偏高 %u；", sample->hcho_ug_m3);
        }

        if (sample->eco2_ppm > 1500) {
            bad = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "eCO2 严重偏高 %u；", sample->eco2_ppm);
        } else if (sample->eco2_ppm > 1000) {
            watch = true;
            ventilation_needed = true;
            append_reason(out_state->reason, sizeof(out_state->reason), "eCO2 偏高 %u；", sample->eco2_ppm);
        }
    }

    if (sample->light_valid && sample->light_is_dark) {
        append_reason(out_state->reason, sizeof(out_state->reason), "光照偏暗；");
    }

    if (sample->smoke_valid && sample->smoke_detected) {
        bad = true;
        append_reason(out_state->reason, sizeof(out_state->reason), "MQ-2 检测到烟雾；");
    }

    if (bad) {
        out_state->air_quality = FUSION_AIR_QUALITY_ALERT;
        out_state->recommend_open_window = ventilation_needed;
        /* 蜂鸣器自动来源仅保留给 MQ-2 烟雾；普通空气质量恶化由窗户和语音处理。 */
        out_state->alarm_enabled = sample->smoke_valid && sample->smoke_detected;
    } else if (watch) {
        out_state->air_quality = FUSION_AIR_QUALITY_WATCH;
        out_state->recommend_open_window = true;
        /* WATCH 只建议通风，不触发蜂鸣器；持续鸣响仅保留给 ALERT */
        out_state->alarm_enabled = false;
    } else {
        out_state->air_quality = FUSION_AIR_QUALITY_GOOD;
        out_state->recommend_open_window = false;
        out_state->alarm_enabled = false;
        app_string_copy(out_state->reason, sizeof(out_state->reason), "空气质量良好");
    }

    if (out_state->reason[0] == '\0') {
        app_string_copy(out_state->reason, sizeof(out_state->reason), "空气质量状态未知");
    }

    return ESP_OK;
}

const char *fusion_air_quality_name(fusion_air_quality_t quality) {
    switch (quality) {
    case FUSION_AIR_QUALITY_GOOD:
        return "good";
    case FUSION_AIR_QUALITY_WATCH:
        return "watch";
    case FUSION_AIR_QUALITY_ALERT:
        return "alert";
    case FUSION_AIR_QUALITY_UNKNOWN:
    default:
        return "unknown";
    }
}
