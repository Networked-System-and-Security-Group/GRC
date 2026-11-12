#ifndef _GSCC_CONFIG_H
#define _GSCC_CONFIG_H
/* Tofino2 target: 1 = T2 (avoids Tofino1 pdfixed PD headers) */
#define __TOFINO_MODE__ 1
/* Symbols referenced by headers.h but never provided by the GRC repo */
#define EVENT_ID_MAX 256
#define PKTBUF_SIZE 2048
#endif
