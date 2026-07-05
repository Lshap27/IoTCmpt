#include "commands.h"

#include <string.h>

#include "app_string.h"
#include "esp_log.h"

static const char *TAG = "COMMANDS";

void command_clear(cloud_command_t *command)
{
    if (command) {
        memset(command, 0, sizeof(*command));
        command->type = CLOUD_COMMAND_NONE;
    }
}

esp_err_t command_from_name(const char *name, cloud_command_t *out_command)
{
    if (!name || !out_command) {
        return ESP_ERR_INVALID_ARG;
    }

    command_clear(out_command);

    if (strcmp(name, "none") == 0 || strcmp(name, "") == 0) {
        out_command->type = CLOUD_COMMAND_NONE;
    } else if (strcmp(name, "window.open") == 0 || strcmp(name, "open") == 0) {
        out_command->type = CLOUD_COMMAND_WINDOW_OPEN;
    } else if (strcmp(name, "window.close") == 0 || strcmp(name, "close") == 0) {
        out_command->type = CLOUD_COMMAND_WINDOW_CLOSE;
    } else if (strcmp(name, "alarm.on") == 0 || strcmp(name, "alarm_on") == 0) {
        out_command->type = CLOUD_COMMAND_ALARM_ON;
    } else if (strcmp(name, "alarm.off") == 0 || strcmp(name, "alarm_off") == 0) {
        out_command->type = CLOUD_COMMAND_ALARM_OFF;
    } else {
        out_command->type = CLOUD_COMMAND_UNKNOWN;
        app_string_copy(out_command->raw, sizeof(out_command->raw), name);
        return ESP_ERR_NOT_SUPPORTED;
    }

    return ESP_OK;
}

esp_err_t command_apply(const cloud_command_t *command)
{
    if (!command) {
        return ESP_ERR_INVALID_ARG;
    }

    switch (command->type) {
    case CLOUD_COMMAND_NONE:
        ESP_LOGI(TAG, "没有下游设备命令");
        return ESP_OK;
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
    case CLOUD_COMMAND_UNKNOWN:
    default:
        ESP_LOGW(TAG, "拒绝不支持的命令：%s", command->raw);
        return ESP_ERR_NOT_SUPPORTED;
    }
}

const char *command_type_name(cloud_command_type_t type)
{
    switch (type) {
    case CLOUD_COMMAND_NONE:
        return "none";
    case CLOUD_COMMAND_WINDOW_OPEN:
        return "window.open";
    case CLOUD_COMMAND_WINDOW_CLOSE:
        return "window.close";
    case CLOUD_COMMAND_ALARM_ON:
        return "alarm.on";
    case CLOUD_COMMAND_ALARM_OFF:
        return "alarm.off";
    case CLOUD_COMMAND_UNKNOWN:
    default:
        return "unknown";
    }
}
