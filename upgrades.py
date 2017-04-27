#!/usr/bin/env python
from docs import *


def upgrade_meta():
    print 'upgrade meta'
    st,op = gso('find ./ -type f -name "meta.json"') ; assert st==0
    for fn in filter(lambda x: len(x),op.split('\n')):
        m = loadmeta(fn)
        touched=False
        if m.get('notify'):
            m['notifications']=[m['notify']]
            del m['notify']
            touched=True
            print fn
        if not m.get('notifications'): continue
        for n in m['notifications']:
            if 'how' not in n:
                n['how']=None
                touched=True
        if touched:
            savemeta(fn,m)


upgrade_meta()
