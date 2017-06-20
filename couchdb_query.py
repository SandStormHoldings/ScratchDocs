#!/usr/bin/env python
from __future__ import print_function
import datetime
from couchdbkit import *
from couchdbkit.designer import push
from docs import initvars
import config as cfg    
import sys
import json

# Wrap sys.stdout into a StreamWriter to allow writing unicode.
import codecs
import locale
sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout) 
# done

initvars(cfg)

from couchdb import *

if __name__=='__main__':
    s,d,p = init_conn()
    
    push_views(d)
    if len(sys.argv)<2:
        sys.exit(0)
    tid = sys.argv[1]
    
    t = get_task(tid)
    print('QUERIED TASK:')
    print(t._id,t.summary)

    tasks = get_children(tid)

    print(len(tasks),'CHILDREN')
    for t in tasks: 
        print(t.path,t._id,t.summary,','.join(t.tags))

    tasks = get_parents(tid)
    print(len(tasks),'PARENTS')
    for t in tasks:
        print(t.path,t._id,t.summary,','.join(t.tags))
    #print 'done'

    if len(sys.argv)>2:
        tag = sys.argv[2]
        tasks = get_by_tag(tag)
        print(len(tasks),'BY TAG %s'%tag)
        for t in tasks: print(t.path,t._id,t.summary,','.join(t.tags))
        
    if len(sys.argv)>3:
        rel = sys.argv[3]
        tasks = get_related(rel)
        print(len(tasks),'BY RELATED %s'%rel)
        for t in tasks: print(t.path,t._id,t.summary,t.assignee)
    if len(sys.argv)>4:
        st = sys.argv[4]
        tasks = get_by_status(st)
        print(len(tasks),'BY STATUS %s'%st)
        for t in tasks: print(t.path,t._id,t.summary,t.status)
    
