from deep_analyse import *

def get_max_drop_rate(expr):
    res = []
    for ana in analyser_iter(expr):
        try:
            drop_rate = ana.get_drop_rate()
            res.append(drop_rate)
        except:
            continue
    return max(res)

#gscc_web = '452' 
gscc_web = '449,452,455,458,461'
#gscc_ali = '363'
gscc_ali = '381,384,387,390,603'


print(get_max_drop_rate(gscc_web)*100 , get_max_drop_rate(gscc_ali)*100)