"""Compile and execute the actual controller budget function against a 64-bit oracle."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class BudgetTests(unittest.TestCase):
    def test_credit_debt_and_long_run_wrap(self):
        self.assertIsNotNone(shutil.which('gcc'))
        source=(ROOT/'ctrl/ctrl.c').read_text()
        function=re.search(r'static void update_reference_bytes\(.*?\n}\n',source,re.S).group(0)
        harness=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { uint32_t last_real_bytes, ref_bytes; int64_t budget_balance; double ref_rate; } dc_stats_t;
'''+function+r'''
int main(void) {
    dc_stats_t d={0}; uint64_t real=0,ref=0;
    for (int i=0;i<10000;i++) {
        uint32_t sent=(i%11==0)?0:25000; uint64_t duration=1000;
        d.ref_rate=3125000000.0; real+=sent; d.last_real_bytes=(uint32_t)real;
        if(ref>real) ref=real;
        if(sent) ref+=3125000;
        update_reference_bytes(&d,duration,sent);
        if(d.ref_bytes!=(uint32_t)ref || d.budget_balance!=(int64_t)ref-(int64_t)real) return 1;
    }
    // Real byte counter crosses 2^32; debt remains bounded and exact.
    d=(dc_stats_t){.last_real_bytes=0xfffffff0u,.ref_bytes=0xfffffff0u};
    real=ref=0xfffffff0u;
    for(int i=0;i<10000;i++) {
        uint32_t sent=(i%2)?9000:11000; d.ref_rate=10000000;
        real+=sent;d.last_real_bytes=(uint32_t)real;
        if(ref>real)ref=real;ref+=10000;
        update_reference_bytes(&d,1000,sent);
        if(d.ref_bytes!=(uint32_t)ref || d.budget_balance!=(int64_t)ref-(int64_t)real) return 2;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'budget.c'; exe=Path(td)/'budget';c.write_text(harness)
            subprocess.run(['gcc','-std=c11','-Wall','-Werror','-Wno-misleading-indentation',str(c),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__':unittest.main()
