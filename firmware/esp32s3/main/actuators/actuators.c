#include "actuators.h"

#include "app_config_defaults.h"
#include "control_state.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ACTUATOR";

#define SERVO_LEDC_CH          LEDC_CHANNEL_1
#define SERVO_TIMER            LEDC_TIMER_1
#define SERVO_FREQ             50
#define SERVO_MIN_US           500
#define SERVO_MAX_US           2500
#define SERVO_CLOSE_US         600
#define SERVO_OPEN_US          2200
#define SERVO_STEP_US          20
#define SERVO_STEP_DELAY_TICKS pdMS_TO_TICKS(15)

static uint16_t s_servo_current_us = SERVO_CLOSE_US;
static bool s_actuator_ready;

static void beep_set(bool on) {
    if (!s_actuator_ready) {
        return;
    }
    const int active = CONFIG_APP_BEEP_ACTIVE_LOW ? 0 : 1;
    gpio_set_level(CONFIG_APP_BEEP_GPIO, on ? active : !active);
}

static void beep_alarm_loop(uint32_t total_ms) {
    const int loops = (int)(total_ms / 200);
    for (int i = 0; i < loops; i++) {
        beep_set(true);
        vTaskDelay(pdMS_TO_TICKS(100));
        beep_set(false);
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static void servo_set_pulse(uint16_t pulse_us) {
    if (pulse_us < SERVO_MIN_US) {
        pulse_us = SERVO_MIN_US;
    }
    if (pulse_us > SERVO_MAX_US) {
        pulse_us = SERVO_MAX_US;
    }

    const uint32_t duty = (uint32_t)pulse_us * 8191 / 20000;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, SERVO_LEDC_CH, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, SERVO_LEDC_CH);
}

static void servo_smooth_turn(uint16_t target_us) {
    const uint16_t current_us = s_servo_current_us;
    if (target_us > current_us) {
        for (uint16_t pulse = current_us; pulse <= target_us; pulse += SERVO_STEP_US) {
            servo_set_pulse(pulse);
            vTaskDelay(SERVO_STEP_DELAY_TICKS);
        }
    } else if (target_us < current_us) {
        for (uint16_t pulse = current_us; pulse >= target_us; pulse -= SERVO_STEP_US) {
            servo_set_pulse(pulse);
            vTaskDelay(SERVO_STEP_DELAY_TICKS);
            if (pulse < SERVO_MIN_US + SERVO_STEP_US) {
                break;
            }
        }
    }

    servo_set_pulse(target_us);
    s_servo_current_us = target_us;
}

static esp_err_t set_window(bool open) {
    if (!s_actuator_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    control_state_t current;
    control_state_get(&current);
    if (current.window_open == open) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "窗户状态切换为：%s", open ? "打开" : "关闭");
    servo_smooth_turn(open ? SERVO_OPEN_US : SERVO_CLOSE_US);
    control_state_set_window_open(open);
    return ESP_OK;
}

esp_err_t actuator_init(void) {
    if (CONFIG_APP_ACTUATOR_ENABLED) {
        gpio_config_t beep = {
            .pin_bit_mask = 1ULL << CONFIG_APP_BEEP_GPIO,
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&beep);
        s_actuator_ready = true;
        beep_set(false);

        ledc_timer_config_t timer = {
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .timer_num = SERVO_TIMER,
            .duty_resolution = LEDC_TIMER_13_BIT,
            .freq_hz = SERVO_FREQ,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        ESP_ERROR_CHECK(ledc_timer_config(&timer));

        ledc_channel_config_t channel = {
            .gpio_num = CONFIG_APP_SERVO_GPIO,
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = SERVO_LEDC_CH,
            .intr_type = LEDC_INTR_DISABLE,
            .timer_sel = SERVO_TIMER,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_ERROR_CHECK(ledc_channel_config(&channel));
        servo_set_pulse(SERVO_CLOSE_US);
        s_servo_current_us = SERVO_CLOSE_US;
        control_state_set_window_open(false);
        ESP_LOGI(TAG, "舵机 GPIO%d、蜂鸣器 GPIO%d 初始化完成", CONFIG_APP_SERVO_GPIO, CONFIG_APP_BEEP_GPIO);
    } else {
        ESP_LOGW(TAG, "舵机和蜂鸣器已禁用；LED 逻辑控制仍可用");
    }

    if (CONFIG_APP_LED_MODE_GPIO) {
        gpio_config_t led = {
            .pin_bit_mask = 1ULL << CONFIG_APP_LED_GPIO,
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&led);
        gpio_set_level(CONFIG_APP_LED_GPIO, CONFIG_APP_LED_ACTIVE_LOW ? 1 : 0);
    }
    control_state_set_led(false);
    return ESP_OK;
}

static esp_err_t set_led(bool on) {
    if (CONFIG_APP_LED_MODE_GPIO) {
        const int active = CONFIG_APP_LED_ACTIVE_LOW ? 0 : 1;
        gpio_set_level(CONFIG_APP_LED_GPIO, on ? active : !active);
    }
    control_state_set_led(on);
    ESP_LOGI(TAG, "LED %s（%s模式）", on ? "开启" : "关闭", CONFIG_APP_LED_MODE_GPIO ? "GPIO" : "逻辑");
    return ESP_OK;
}

void actuator_refresh_alarm(void) {
    control_state_t state;
    control_state_get(&state);
    beep_set(state.alarm_on);
}

esp_err_t actuator_apply(const cloud_command_t *command, const fusion_state_t *state) {
    if (!state) {
        return ESP_ERR_INVALID_ARG;
    }

    control_state_t local;
    control_state_get(&local);

    bool target_open = local.manual_override ? local.manual_open : state->recommend_open_window;
    bool manual_request = false;
    control_state_set_alarm_source(CONTROL_ALARM_FUSION, state->alarm_enabled);

    if (command) {
        switch (command->type) {
        case CLOUD_COMMAND_WINDOW_OPEN:
            target_open = true;
            manual_request = true;
            control_state_set_manual(true, true);
            break;
        case CLOUD_COMMAND_WINDOW_CLOSE:
            target_open = false;
            manual_request = true;
            control_state_set_manual(true, false);
            break;
        case CLOUD_COMMAND_ALARM_ON:
            if (!s_actuator_ready) {
                return ESP_ERR_INVALID_STATE;
            }
            control_state_set_alarm_source(CONTROL_ALARM_COMMAND, true);
            break;
        case CLOUD_COMMAND_ALARM_OFF:
            if (!s_actuator_ready) {
                return ESP_ERR_INVALID_STATE;
            }
            control_state_set_alarm_source(CONTROL_ALARM_COMMAND, false);
            break;
        case CLOUD_COMMAND_LED_ON:
            return set_led(true);
        case CLOUD_COMMAND_LED_OFF:
            return set_led(false);
            break;
        case CLOUD_COMMAND_NONE:
            break;
        case CLOUD_COMMAND_UNKNOWN:
        default:
            return ESP_ERR_NOT_SUPPORTED;
        }
    }

    if (!s_actuator_ready) {
        return command ? ESP_ERR_INVALID_STATE : ESP_OK;
    }

    /* 仅自动联动开窗需要 3 秒预警音；手动/云端指令开窗立即执行 */
    if (!local.window_open && target_open && !local.manual_override && !manual_request) {
        beep_alarm_loop(3000);
    }

    esp_err_t err = set_window(target_open);
    actuator_refresh_alarm();
    return err;
}
