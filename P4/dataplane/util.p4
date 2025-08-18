#ifndef _UTIL_
#define _UTIL_

parser gs_TofinoIngressParser(
        packet_in gs_pkt,
        out ingress_intrinsic_metadata_t gs_ig_intr_md) {
    state start {
        gs_pkt.extract(gs_ig_intr_md);
        transition select(gs_ig_intr_md.resubmit_flag) {
            1 : gs_parse_resubmit;
            0 : gs_parse_port_metadata;
        }
    }

    state gs_parse_resubmit {
        // rixin: 暂时不管resubmit
        transition reject;
    }

    state gs_parse_port_metadata {
        gs_pkt.advance(PORT_METADATA_SIZE);
        transition accept;
    }
}

parser gs_TofinoEgressParser(
        packet_in gs_pkt,
        out egress_intrinsic_metadata_t gs_eg_intr_md) {
    state start {
        gs_pkt.extract(gs_eg_intr_md);
        transition accept;
    }
}

// Skip egress
control gs_BypassEgress(inout ingress_intrinsic_metadata_for_tm_t gs_ig_tm_md) {

    action gs_set_bypass_egress() {
        gs_ig_tm_md.bypass_egress = 1w1;
    }

    table gs_bypass_egress {
        actions = {
            gs_set_bypass_egress();
        }
        const default_action = gs_set_bypass_egress;
    }

    apply {
        gs_bypass_egress.apply();
    }
}

// Empty egress parser/control blocks
parser gs_EmptyEgressParser(
        packet_in gs_pkt,
        out gs_empty_header_t gs_hdr,
        out gs_empty_metadata_t gs_eg_md,
        out egress_intrinsic_metadata_t gs_eg_intr_md) {
    state start {
        transition accept;
    }
}

control gs_EmptyEgressDeparser(
        packet_out gs_pkt,
        inout gs_empty_header_t gs_hdr,
        in gs_empty_metadata_t gs_eg_md,
        in egress_intrinsic_metadata_for_deparser_t gs_ig_intr_dprs_md) {
    apply {}
}

control gs_EmptyEgress(
        inout gs_empty_header_t gs_hdr,
        inout gs_empty_metadata_t gs_eg_md,
        in egress_intrinsic_metadata_t gs_eg_intr_md,
        in egress_intrinsic_metadata_from_parser_t gs_eg_intr_md_from_prsr,
        inout egress_intrinsic_metadata_for_deparser_t gs_ig_intr_dprs_md,
        inout egress_intrinsic_metadata_for_output_port_t gs_eg_intr_oport_md) {
    apply {}
}

#endif /* _UTIL */
