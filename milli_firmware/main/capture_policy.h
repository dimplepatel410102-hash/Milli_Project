#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t confirm_frames;    /* consecutive face frames before a person counts as present */
    uint32_t absent_frames;     /* consecutive empty frames before the person counts as gone */
    uint32_t cooldown_ms;       /* re-upload while still present after this long; 0 = never */
    uint32_t min_interval_ms;   /* hard floor between any two uploads */
} capture_policy_config_t;

typedef struct {
    capture_policy_config_t cfg;
    bool present;
    bool captured_this_presence;
    bool upload_in_flight;
    bool has_uploaded;
    uint32_t presence_seq;
    uint32_t in_flight_presence;
    uint32_t face_streak;
    uint32_t empty_streak;
    int64_t last_upload_ms;
    uint32_t suppressed;
} capture_policy_t;

void capture_policy_init(capture_policy_t *policy, const capture_policy_config_t *cfg);

/**
 * Feed one detection result. Returns true if this frame (which contains a face) should be uploaded.
 * Once true is returned, no further uploads are requested until capture_policy_upload_done() is called.
 */
bool capture_policy_on_frame(capture_policy_t *policy, int face_count, int64_t now_ms);

/** Report the upload outcome; a failed upload lets the same presence be captured again. */
void capture_policy_upload_done(capture_policy_t *policy, bool accepted, int64_t now_ms);

#ifdef __cplusplus
}
#endif
