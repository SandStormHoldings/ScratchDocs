import datetime
from couchdbkit import *
from couchdbkit.designer import push
from docs import get_fns,initvars,get_task,parse_fn,read_journal
import config as cfg    
import sys
import json
initvars(cfg)

from couchdb import Task,init_conn

if __name__=='__main__':
    s,d = init_conn()

    tasks = Task.view('task/all')
    for t in tasks: 
        #get rid of old id tasks here
        if len(t._id)==32:
            print t._id
            t.delete()
            continue
        t.path = [int(tp) for tp in t.path]
        t.save()
