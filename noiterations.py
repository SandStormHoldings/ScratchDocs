#!/usr/bin/env python

from docs import gso
import re
import sys
if 'phase1' in sys.argv:
    st,op = gso("find ./ -type d ! -wholename '*venv*' ! -wholename '*.git*' ! -wholename '*sd*'")
    assert st==0
    for fn in op.split('\n'):
        if fn=='./': continue
        spl = [p for p in fn.split('/') if p not in ['.','./']]
        for p in spl: assert re.compile('^\d+$').search(p) or p=='Backlog',"'%s' in %s"%(p,fn)
        if len(spl)<2: 
            continue
        itn = spl[0]
        tltid = spl[1]
        if len(spl)>2: continue
        #print spl
        cmd = 'git mv %(from)s %(to)s'%{'from':'/'.join([itn,tltid]),'to':'./'+tltid}
        print cmd
        st,op = gso(cmd) ; assert st==0,"returned %s\n%s"%(st,op)
        #print fn
    
if 'test' in sys.argv:
    st,op = gso("find ./ -type f -iname 'task.org'") ; assert st==0
    for fn in op.split('\n'):
        spl = fn.split('/')[1:]
        if spl[0]==spl[1]:
            print 'git mv %(fr)s %(to)s'%{'fr':spl[0]+'/'+spl[0]+'/*','to':spl[0]+'/'}

if 'iterations' in sys.argv:
    st,op = gso("find ./ -type f -iname 'iteration.org'"); assert st==0
    for fn in op.split('\n'):
        itn = fn.split('/')[1]
        #print itn,fn
        print 'git mv %s %s'%(fn,'iterations/'+itn+'.org')
