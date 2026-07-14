#include "mqtt_app.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "app_config_defaults.h"
#include "cJSON.h"
#include "command_catalog.generated.h"
#include "control_state.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_random.h"
#include "firmware_behavior.generated.h"
#include "mqtt_client.h"
#include "nvs.h"

static const char *TAG = "MQTT_APP";

static app_config_t s_config;
static esp_mqtt_client_handle_t s_client;
static mqtt_app_command_handler_t s_command_handler;
static char s_status_topic[96];
static char s_status_offline_payload[320];
static char s_boot_id[24];
static uint32_t s_sequence;

static bool capability_enabled(const char *name);

typedef struct {
    char command_id[64];
    char trace_id[64];
    char status[16];
    char message[64];
} recent_ack_t;

static recent_ack_t s_recent_acks[AIOT_TERMINAL_ACK_CACHE_SIZE];
static uint8_t s_recent_ack_index;

static cJSON *create_envelope(cJSON *payload, const char *trace_id, const char *message_id) {
    if (!payload) {
        return NULL;
    }
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        cJSON_Delete(payload);
        return NULL;
    }
    char generated_id[64];
    snprintf(generated_id, sizeof(generated_id), "msg-%s-%lu", s_boot_id, (unsigned long)++s_sequence);
    cJSON_AddStringToObject(root, "schema_version", AIOT_PROTOCOL_VERSION);
    cJSON_AddStringToObject(root, "message_id", message_id && message_id[0] ? message_id : generated_id);
    if (trace_id && trace_id[0]) {
        cJSON_AddStringToObject(root, "trace_id", trace_id);
    } else {
        cJSON_AddNullToObject(root, "trace_id");
    }
    cJSON_AddStringToObject(root, "device_id", s_config.device_id);
    cJSON_AddNullToObject(root, "occurred_at");
    cJSON_AddStringToObject(root, "boot_id", s_boot_id);
    cJSON_AddNumberToObject(root, "sequence", s_sequence);
    cJSON_AddItemToObject(root, "payload", payload);
    return root;
}

static void load_recent_acks(void) {
    nvs_handle_t handle;
    if (nvs_open("cmd_dedup", NVS_READONLY, &handle) != ESP_OK) {
        return;
    }
    size_t size = sizeof(s_recent_acks);
    if (nvs_get_blob(handle, "recent", s_recent_acks, &size) != ESP_OK || size != sizeof(s_recent_acks)) {
        memset(s_recent_acks, 0, sizeof(s_recent_acks));
    }
    uint8_t index = 0;
    if (nvs_get_u8(handle, "index", &index) == ESP_OK) {
        s_recent_ack_index = index % AIOT_TERMINAL_ACK_CACHE_SIZE;
    }
    nvs_close(handle);
}

static void save_recent_acks(void) {
    nvs_handle_t handle;
    if (nvs_open("cmd_dedup", NVS_READWRITE, &handle) != ESP_OK) {
        return;
    }
    nvs_set_blob(handle, "recent", s_recent_acks, sizeof(s_recent_acks));
    nvs_set_u8(handle, "index", s_recent_ack_index);
    nvs_commit(handle);
    nvs_close(handle);
}

static const recent_ack_t *find_recent_ack(const char *command_id) {
    if (!command_id || !command_id[0]) {
        return NULL;
    }
    for (size_t i = 0; i < AIOT_TERMINAL_ACK_CACHE_SIZE; ++i) {
        if (strcmp(s_recent_acks[i].command_id, command_id) == 0) {
            return &s_recent_acks[i];
        }
    }
    return NULL;
}

static void remember_terminal_ack(const mqtt_app_command_t *command, const char *status, const char *message) {
    if (!command || !status || strcmp(status, "accepted") == 0) {
        return;
    }
    recent_ack_t *entry = &s_recent_acks[s_recent_ack_index];
    memset(entry, 0, sizeof(*entry));
    strlcpy(entry->command_id, command->command_id, sizeof(entry->command_id));
    strlcpy(entry->trace_id, command->trace_id, sizeof(entry->trace_id));
    strlcpy(entry->status, status, sizeof(entry->status));
    strlcpy(entry->message, message ? message : "", sizeof(entry->message));
    s_recent_ack_index = (s_recent_ack_index + 1) % AIOT_TERMINAL_ACK_CACHE_SIZE;
    save_recent_acks();
}

static esp_err_t make_topic(char *buffer, size_t buffer_size, const char *suffix) {
    if (!buffer || buffer_size == 0 || !suffix || s_config.device_id[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }

    const int written = snprintf(buffer, buffer_size, "devices/%s/%s", s_config.device_id, suffix);
    if (written < 0 || written >= (int)buffer_size) {
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}

static void copy_json_string(char *dest, size_t dest_size, const cJSON *root, const char *key) {
    if (!dest || dest_size == 0) {
        return;
    }
    dest[0] = '\0';
    if (!root || !key) {
        return;
    }

    const cJSON *item = cJSON_GetObjectItemCaseSensitive(root, key);
    if (cJSON_IsString(item) && item->valuestring) {
        strlcpy(dest, item->valuestring, dest_size);
    }
}

static int64_t utc_days_from_civil(int year, unsigned month, unsigned day) {
    year -= month <= 2;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned year_of_era = (unsigned)(year - era * 400);
    const unsigned adjusted_month = (unsigned)((int)month + (month > 2 ? -3 : 9));
    const unsigned day_of_year = (153 * adjusted_month + 2) / 5 + day - 1;
    const unsigned day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    return (int64_t)era * 146097 + (int64_t)day_of_era - 719468;
}

static bool valid_utc_date(int year, int month, int day) {
    static const int days_per_month[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    if (year < 1970 || month < 1 || month > 12 || day < 1) {
        return false;
    }
    int maximum = days_per_month[month - 1];
    if (month == 2 && (year % 400 == 0 || (year % 4 == 0 && year % 100 != 0))) {
        maximum = 29;
    }
    return day <= maximum;
}

static bool valid_utc_suffix(const char *value) {
    const char *suffix = value + 19;
    if (*suffix == '.') {
        ++suffix;
        if (*suffix < '0' || *suffix > '9') {
            return false;
        }
        while (*suffix >= '0' && *suffix <= '9') {
            ++suffix;
        }
    }
    return strcmp(suffix, "Z") == 0 || strcmp(suffix, "+00:00") == 0;
}

static const char *validate_command_expiry(const cJSON *body) {
    const cJSON *expires_at = cJSON_GetObjectItemCaseSensitive(body, "expires_at");
    if (!expires_at || cJSON_IsNull(expires_at)) {
        return NULL;
    }
    if (!cJSON_IsString(expires_at) || !expires_at->valuestring) {
        return "invalid_parameter";
    }

    const time_t now = time(NULL);
    if (now < 1704067200) { // 2024-01-01 UTC: system clock is not trustworthy yet.
        ESP_LOGW(TAG, "system time not synchronized; expires_at cannot be enforced yet");
        return NULL;
    }

    int year, month, day, hour, minute, second;
    if (strlen(expires_at->valuestring) < 20 || expires_at->valuestring[4] != '-' ||
        expires_at->valuestring[7] != '-' || expires_at->valuestring[10] != 'T' || expires_at->valuestring[13] != ':' ||
        expires_at->valuestring[16] != ':' ||
        sscanf(expires_at->valuestring, "%4d-%2d-%2dT%2d:%2d:%2d", &year, &month, &day, &hour, &minute, &second) != 6 ||
        !valid_utc_suffix(expires_at->valuestring) || !valid_utc_date(year, month, day) || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59 || second < 0 || second > 60) {
        return "invalid_parameter";
    }
    const int64_t expiry =
        utc_days_from_civil(year, (unsigned)month, (unsigned)day) * 86400 + hour * 3600 + minute * 60 + second;
    return expiry <= (int64_t)now ? "expired" : NULL;
}

static uint32_t command_source_mask(cloud_command_source_t source) {
    switch (source) {
    case CLOUD_COMMAND_SOURCE_FRONTEND:
        return 1U;
    case CLOUD_COMMAND_SOURCE_AI:
        return 2U;
    case CLOUD_COMMAND_SOURCE_EXTERNAL_MCP:
        return 4U;
    case CLOUD_COMMAND_SOURCE_RULE:
        return 8U;
    case CLOUD_COMMAND_SOURCE_UNKNOWN:
    default:
        return 0U;
    }
}

static uint32_t command_allowed_source_mask(cloud_command_type_t type) {
    switch (type) {
#define SOURCE_CASE(command_enum, command_name, ai_allowed, safety_class, parameter_schema_json, source_mask)          \
    case command_enum:                                                                                                 \
        return source_mask;
        AIOT_COMMAND_CATALOG(SOURCE_CASE)
#undef SOURCE_CASE
    default:
        return 0U;
    }
}

static bool object_only_has(const cJSON *object, const char *first, const char *second) {
    for (const cJSON *item = object ? object->child : NULL; item; item = item->next) {
        if ((!first || strcmp(item->string, first) != 0) && (!second || strcmp(item->string, second) != 0)) {
            return false;
        }
    }
    return true;
}

static bool command_parameter_valid(cloud_command_type_t type, const cJSON *parameter) {
    if (!cJSON_IsObject(parameter)) {
        return false;
    }
    const cJSON *value;
    switch (type) {
    case CLOUD_COMMAND_WINDOW_OPEN:
    case CLOUD_COMMAND_WINDOW_CLOSE:
    case CLOUD_COMMAND_ALARM_ON:
    case CLOUD_COMMAND_ALARM_OFF:
    case CLOUD_COMMAND_LED_ON:
    case CLOUD_COMMAND_LED_OFF:
    case CLOUD_COMMAND_CONTROL_RESUME_AUTO:
        return parameter->child == NULL;
    case CLOUD_COMMAND_CONTROL_SET_PRIORITY:
        value = cJSON_GetObjectItemCaseSensitive(parameter, "priority");
        return object_only_has(parameter, "priority", NULL) && cJSON_GetArraySize(parameter) == 1 &&
               cJSON_IsString(value) &&
               (strcmp(value->valuestring, "manual_first") == 0 || strcmp(value->valuestring, "auto_first") == 0);
    case CLOUD_COMMAND_ALARM_SILENCE:
        value = cJSON_GetObjectItemCaseSensitive(parameter, "duration_seconds");
        return object_only_has(parameter, "duration_seconds", NULL) && cJSON_GetArraySize(parameter) <= 1 &&
               (!value || (cJSON_IsNumber(value) && value->valuedouble == (double)value->valueint &&
                           value->valueint >= (int)AIOT_SMOKE_SILENCE_MIN_SECONDS &&
                           value->valueint <= (int)AIOT_SMOKE_SILENCE_MAX_SECONDS));
    case CLOUD_COMMAND_VOICE_SPEAK:
        value = cJSON_GetObjectItemCaseSensitive(parameter, "gb2312_base64");
        return object_only_has(parameter, "gb2312_base64", NULL) && cJSON_GetArraySize(parameter) == 1 &&
               cJSON_IsString(value) && strlen(value->valuestring) >= 4 && strlen(value->valuestring) <= 320;
    case CLOUD_COMMAND_DISPLAY_MESSAGE:
        value = cJSON_GetObjectItemCaseSensitive(parameter, "text");
        return object_only_has(parameter, "text", NULL) && cJSON_GetArraySize(parameter) == 1 &&
               cJSON_IsString(value) && strlen(value->valuestring) >= 1 && strlen(value->valuestring) <= 120;
    default:
        return false;
    }
}

static void handle_command_payload(const char *payload) {
    if (!payload) {
        return;
    }

    cJSON *root = cJSON_Parse(payload);
    if (!root) {
        ESP_LOGW(TAG, "command payload is not JSON: %s", payload);
        return;
    }

    const cJSON *schema_version = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
    const cJSON *nested_payload = cJSON_GetObjectItemCaseSensitive(root, "payload");
    const cJSON *device_id = cJSON_GetObjectItemCaseSensitive(root, "device_id");
    if (!cJSON_IsString(schema_version) || strcmp(schema_version->valuestring, AIOT_PROTOCOL_VERSION) != 0 ||
        !cJSON_IsString(device_id) || strcmp(device_id->valuestring, s_config.device_id) != 0 ||
        !cJSON_HasObjectItem(root, "message_id") || !cJSON_HasObjectItem(root, "occurred_at") ||
        !cJSON_HasObjectItem(root, "boot_id") || !cJSON_HasObjectItem(root, "sequence") ||
        !cJSON_IsObject(nested_payload)) {
        ESP_LOGW(TAG, "rejecting command without a valid MQTT v2 envelope");
        cJSON_Delete(root);
        return;
    }
    const cJSON *body = nested_payload;

    mqtt_app_command_t envelope = {0};
    command_clear(&envelope.command);
    copy_json_string(envelope.command_id, sizeof(envelope.command_id), body, "command_id");
    copy_json_string(envelope.trace_id, sizeof(envelope.trace_id), root, "trace_id");
    if (envelope.command_id[0] == '\0') {
        ESP_LOGW(TAG, "command_id is required");
        cJSON_Delete(root);
        return;
    }

    char command_type[64] = {0};
    copy_json_string(command_type, sizeof(command_type), body, "type");
    esp_err_t err = command_from_name(command_type, &envelope.command);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "unsupported command type=%s", command_type);
        mqtt_app_publish_command_ack(&envelope, "rejected", "unsupported_command");
        cJSON_Delete(root);
        return;
    }

    const cJSON *confidence = cJSON_GetObjectItemCaseSensitive(body, "confidence");
    if (cJSON_IsNumber(confidence)) {
        envelope.command.confidence = (float)confidence->valuedouble;
    }

    char source[24] = {0};
    copy_json_string(source, sizeof(source), body, "source");
    if (strcmp(source, "frontend") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_FRONTEND;
    } else if (strcmp(source, "ai") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_AI;
    } else if (strcmp(source, "external_mcp") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_EXTERNAL_MCP;
    } else if (strcmp(source, "rule") == 0) {
        envelope.command.source = CLOUD_COMMAND_SOURCE_RULE;
    } else {
        envelope.command.source = CLOUD_COMMAND_SOURCE_UNKNOWN;
        mqtt_app_publish_command_ack(&envelope, "rejected", "policy_denied");
        cJSON_Delete(root);
        return;
    }

    const cJSON *parameter = cJSON_GetObjectItemCaseSensitive(body, "parameter");
    if ((command_allowed_source_mask(envelope.command.type) & command_source_mask(envelope.command.source)) == 0U) {
        mqtt_app_publish_command_ack(&envelope, "rejected", "policy_denied");
        cJSON_Delete(root);
        return;
    }
    if (!capability_enabled(command_type)) {
        mqtt_app_publish_command_ack(&envelope, "rejected", "unsupported_command");
        cJSON_Delete(root);
        return;
    }
    if (!command_parameter_valid(envelope.command.type, parameter)) {
        mqtt_app_publish_command_ack(&envelope, "rejected", "invalid_parameter");
        cJSON_Delete(root);
        return;
    }
    const char *expiry_error = validate_command_expiry(body);
    if (expiry_error) {
        ESP_LOGW(TAG, "rejecting command id=%s: %s", envelope.command_id, expiry_error);
        mqtt_app_publish_command_ack(&envelope, "rejected", expiry_error);
        cJSON_Delete(root);
        return;
    }
    const recent_ack_t *recent = find_recent_ack(envelope.command_id);
    if (recent) {
        strlcpy(envelope.trace_id, recent->trace_id, sizeof(envelope.trace_id));
        ESP_LOGW(TAG, "duplicate command id=%s, replaying terminal ack", envelope.command_id);
        mqtt_app_publish_command_ack(&envelope, recent->status, recent->message);
        cJSON_Delete(root);
        return;
    }
    char *parameter_json = cJSON_PrintUnformatted(parameter);
    if (parameter_json) {
        strlcpy(envelope.command.parameter, parameter_json, sizeof(envelope.command.parameter));
        cJSON_free(parameter_json);
    }

    strlcpy(envelope.command.raw, payload, sizeof(envelope.command.raw));
    ESP_LOGI(TAG, "received command id=%s type=%s", envelope.command_id, command_type);
    if (s_command_handler) {
        s_command_handler(&envelope);
    }

    cJSON_Delete(root);
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void)handler_args;
    (void)base;

    esp_mqtt_event_handle_t event = event_data;
    if (!event) {
        return;
    }

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED: {
        ESP_LOGI(TAG, "connected");
        mqtt_app_publish_status("online");
        mqtt_app_publish_capabilities();

        char topic[96];
        if (make_topic(topic, sizeof(topic), "command") == ESP_OK) {
            esp_mqtt_client_subscribe(s_client, topic, 1);
            ESP_LOGI(TAG, "subscribed %s", topic);
        }
        break;
    }
    case MQTT_EVENT_DATA: {
        /* 超过客户端缓冲区的消息会拆成多个 DATA 事件，单个分片不是完整 JSON，直接丢弃 */
        if (event->current_data_offset != 0 || event->data_len != event->total_data_len) {
            ESP_LOGW(TAG, "discarding fragmented MQTT message (offset=%d len=%d total=%d)", event->current_data_offset,
                     event->data_len, event->total_data_len);
            break;
        }
        char *payload = malloc((size_t)event->data_len + 1);
        if (!payload) {
            ESP_LOGE(TAG, "no memory for command payload (%d bytes)", event->data_len);
            break;
        }
        memcpy(payload, event->data, event->data_len);
        payload[event->data_len] = '\0';
        handle_command_payload(payload);
        free(payload);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}

esp_err_t mqtt_app_init(const app_config_t *config) {
    if (!config) {
        return ESP_ERR_INVALID_ARG;
    }

    s_config = *config;
    snprintf(s_boot_id, sizeof(s_boot_id), "%08lx", (unsigned long)esp_random());
    load_recent_acks();
    if (!s_config.mqtt_enabled) {
        ESP_LOGW(TAG, "MQTT disabled");
        return ESP_OK;
    }
    if (s_config.mqtt_broker_uri[0] == '\0') {
        ESP_LOGW(TAG, "MQTT broker URI is empty");
        return ESP_ERR_INVALID_STATE;
    }

    ESP_RETURN_ON_ERROR(make_topic(s_status_topic, sizeof(s_status_topic), "status"), TAG, "status topic");
    snprintf(s_status_offline_payload, sizeof(s_status_offline_payload),
             "{\"schema_version\":\"%s\",\"message_id\":\"lwt-%s\",\"trace_id\":null,\"device_id\":\"%s\","
             "\"occurred_at\":null,\"boot_id\":\"%s\",\"sequence\":0,\"payload\":{\"status\":\"offline\"}}",
             AIOT_PROTOCOL_VERSION, s_boot_id, s_config.device_id, s_boot_id);

    esp_mqtt_client_config_t mqtt_config = {
        .broker.address.uri = s_config.mqtt_broker_uri,
        .session.last_will.topic = s_status_topic,
        .session.last_will.msg = s_status_offline_payload,
        .session.last_will.qos = 1,
        .session.last_will.retain = true,
    };
    s_client = esp_mqtt_client_init(&mqtt_config);
    if (!s_client) {
        return ESP_FAIL;
    }

    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    return ESP_OK;
}

esp_err_t mqtt_app_start(void) {
    if (!s_config.mqtt_enabled) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!s_client) {
        return ESP_ERR_INVALID_STATE;
    }
    return esp_mqtt_client_start(s_client);
}

esp_err_t mqtt_app_publish_status(const char *status) {
    if (!s_client || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "status"), TAG, "status topic");
    cJSON *payload = cJSON_CreateObject();
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(payload, "status", status);
    cJSON_AddStringToObject(payload, "protocol_version", AIOT_PROTOCOL_VERSION);
    cJSON *root = create_envelope(payload, NULL, NULL);
    char *json = root ? cJSON_PrintUnformatted(root) : NULL;
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }
    const int msg_id = esp_mqtt_client_publish(s_client, topic, json, 0, 1, true);
    cJSON_free(json);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

static bool capability_enabled(const char *name) {
    if (strcmp(name, "display.message") == 0) {
        return s_config.display_enabled;
    }
    if (strcmp(name, "voice.speak") == 0) {
        return CONFIG_APP_VOICE_ENABLED;
    }
    if (strcmp(name, "led.on") == 0 || strcmp(name, "led.off") == 0) {
        return CONFIG_APP_LED_ENABLED;
    }
    if (strcmp(name, "control.set_priority") == 0 || strcmp(name, "control.resume_auto") == 0) {
        return true;
    }
    if (strcmp(name, "alarm.silence") == 0) {
        return s_config.actuator_enabled && CONFIG_APP_MQ2_ENABLED;
    }
    return s_config.actuator_enabled;
}

esp_err_t mqtt_app_publish_capabilities(void) {
    if (!s_client) {
        return ESP_ERR_INVALID_STATE;
    }
    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "capabilities"), TAG, "capabilities topic");
    cJSON *payload = cJSON_CreateObject();
    cJSON *commands = cJSON_CreateArray();
    if (!payload || !commands) {
        cJSON_Delete(payload);
        cJSON_Delete(commands);
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(payload, "protocol_version", AIOT_PROTOCOL_VERSION);
    cJSON_AddStringToObject(payload, "firmware_version", "2.0.0");
    cJSON_AddStringToObject(payload, "hardware_model", "ESP32-S3-DevKitC-1");

#define ADD_CAPABILITY(command_enum, command_name, ai_allowed, safety_class, parameter_schema_json, source_mask)       \
    do {                                                                                                               \
        (void)(command_enum);                                                                                          \
        if (capability_enabled(command_name)) {                                                                        \
            cJSON *item = cJSON_CreateObject();                                                                        \
            cJSON_AddStringToObject(item, "name", command_name);                                                       \
            cJSON *schema = cJSON_Parse(parameter_schema_json);                                                        \
            cJSON_AddItemToObject(item, "parameter_schema", schema ? schema : cJSON_CreateObject());                   \
            cJSON_AddStringToObject(item, "safety_class", safety_class);                                               \
            cJSON_AddBoolToObject(item, "ai_allowed", ai_allowed);                                                     \
            cJSON *sources = cJSON_CreateArray();                                                                      \
            if ((source_mask & 1U) != 0U)                                                                              \
                cJSON_AddItemToArray(sources, cJSON_CreateString("frontend"));                                         \
            if ((source_mask & 2U) != 0U)                                                                              \
                cJSON_AddItemToArray(sources, cJSON_CreateString("ai"));                                               \
            if ((source_mask & 4U) != 0U)                                                                              \
                cJSON_AddItemToArray(sources, cJSON_CreateString("external_mcp"));                                     \
            if ((source_mask & 8U) != 0U)                                                                              \
                cJSON_AddItemToArray(sources, cJSON_CreateString("rule"));                                             \
            cJSON_AddItemToObject(item, "allowed_sources", sources);                                                   \
            cJSON_AddItemToArray(commands, item);                                                                      \
        }                                                                                                              \
    } while (0);
    AIOT_COMMAND_CATALOG(ADD_CAPABILITY)
#undef ADD_CAPABILITY

    cJSON_AddItemToObject(payload, "commands", commands);
    cJSON *root = create_envelope(payload, NULL, NULL);
    char *json = root ? cJSON_PrintUnformatted(root) : NULL;
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }
    const int msg_id = esp_mqtt_client_publish(s_client, topic, json, 0, 1, true);
    cJSON_free(json);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

static void add_optional_number(cJSON *root, const char *name, bool valid, double value) {
    if (valid) {
        cJSON_AddNumberToObject(root, name, value);
    } else {
        cJSON_AddNullToObject(root, name);
    }
}

static char *build_telemetry_json(const sensor_sample_t *sample, const fusion_state_t *fusion) {
    control_state_t control = {0};
    control_state_get(&control);

    cJSON *root = cJSON_CreateObject();
    cJSON *sensors = cJSON_CreateObject();
    cJSON *state = cJSON_CreateObject();
    cJSON *fusion_json = cJSON_CreateObject();
    if (!root || !sensors || !state || !fusion_json) {
        cJSON_Delete(root);
        cJSON_Delete(sensors);
        cJSON_Delete(state);
        cJSON_Delete(fusion_json);
        return NULL;
    }

    add_optional_number(sensors, "temperature_c", sample->climate_valid, sample->temperature_c);
    add_optional_number(sensors, "humidity_percent", sample->climate_valid, sample->humidity_percent);
    add_optional_number(sensors, "tvoc_ppb", sample->air_valid, sample->tvoc_ppb);
    add_optional_number(sensors, "hcho_ug_m3", sample->air_valid, sample->hcho_ug_m3);
    add_optional_number(sensors, "eco2_ppm", sample->air_valid, sample->eco2_ppm);
    if (sample->light_valid) {
        cJSON_AddBoolToObject(sensors, "light_is_dark", sample->light_is_dark);
    } else {
        cJSON_AddNullToObject(sensors, "light_is_dark");
    }
    if (sample->smoke_valid) {
        cJSON_AddBoolToObject(sensors, "smoke_detected", sample->smoke_detected);
    } else {
        cJSON_AddNullToObject(sensors, "smoke_detected");
    }

    cJSON_AddBoolToObject(state, "window_open", control.window_open);
    cJSON_AddBoolToObject(state, "alarm_on", control.alarm_on);
    cJSON_AddBoolToObject(state, "manual_override", control.manual_override);
    cJSON_AddBoolToObject(state, "manual_window_override", control.manual_window_override);
    cJSON_AddBoolToObject(state, "manual_led_override", control.manual_led_override);
    cJSON_AddStringToObject(state, "control_priority", control_priority_name(control.priority));
    cJSON_AddBoolToObject(state, "smoke_silenced", control.smoke_silenced);
    cJSON_AddBoolToObject(state, "led_on", control.led_on);

    cJSON_AddStringToObject(fusion_json, "air_quality", fusion_air_quality_name(fusion->air_quality));
    cJSON_AddBoolToObject(fusion_json, "recommend_open_window", fusion->recommend_open_window);
    cJSON_AddBoolToObject(fusion_json, "alarm_enabled", fusion->alarm_enabled);
    cJSON_AddStringToObject(fusion_json, "reason", fusion->reason);

    cJSON_AddItemToObject(root, "sensors", sensors);
    cJSON_AddItemToObject(root, "state", state);
    cJSON_AddItemToObject(root, "fusion", fusion_json);
    cJSON *envelope = create_envelope(root, NULL, NULL);
    char *json = envelope ? cJSON_PrintUnformatted(envelope) : NULL;
    cJSON_Delete(envelope);
    return json;
}

esp_err_t mqtt_app_publish_event(const char *type, const char *severity, const char *message) {
    if (!s_client || !type || !severity) {
        return ESP_ERR_INVALID_STATE;
    }
    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "event"), TAG, "event topic");
    cJSON *payload = cJSON_CreateObject();
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(payload, "type", type);
    cJSON_AddStringToObject(payload, "severity", severity);
    cJSON_AddStringToObject(payload, "message", message ? message : "");
    cJSON *root = create_envelope(payload, NULL, NULL);
    char *json = root ? cJSON_PrintUnformatted(root) : NULL;
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t err = ESP_OK;
    const int msg_id = esp_mqtt_client_publish(s_client, topic, json, 0, 1, false);
    if (msg_id < 0) {
        err = ESP_FAIL;
    }
    cJSON_free(json);
    return err;
}

esp_err_t mqtt_app_publish_telemetry(const sensor_sample_t *sample, const fusion_state_t *fusion) {
    if (!s_client || !sample || !fusion) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "telemetry"), TAG, "telemetry topic");

    char *payload = build_telemetry_json(sample, fusion);
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }

    const int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, 0, false);
    cJSON_free(payload);
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

esp_err_t mqtt_app_publish_command_ack(const mqtt_app_command_t *command, const char *status, const char *message) {
    if (!s_client || !command || !status) {
        return ESP_ERR_INVALID_STATE;
    }

    char topic[96];
    ESP_RETURN_ON_ERROR(make_topic(topic, sizeof(topic), "command_ack"), TAG, "ack topic");

    cJSON *payload = cJSON_CreateObject();
    if (!payload) {
        return ESP_ERR_NO_MEM;
    }
    cJSON_AddStringToObject(payload, "command_id", command->command_id);
    cJSON_AddStringToObject(payload, "status", status);
    cJSON_AddStringToObject(payload, "message", message ? message : "");
    if (strcmp(status, "rejected") == 0) {
        const char *reason = message ? message : "";
        const bool has_protocol_code = strcmp(reason, "unsupported_command") == 0 || strcmp(reason, "expired") == 0 ||
                                       strcmp(reason, "invalid_parameter") == 0 ||
                                       strcmp(reason, "policy_denied") == 0 || strcmp(reason, "safety_interlock") == 0;
        cJSON_AddStringToObject(payload, "error_code", has_protocol_code ? reason : "device_rejected");
    } else if (strcmp(status, "failed") == 0) {
        cJSON_AddStringToObject(payload, "error_code", "device_failed");
    } else {
        cJSON_AddNullToObject(payload, "error_code");
    }
    cJSON_AddItemToObject(payload, "reported_state", cJSON_CreateObject());
    cJSON *root = create_envelope(payload, command->trace_id, NULL);
    char *json = root ? cJSON_PrintUnformatted(root) : NULL;
    cJSON_Delete(root);
    if (!json) {
        return ESP_ERR_NO_MEM;
    }

    const int msg_id = esp_mqtt_client_publish(s_client, topic, json, 0, 1, false);
    cJSON_free(json);
    if (msg_id >= 0) {
        remember_terminal_ack(command, status, message);
    }
    return msg_id < 0 ? ESP_FAIL : ESP_OK;
}

esp_err_t mqtt_app_set_command_handler(mqtt_app_command_handler_t handler) {
    s_command_handler = handler;
    return ESP_OK;
}
