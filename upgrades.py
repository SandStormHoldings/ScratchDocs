#!/usr/bin/env python
from __future__ import print_function
from docs import *


def upgrade_meta():
    print('upgrade meta')
    st,op = gso('find ./ -type f -name "meta.json"') ; assert st==0
    for fn in [x for x in op.split('\n') if len(x)]:
        m = loadmeta(fn)
        touched=False
        if m.get('notify'):
            m['notifications']=[m['notify']]
            del m['notify']
            touched=True
            print(fn)
        if not m.get('notifications'): continue
        for n in m['notifications']:
            if 'how' not in n:
                n['how']=None
                touched=True
        if touched:
            savemeta(fn,m)


upgrade_meta()
