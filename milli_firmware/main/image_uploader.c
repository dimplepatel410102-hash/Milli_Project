#include "image_uploader.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "uploader";

#define URL_MAX 192
#define ID_MAX 65
#define KEY_MAX 257
#define RESPONSE_MAX 4096
#define MAX_BACKOFF_MS 10000

typedef struct {
    char capture_url[URL_MAX];
    char register_url[URL_MAX];
    char device_id[ID_MAX];
    char api_key[KEY_MAX];
    int timeout_ms;
    int max_attempts;
    int backoff_ms;
    bool configured;
} uploader_state_t;

static uploader_state_t s_state;

static struct {
    char firmware_version[33];
    char hardware_model[65];
    char camera_model[65];
    bool has_camera_model;
    bool on_device_face_detection;
    bool valid;
} s_last_registration;

static bool build_url(char *out, size_t out_len, const char *base, const char *path)
{
    size_t base_len = strlen(base);
    while (base_len > 0 && base[base_len - 1] == '/') {
        base_len--;
    }
    int n = snprintf(out, out_len, "%.*s%s%s", (int)base_len, base, path[0] == '/' ? "" : "/", path);
    return n > 0 && (size_t)n < out_len;
}

static bool is_valid_device_id(const char *id)
{
    size_t len = strlen(id);
    if (len == 0 || len > 64) {
        return false;
    }
    for (size_t i = 0; i < len; i++) {
        char c = id[i];
        bool alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (!alnum && !(i > 0 && (c == '-' || c == '_'))) {
            return false;
        }
    }
    return true;
}

esp_err_t image_uploader_init(const image_uploader_config_t *config)
{
    memset(&s_state, 0, sizeof(s_state));
    bool ok = true;
    if (config->server_url == NULL || (strncmp(config->server_url, "http://", 7) != 0 &&
                                       strncmp(config->server_url, "https://", 8) != 0)) {
        ESP_LOGE(TAG, "MILLI_SERVER_URL must start with http:// or https://");
        ok = false;
    }
    if (config->device_id == NULL || !is_valid_device_id(config->device_id)) {
        ESP_LOGE(TAG, "MILLI_DEVICE_ID is missing or invalid (letters, digits, '-', '_'; max 64)");
        ok = false;
    }
    if (config->api_key == NULL || config->api_key[0] == '\0' || strlen(config->api_key) >= KEY_MAX) {
        ESP_LOGE(TAG, "MILLI_DEVICE_API_KEY is missing or too long");
        ok = false;
    }
    if (!ok) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!build_url(s_state.capture_url, URL_MAX, config->server_url, config->capture_endpoint) ||
        !build_url(s_state.register_url, URL_MAX, config->server_url, config->register_endpoint)) {
        ESP_LOGE(TAG, "server URL plus endpoint is longer than %d characters", URL_MAX - 1);
        return ESP_ERR_INVALID_ARG;
    }
    strlcpy(s_state.device_id, config->device_id, sizeof(s_state.device_id));
    strlcpy(s_state.api_key, config->api_key, sizeof(s_state.api_key));
    s_state.timeout_ms = config->timeout_ms;
    s_state.max_attempts = config->max_attempts < 1 ? 1 : config->max_attempts;
    s_state.backoff_ms = config->backoff_ms;
    s_state.configured = true;

    if (strncmp(s_state.capture_url, "http://", 7) == 0) {
        ESP_LOGW(TAG, "using plain HTTP: the API key is sent unencrypted (development only)");
    }
    ESP_LOGI(TAG, "capture URL %s, device %s", s_state.capture_url, s_state.device_id);
    return ESP_OK;
}

bool image_uploader_is_configured(void)
{
    return s_state.configured;
}

static void set_error(upload_result_t *result, const char *code)
{
    strlcpy(result->error_code, code, sizeof(result->error_code));
}

/* One HTTP POST. Returns ESP_OK if an HTTP response was received (any status). */
static esp_err_t post_once(const char *url, const char *content_type, const uint8_t *body, size_t body_len,
                           const char *const *extra_headers, int *status, char *response, size_t response_len)
{
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = s_state.timeout_ms,
        .disable_auto_redirect = true,
        .buffer_size = 1024,
        .buffer_size_tx = 1024,
    };
    if (strncmp(url, "https://", 8) == 0) {
        cfg.crt_bundle_attach = esp_crt_bundle_attach;
    }
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        return ESP_ERR_NO_MEM;
    }
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_header(client, "X-Device-ID", s_state.device_id);
    esp_http_client_set_header(client, "X-Device-Key", s_state.api_key);
    for (size_t i = 0; extra_headers != NULL && extra_headers[i] != NULL; i += 2) {
        esp_http_client_set_header(client, extra_headers[i], extra_headers[i + 1]);
    }

    esp_err_t err = esp_http_client_open(client, (int)body_len);
    if (err == ESP_OK) {
        size_t sent = 0;
        while (sent < body_len) {
            int n = esp_http_client_write(client, (const char *)body + sent, (int)(body_len - sent));
            if (n <= 0) {
                err = ESP_FAIL;
                break;
            }
            sent += (size_t)n;
        }
    }
    if (err == ESP_OK && esp_http_client_fetch_headers(client) < 0) {
        err = ESP_FAIL;
    }
    if (err == ESP_OK) {
        *status = esp_http_client_get_status_code(client);
        int total = 0;
        while (total < (int)response_len - 1) {
            int n = esp_http_client_read(client, response + total, (int)response_len - 1 - total);
            if (n <= 0) {
                break;
            }
            total += n;
        }
        response[total] = '\0';
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}

static void parse_error(const char *response, upload_result_t *result)
{
    cJSON *root = cJSON_Parse(response);
    const cJSON *error = root ? cJSON_GetObjectItemCaseSensitive(root, "error") : NULL;
    const cJSON *code = error ? cJSON_GetObjectItemCaseSensitive(error, "code") : NULL;
    const cJSON *message = error ? cJSON_GetObjectItemCaseSensitive(error, "message") : NULL;
    if (cJSON_IsString(code)) {
        set_error(result, code->valuestring);
    }
    if (cJSON_IsString(message)) {
        ESP_LOGW(TAG, "server error %s: %s", result->error_code, message->valuestring);
    }
    cJSON_Delete(root);
}

static const char *json_string_or(const cJSON *object, const char *key, const char *fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(item) ? item->valuestring : fallback;
}

static void log_recognition(const cJSON *recognition)
{
    if (!cJSON_IsObject(recognition)) {
        return;
    }
    const char *status = json_string_or(recognition, "status", "?");
    const cJSON *similarity = cJSON_GetObjectItemCaseSensitive(recognition, "similarity");
    double sim = cJSON_IsNumber(similarity) ? similarity->valuedouble : -1.0;
    if (strcmp(status, "recognized") == 0) {
        ESP_LOGI(TAG, "RECOGNIZED: %s (employee %s, similarity %.2f)", json_string_or(recognition, "label", "?"),
                 json_string_or(recognition, "employee_id", "?"), sim);
    } else if (strcmp(status, "unknown") == 0) {
        ESP_LOGI(TAG, "RECOGNITION: Unknown person (best similarity %.2f)", sim);
    } else {
        ESP_LOGI(TAG, "recognition %s: %s", status, json_string_or(recognition, "message", ""));
    }
}

static bool parse_capture_accepted(const char *response, upload_result_t *result)
{
    cJSON *root = cJSON_Parse(response);
    if (root == NULL) {
        return false;
    }
    const cJSON *status = cJSON_GetObjectItemCaseSensitive(root, "status");
    const cJSON *received = cJSON_GetObjectItemCaseSensitive(root, "image_received");
    const cJSON *capture_id = cJSON_GetObjectItemCaseSensitive(root, "capture_id");
    const cJSON *image = cJSON_GetObjectItemCaseSensitive(root, "image");
    const cJSON *format = image ? cJSON_GetObjectItemCaseSensitive(image, "format") : NULL;
    const cJSON *detection = cJSON_GetObjectItemCaseSensitive(root, "server_detection");
    const cJSON *face_count = detection ? cJSON_GetObjectItemCaseSensitive(detection, "face_count") : NULL;

    bool accepted = cJSON_IsString(status) && strcmp(status->valuestring, "received") == 0 &&
                    cJSON_IsTrue(received);
    if (accepted && cJSON_IsString(capture_id)) {
        strlcpy(result->capture_id, capture_id->valuestring, sizeof(result->capture_id));
        if (cJSON_IsNumber(face_count)) {
            ESP_LOGI(TAG, "server confirmed capture_id=%s format=%s, server found %d face(s)", result->capture_id,
                     cJSON_IsString(format) ? format->valuestring : "?", face_count->valueint);
        } else {
            ESP_LOGI(TAG, "server confirmed capture_id=%s format=%s, server face detection not run",
                     result->capture_id, cJSON_IsString(format) ? format->valuestring : "?");
        }
        log_recognition(cJSON_GetObjectItemCaseSensitive(root, "recognition"));
    }
    cJSON_Delete(root);
    return accepted;
}

static bool is_transient(esp_err_t transport_err, int status)
{
    return transport_err != ESP_OK || status >= 500 || status == 408 || status == 429;
}

esp_err_t image_uploader_register(const device_registration_t *device, upload_result_t *result)
{
    memset(result, 0, sizeof(*result));
    if (!s_state.configured) {
        set_error(result, "not_configured");
        return ESP_ERR_INVALID_STATE;
    }

    if (device->firmware_version != s_last_registration.firmware_version) {
        strlcpy(s_last_registration.firmware_version, device->firmware_version,
                sizeof(s_last_registration.firmware_version));
        strlcpy(s_last_registration.hardware_model, device->hardware_model,
                sizeof(s_last_registration.hardware_model));
        s_last_registration.has_camera_model = device->camera_model != NULL;
        strlcpy(s_last_registration.camera_model, device->camera_model ? device->camera_model : "",
                sizeof(s_last_registration.camera_model));
        s_last_registration.on_device_face_detection = device->on_device_face_detection;
        s_last_registration.valid = true;
    }

    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "firmware_version", device->firmware_version);
    cJSON_AddStringToObject(body, "hardware_model", device->hardware_model);
    if (device->camera_model != NULL) {
        cJSON_AddStringToObject(body, "camera_model", device->camera_model);
    }
    cJSON_AddBoolToObject(body, "on_device_face_detection", device->on_device_face_detection);
    char *json = cJSON_PrintUnformatted(body);
    cJSON_Delete(body);
    if (json == NULL) {
        return ESP_ERR_NO_MEM;
    }

    char *response = calloc(1, RESPONSE_MAX);
    if (response == NULL) {
        cJSON_free(json);
        return ESP_ERR_NO_MEM;
    }
    result->attempts = 1;
    esp_err_t err = post_once(s_state.register_url, "application/json", (const uint8_t *)json, strlen(json),
                              NULL, &result->http_status, response, RESPONSE_MAX);
    cJSON_free(json);

    if (err != ESP_OK) {
        set_error(result, "network_error");
        ESP_LOGW(TAG, "registration failed: no response from %s (%s)", s_state.register_url, esp_err_to_name(err));
    } else if (result->http_status == 200) {
        result->accepted = true;
        ESP_LOGI(TAG, "device %s registered with backend (HTTP 200)", s_state.device_id);
    } else {
        parse_error(response, result);
        ESP_LOGE(TAG, "registration rejected: HTTP %d %s", result->http_status, result->error_code);
        if (result->http_status == 401) {
            ESP_LOGE(TAG, "check MILLI_DEVICE_ID / MILLI_DEVICE_API_KEY against the backend's credentials");
        }
    }
    free(response);
    return result->accepted ? ESP_OK : ESP_FAIL;
}

esp_err_t image_uploader_upload(const image_upload_t *upload, upload_result_t *result)
{
    memset(result, 0, sizeof(*result));
    if (!s_state.configured) {
        set_error(result, "not_configured");
        return ESP_ERR_INVALID_STATE;
    }

    char captured_at[32] = "";
    char face_count[12] = "";
    const char *headers[16];
    size_t h = 0;
    if (upload->device_capture_id != NULL) {
        headers[h++] = "X-Capture-Id";
        headers[h++] = upload->device_capture_id;
    }
    if (upload->captured_at > 0) {
        struct tm tm_utc;
        gmtime_r(&upload->captured_at, &tm_utc);
        strftime(captured_at, sizeof(captured_at), "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
        headers[h++] = "X-Captured-At";
        headers[h++] = captured_at;
    }
    if (upload->face_count >= 0) {
        snprintf(face_count, sizeof(face_count), "%d", upload->face_count);
        headers[h++] = "X-Device-Face-Detected";
        headers[h++] = upload->face_count > 0 ? "true" : "false";
        headers[h++] = "X-Device-Face-Count";
        headers[h++] = face_count;
        if (upload->detector != NULL) {
            headers[h++] = "X-Device-Detector";
            headers[h++] = upload->detector;
        }
    }
    headers[h] = NULL;

    char *response = calloc(1, RESPONSE_MAX);
    if (response == NULL) {
        set_error(result, "out_of_memory");
        return ESP_ERR_NO_MEM;
    }

    bool reregistered = false;
    int delay_ms = s_state.backoff_ms;
    for (int attempt = 1; attempt <= s_state.max_attempts; attempt++) {
        result->attempts = attempt;
        result->http_status = 0;
        result->error_code[0] = '\0';
        int64_t start = esp_timer_get_time();
        esp_err_t err = post_once(s_state.capture_url, upload->content_type, upload->data, upload->len, headers,
                                  &result->http_status, response, RESPONSE_MAX);
        int elapsed_ms = (int)((esp_timer_get_time() - start) / 1000);

        if (err == ESP_OK && result->http_status == 200) {
            if (parse_capture_accepted(response, result)) {
                result->accepted = true;
                ESP_LOGI(TAG, "upload accepted: %u bytes, HTTP 200, %d ms, attempt %d", (unsigned)upload->len,
                         elapsed_ms, attempt);
                break;
            }
            set_error(result, "unexpected_response");
            ESP_LOGE(TAG, "HTTP 200 but the response did not confirm receipt; not counting as success");
            break;
        }

        if (err != ESP_OK) {
            set_error(result, "network_error");
            ESP_LOGW(TAG, "attempt %d/%d: no response (%s) after %d ms", attempt, s_state.max_attempts,
                     esp_err_to_name(err), elapsed_ms);
        } else {
            parse_error(response, result);
            ESP_LOGW(TAG, "attempt %d/%d: HTTP %d %s", attempt, s_state.max_attempts, result->http_status,
                     result->error_code);
        }

        if (err == ESP_OK && result->http_status == 403 && strcmp(result->error_code, "device_not_registered") == 0 &&
            !reregistered && s_last_registration.valid) {
            reregistered = true;
            ESP_LOGI(TAG, "backend requires registration; registering and retrying once");
            upload_result_t reg;
            const device_registration_t device = {
                .firmware_version = s_last_registration.firmware_version,
                .hardware_model = s_last_registration.hardware_model,
                .camera_model = s_last_registration.has_camera_model ? s_last_registration.camera_model : NULL,
                .on_device_face_detection = s_last_registration.on_device_face_detection,
            };
            if (image_uploader_register(&device, &reg) == ESP_OK) {
                attempt--;
                continue;
            }
            break;
        }
        if (!is_transient(err, result->http_status)) {
            if (result->http_status == 401) {
                ESP_LOGE(TAG, "credentials rejected; not retrying. Check MILLI_DEVICE_ID / MILLI_DEVICE_API_KEY");
            }
            break;
        }
        if (attempt < s_state.max_attempts) {
            ESP_LOGI(TAG, "retrying in %d ms", delay_ms);
            vTaskDelay(pdMS_TO_TICKS(delay_ms));
            delay_ms = delay_ms * 2 > MAX_BACKOFF_MS ? MAX_BACKOFF_MS : delay_ms * 2;
        }
    }

    free(response);
    if (!result->accepted) {
        ESP_LOGE(TAG, "upload NOT accepted after %d attempt(s): HTTP %d %s", result->attempts, result->http_status,
                 result->error_code);
    }
    return result->accepted ? ESP_OK : ESP_FAIL;
}
