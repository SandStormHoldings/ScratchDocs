#!/usr/bin/env python
"""
associate existing tasks with other dependent tasks.
useful for classification purposes in an external tool
input arrives in the form of tab separated stdin rows containing dependence task ids and their classification.
argv[1] - parent task id to create dependent tasks under
argv[2] - position of dependence task id in stdin line.
argv[3] - position of classifier name for task in stdin line.
'print' in argv - print extracted values from stdin instead of acting upon them. 
"""
import sys,json
tlid='1626'
from couchdb import init_conn
import config as cfg
from docs import add_task,initvars,rewrite
initvars(cfg)


def trig(P,C,pid,dtid,cls):
    qtid = tlid+'/%'
    qry="select id,contents->>'summary' summary,contents->>'dependencies' deps from tasks where id like %s and contents->>'summary'=%s"
    args=(str(pid)+'%',cls)
    C.execute(qry,args)
    rt = C.fetchall()
    if not len(rt):
        user = 'tags_import'
        o_params={'summary':cls,
                  'creator':user,
                  'status':'TODO',
                  'informed':[],
                  'assignee':'',
                  'branches':[],
                  'links':[],
                  'unstructured':'',
    }
        rt = add_task(P,C,
                      parent=pid,
                      params=o_params,
                      tags=[],
                      user=user)
        tid = rt._id
        deps = []
        print(tid,'created')
    elif len(rt)==1:
        tid = rt[0]['id']
        deps = json.loads(rt[0]['deps'])
        #print(tid,'found')
    else:
        raise Exception('more than one result?')
    if dtid not in deps: deps.append(dtid)
    rewrite(P,C,tid,o_params={'dependencies':deps,
                              'cross_links':[],
                              'cross_links_raw':''})
if __name__=='__main__':
    P = init_conn()
    pid = sys.argv[1]
    with P as p:
        C = p.cursor()
        for row in sys.stdin:
            l = row.strip().split('\t')
            tid = l[int(sys.argv[2])]
            cls = l[int(sys.argv[3])]
            if 'print' in sys.argv[1:]:
                print(tid,cls)
                continue
            assert tid

            if cls:
                trig(P,C,pid,tid,cls)

        

    
