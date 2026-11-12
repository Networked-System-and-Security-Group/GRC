/* Perftest startup gate. Records successful RTR/RTS transitions only; the
 * send/receive fast path is untouched. Both endpoints wait before first data.
 */
#define _GNU_SOURCE
#include <infiniband/verbs.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

struct pair { uint32_t local, remote; int rts; };
static struct pair pairs[64];
static int npairs, released;
static void fail(const char *s) { fprintf(stderr,"QP_GATE: %s\n",s); _exit(126); }

int ibv_modify_qp(struct ibv_qp *qp, struct ibv_qp_attr *attr, int mask) {
    static int (*real_modify)(struct ibv_qp *, struct ibv_qp_attr *, int);
    if (!real_modify) {
        *(void **)(&real_modify)=dlvsym(RTLD_NEXT,"ibv_modify_qp","IBVERBS_1.1");
        if (!real_modify) fail("cannot resolve ibv_modify_qp");
    }
    fprintf(stderr,"QP_GATE: qpn=%u state=%d mask=%x\n",qp->qp_num,attr->qp_state,mask);
    int rc=real_modify(qp,attr,mask);
    const char *dir=getenv("P4SORT_GATE_DIR"), *role=getenv("P4SORT_GATE_ROLE");
    const char *count=getenv("P4SORT_GATE_QPS");
    if (rc || !dir || !role || !count || released) return rc;
    if (strcmp(role,"client") && strcmp(role,"server")) fail("invalid role");
    int expected=atoi(count);
    if (expected<1 || expected>64) fail("unsupported QP count");
    if ((mask & IBV_QP_STATE) && attr->qp_state==IBV_QPS_RTR) {
        if (!(mask & IBV_QP_DEST_QPN) || npairs>=expected) fail("unexpected RTR transition");
        for (int i=0;i<npairs;i++) if(pairs[i].local==qp->qp_num) fail("duplicate RTR");
        pairs[npairs++]=(struct pair){qp->qp_num,attr->dest_qp_num,0};
    }
    int ready=0;
    if (!strcmp(role,"server") && (mask & IBV_QP_STATE) && attr->qp_state==IBV_QPS_RTR)
        ready=npairs; /* Unidirectional Write responder stays RTR. */
    if (!strcmp(role,"client") && (mask & IBV_QP_STATE) && attr->qp_state==IBV_QPS_RTS) {
        int found=0;
        for(int i=0;i<npairs;i++) {
            if(pairs[i].local==qp->qp_num) { if(pairs[i].rts) fail("duplicate RTS"); pairs[i].rts=1; found=1; }
            ready+=pairs[i].rts;
        }
        if(!found) fail("RTS without recorded RTR");
    }
    if(ready==expected) {
            char tmp[1024],path[1024],release[1024];
            if(snprintf(path,sizeof(path),"%s/%s-qp.json",dir,role)>=(int)sizeof(path) ||
               snprintf(tmp,sizeof(tmp),"%s.tmp",path)>=(int)sizeof(tmp) ||
               snprintf(release,sizeof(release),"%s/release",dir)>=(int)sizeof(release)) fail("path too long");
            FILE *f=fopen(tmp,"w"); if(!f) fail("cannot open QP evidence");
            fprintf(f,"{\"pid\":%d,\"role\":\"%s\",\"pairs\":[",getpid(),role);
            for(int i=0;i<npairs;i++) fprintf(f,"%s{\"local\":%u,\"remote\":%u}",i?",":"",pairs[i].local,pairs[i].remote);
            fprintf(f,"]}\n"); if(fclose(f) || rename(tmp,path)) fail("cannot publish QP evidence");
            for(int k=0;k<24000;k++) { if(access(release,F_OK)==0) { released=1; return rc; } usleep(10000); }
            fail("mapping release timed out; no test data sent");
    }
    return rc;
}
