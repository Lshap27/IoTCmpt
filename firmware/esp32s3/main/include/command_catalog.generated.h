/* Generated from contracts/commands.json. Do not edit by hand. */
#pragma once

#define AIOT_PROTOCOL_VERSION "2.0"

#define AIOT_COMMAND_CATALOG(X) \
    X(CLOUD_COMMAND_WINDOW_OPEN, "window.open", true, "normal", "{\"type\":\"object\",\"additionalProperties\":false}", 15U) \
    X(CLOUD_COMMAND_WINDOW_CLOSE, "window.close", true, "normal", "{\"type\":\"object\",\"additionalProperties\":false}", 15U) \
    X(CLOUD_COMMAND_ALARM_ON, "alarm.on", false, "safety", "{\"type\":\"object\",\"additionalProperties\":false}", 13U) \
    X(CLOUD_COMMAND_ALARM_OFF, "alarm.off", false, "safety", "{\"type\":\"object\",\"additionalProperties\":false}", 13U) \
    X(CLOUD_COMMAND_LED_ON, "led.on", true, "normal", "{\"type\":\"object\",\"additionalProperties\":false}", 15U) \
    X(CLOUD_COMMAND_LED_OFF, "led.off", true, "normal", "{\"type\":\"object\",\"additionalProperties\":false}", 15U) \
    X(CLOUD_COMMAND_CONTROL_SET_PRIORITY, "control.set_priority", false, "administrative", "{\"type\":\"object\",\"properties\":{\"priority\":{\"enum\":[\"manual_first\",\"auto_first\"]}},\"required\":[\"priority\"],\"additionalProperties\":false}", 13U) \
    X(CLOUD_COMMAND_CONTROL_RESUME_AUTO, "control.resume_auto", false, "administrative", "{\"type\":\"object\",\"additionalProperties\":false}", 13U) \
    X(CLOUD_COMMAND_ALARM_SILENCE, "alarm.silence", false, "safety", "{\"type\":\"object\",\"properties\":{\"duration_seconds\":{\"type\":\"integer\",\"minimum\":10,\"maximum\":600}},\"additionalProperties\":false}", 13U) \
    X(CLOUD_COMMAND_VOICE_SPEAK, "voice.speak", true, "normal", "{\"type\":\"object\",\"properties\":{\"gb2312_base64\":{\"type\":\"string\",\"minLength\":4,\"maxLength\":320}},\"required\":[\"gb2312_base64\"],\"additionalProperties\":false}", 15U) \
    X(CLOUD_COMMAND_DISPLAY_MESSAGE, "display.message", true, "normal", "{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120}},\"required\":[\"text\"],\"additionalProperties\":false}", 15U)
