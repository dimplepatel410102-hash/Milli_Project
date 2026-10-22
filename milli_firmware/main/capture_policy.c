#include "capture_policy.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

void capture_policy_init(capture_policy_t *policy, const capture_policy_config_t *cfg)
{
    memset(policy, 0, sizeof(*policy));
    policy->cfg = *cfg;
    if (policy->cfg.confirm_frames == 0) {
        policy->cfg.confirm_frames = 1;
    }
    if (policy->cfg.absent_frames == 0) {
        policy->cfg.absent_frames = 1;
    }
}

bool capture_policy_on_frame(capture_policy_t *policy, int face_count, int64_t now_ms)
{
    if (face_count > 0) {
        policy->empty_streak = 0;
        if (policy->face_streak < UINT32_MAX) {
            policy->face_streak++;
        }
        if (!policy->present && policy->face_streak >= policy->cfg.confirm_frames) {
            policy->present = true;
            policy->presence_seq++;
            policy->captured_this_presence = false;
        }
    } else {
        policy->face_streak = 0;
        if (policy->empty_streak < UINT32_MAX) {
            policy->empty_streak++;
        }
        if (policy->present && policy->empty_streak >= policy->cfg.absent_frames) {
            policy->present = false;
            policy->captured_this_presence = false;
        }
        return false;
    }

    if (!policy->present || policy->upload_in_flight) {
        return false;
    }
    int64_t since_last = now_ms - policy->last_upload_ms;
    if (policy->has_uploaded && since_last < (int64_t)policy->cfg.min_interval_ms) {
        policy->suppressed++;
        return false;
    }
    if (policy->captured_this_presence) {
        if (policy->cfg.cooldown_ms == 0 || since_last < (int64_t)policy->cfg.cooldown_ms) {
            policy->suppressed++;
            return false;
        }
    }
    policy->upload_in_flight = true;
    policy->in_flight_presence = policy->presence_seq;
    return true;
}

void capture_policy_upload_done(capture_policy_t *policy, bool accepted, int64_t now_ms)
{
    policy->upload_in_flight = false;
    policy->has_uploaded = true;
    policy->last_upload_ms = now_ms;
    if (accepted && policy->present && policy->in_flight_presence == policy->presence_seq) {
        policy->captured_this_presence = true;
    }
}
