"""Measurement contract. Offset is ACK.PSN - resident probe PSN, modulo 24 bits.

It is a table-residency diagnostic, not a reconstruction of the original
AckReq/ACK pairing. In particular another QP can own the resident probe.
"""
PSN_MOD = 1 << 24
HALF = PSN_MOD // 2
SCHEMA = "gscc.ack-experiment.v1"
EMPTY_PSN = 0x7f000000


def offset(ack, stored):
    return ((ack - stored + HALF) % PSN_MOD) - HALF


def offset_bins(slots):
    # Exact zero, signed near intervals, signed tails, and half-space ambiguity.
    bins = [{"id": 0, "lo": 0, "hi": 0}]
    for sign in (1, -1):
        for k in range(64):
            lo, hi = k * slots + 1, (k + 1) * slots
            if sign < 0:
                lo, hi = -hi, -lo
            bins.append({"id": len(bins), "lo": lo, "hi": hi})
        lo, hi = 64 * slots + 1, HALF - 1
        if sign < 0:
            lo, hi = -hi, -lo
        bins.append({"id": len(bins), "lo": lo, "hi": hi, "tail": True})
    bins.append({"id": len(bins), "lo": -HALF, "hi": -HALF, "ambiguous": True})
    return bins


def classify_ranges(slots, window):
    """Disjoint unsigned-32 ranges for actual stored32 - ACK24.

    High bits are part of the key. No modulo histogram index is used for
    acceptance. Empty sentinel differences do not occur in these ranges.
    """
    result = []
    for b in offset_bins(slots):
        cuts = sorted({b["lo"], b["hi"] + 1} |
                      {x for x in (-window, window + 1) if b["lo"] < x <= b["hi"]})
        for lo, end in zip(cuts, cuts[1:]):
            hi = end - 1
            hit = int(-window <= lo and hi <= window)
            for wrap in (-PSN_MOD, 0, PSN_MOD):
                left = max(-PSN_MOD + 1, -hi + wrap)
                right = min(PSN_MOD - 1, -lo + wrap)
                if left > right:
                    continue
                for a, z in ((left, min(right, -1)), (max(left, 0), right)):
                    if a <= z:
                        result.append((a & 0xffffffff, z & 0xffffffff, b["id"], hit))
    return sorted(result)


def lookup(d, slots, window):
    for lo, hi, bucket, hit in classify_ranges(slots, window):
        if lo <= d <= hi:
            return bucket, bool(hit)
    return None, False


def split_range32(lo, hi):
    """Exact rectangles in high16 x low16; SDE supports range keys <=20 bits."""
    a, b = lo >> 16, hi >> 16
    if a == b:
        return [(a, a, lo & 65535, hi & 65535)]
    out = [(a, a, lo & 65535, 65535), (b, b, 0, hi & 65535)]
    if a + 1 <= b - 1:
        out.append((a + 1, b - 1, 0, 65535))
    return out
