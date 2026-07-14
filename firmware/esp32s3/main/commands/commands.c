#include "commands.h"

#include <string.h>

#include "app_string.h"
#include "esp_log.h"

static const char *TAG = "COMMANDS";

void command_clear(cloud_command_t *command) {
    if (command) {
        memset(command, 0, sizeof(*command));
        command->type = CLOUD_COMMAND_UNSET;
    }
}

esp_err_t command_from_name(const char *name, cloud_command_t *out_command) {
    if (!name || !out_command) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);

    if (strcmp(name, "window.open") == 0 || strcmp(name, "open") == 0) {
        out_command->type = CLOUD_COMMAND_WINDOW_OPEN;
    } else if (strcmp(name, "window.close") == 0 || strcmp(name, "close") == 0) {
        out_command->type = CLOUD_COMMAND_WINDOW_CLOSE;
    } else if (strcmp(name, "alarm.on") == 0 || strcmp(name, "alarm_on") == 0) {
        out_command->type = CLOUD_COMMAND_ALARM_ON;
    } else if (strcmp(name, "alarm.off") == 0 || strcmp(name, "alarm_off") == 0) {
        out_command->type = CLOUD_COMMAND_ALARM_OFF;
    } else if (strcmp(name, "led.on") == 0 || strcmp(name, "led_on") == 0) {
        out_command->type = CLOUD_COMMAND_LED_ON;
    } else if (strcmp(name, "led.off") == 0 || strcmp(name, "led_off") == 0) {
        out_command->type = CLOUD_COMMAND_LED_OFF;
    } else if (strcmp(name, "control.set_priority") == 0) {
        out_command->type = CLOUD_COMMAND_CONTROL_SET_PRIORITY;
    } else if (strcmp(name, "control.resume_auto") == 0) {
        out_command->type = CLOUD_COMMAND_CONTROL_RESUME_AUTO;
    } else if (strcmp(name, "alarm.silence") == 0) {
        out_command->type = CLOUD_COMMAND_ALARM_SILENCE;
    } else if (strcmp(name, "voice.speak") == 0) {
        out_command->type = CLOUD_COMMAND_VOICE_SPEAK;
    } else if (strcmp(name, "display.message") == 0) {
        out_command->type = CLOUD_COMMAND_DISPLAY_MESSAGE;
    } else {
        out_command->type = CLOUD_COMMAND_UNKNOWN;
        app_string_copy(out_command->raw, sizeof(out_command->raw), name);
        return ESP_ERR_NOT_SUPPORTED;
    }

    return ESP_OK;
}

esp_err_t command_apply(const cloud_command_t *command) {
    if (!command) {
        return ESP_ERR_INVALID_ARG;
    }

    switch (command->type) {
    case CLOUD_COMMAND_UNSET:
        return ESP_ERR_INVALID_STATE;
    case CLOUD_COMMAND_WINDOW_OPEN:
        ESP_LOGI(TAG, "执行命令：打开窗户");
        return ESP_OK;
    case CLOUD_COMMAND_WINDOW_CLOSE:
        ESP_LOGI(TAG, "执行命令：关闭窗户");
        return ESP_OK;
    case CLOUD_COMMAND_ALARM_ON:
        ESP_LOGI(TAG, "执行命令：开启报警");
        return ESP_OK;
    case CLOUD_COMMAND_ALARM_OFF:
        ESP_LOGI(TAG, "执行命令：关闭报警");
        return ESP_OK;
    case CLOUD_COMMAND_LED_ON:
        ESP_LOGI(TAG, "执行命令：打开 LED");
        return ESP_OK;
    case CLOUD_COMMAND_LED_OFF:
        ESP_LOGI(TAG, "执行命令：关闭 LED");
        return ESP_OK;
    case CLOUD_COMMAND_CONTROL_SET_PRIORITY:
    case CLOUD_COMMAND_CONTROL_RESUME_AUTO:
    case CLOUD_COMMAND_ALARM_SILENCE:
    case CLOUD_COMMAND_VOICE_SPEAK:
    case CLOUD_COMMAND_DISPLAY_MESSAGE:
        ESP_LOGI(TAG, "执行扩展控制命令：%s", command_type_name(command->type));
        return ESP_OK;
    case CLOUD_COMMAND_UNKNOWN:
    default:
        ESP_LOGW(TAG, "拒绝不支持的命令：%s", command->raw);
        return ESP_ERR_NOT_SUPPORTED;
    }
}

const char *command_type_name(cloud_command_type_t type) {
    switch (type) {
    case CLOUD_COMMAND_UNSET:
        return "unset";
    case CLOUD_COMMAND_WINDOW_OPEN:
        return "window.open";
    case CLOUD_COMMAND_WINDOW_CLOSE:
        return "window.close";
    case CLOUD_COMMAND_ALARM_ON:
        return "alarm.on";
    case CLOUD_COMMAND_ALARM_OFF:
        return "alarm.off";
    case CLOUD_COMMAND_LED_ON:
        return "led.on";
    case CLOUD_COMMAND_LED_OFF:
        return "led.off";
    case CLOUD_COMMAND_CONTROL_SET_PRIORITY:
        return "control.set_priority";
    case CLOUD_COMMAND_CONTROL_RESUME_AUTO:
        return "control.resume_auto";
    case CLOUD_COMMAND_ALARM_SILENCE:
        return "alarm.silence";
    case CLOUD_COMMAND_VOICE_SPEAK:
        return "voice.speak";
    case CLOUD_COMMAND_DISPLAY_MESSAGE:
        return "display.message";
    case CLOUD_COMMAND_UNKNOWN:
    default:
        return "unknown";
    }
}
