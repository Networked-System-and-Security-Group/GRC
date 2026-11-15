#ifndef PAPER_RATE_H
#define PAPER_RATE_H

#include <math.h>
#include <stdint.h>

#define PAPER_RTO_NS 67108864u
#define PAPER_MIN_BUCKETS 61u
#define PAPER_INV_DELTA 6291456.0 /* §IV-A: 6 MB, using the ns-3 reference unit */
#define PAPER_BETA 0.3
#define PAPER_RATE_FLOOR 1000.0

typedef struct {
    uint64_t second;
    double minimum_s;
} paper_min_bucket_t;

/* Minimum of populated one-second buckets over the last ~60 seconds. */
static double paper_base_rtt(paper_min_bucket_t *history, uint64_t now_us, double sample_s) {
    uint64_t second = now_us / 1000000;
    paper_min_bucket_t *b = &history[second % PAPER_MIN_BUCKETS];
    if (sample_s > 0 && (b->second != second || b->minimum_s == 0 || sample_s < b->minimum_s)) {
        b->second = second;
        b->minimum_s = sample_s;
    }
    double min = INFINITY;
    for (unsigned i = 0; i < PAPER_MIN_BUCKETS; i++) {
        if (history[i].minimum_s > 0 && second - history[i].second < PAPER_MIN_BUCKETS)
            min = fmin(min, history[i].minimum_s);
    }
    return isfinite(min) ? min : 0;
}

static uint32_t paper_rtt_floor(double estimate_s) {
    /* Discard sample < estimate - RTO; equality is accepted. */
    return (uint32_t)fmax(0, ceil(estimate_s * 1e9 - PAPER_RTO_NS));
}

static double paper_reference_rate(double ref, double base_rate, double real_rate,
                                   double rtt, double base_rtt, double epoch_s,
                                   double link_rate, int *direction, double *direction_s) {
    if (rtt > 0) {
        double qdelay = rtt - base_rtt;
        double target = qdelay > 0 ? PAPER_INV_DELTA / qdelay : INFINITY;
        int next_direction = target > ref ? 1 : -1;
        if (next_direction != *direction) *direction_s = 0;
        *direction = next_direction;
        *direction_s += epoch_s;
        double v = *direction_s >= 10 * base_rtt ? 4 : *direction_s >= 5 * base_rtt ? 2 : 1;
        double epochs_per_rtt = base_rtt / epoch_s;
        double step = v * PAPER_INV_DELTA / (epochs_per_rtt * base_rtt);
        if (next_direction == 1) {
            ref += step;
        } else {
            double beta_e = -expm1(log1p(-PAPER_BETA) / epochs_per_rtt);
            ref -= fmax(step, (ref - target) * beta_e);
        }
    } else {
        *direction = 0;
        *direction_s = 0;
    }
    double upper = fmax(base_rate, 1.2 * real_rate);
    if (ref > upper) ref = upper + 0.8 * (ref - upper);
    return fmin(link_rate, fmax(PAPER_RATE_FLOOR, ref));
}

#endif
