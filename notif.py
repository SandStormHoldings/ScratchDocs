from __future__ import print_function
from builtins import range
#!/usr/bin/env python

#from deepdiff import DeepDiff
import jsonpatch
import json
import re
import sys
from collections import defaultdict
from noodles.utils.datahandler import datahandler

vers={}

lstre = re.compile('^/(cross_links|branches|tags|informed|dependencies)')
urlre = re.compile('http(|s)\:\/\/([^\/]+)/([^ ]*)',re.I)
jenkre = re.compile('job/([^/]+)/([^ ]+)')
def jenkshorten(sval):
    while True:
        urlres = jenkre.search(sval)
        if not urlres: break
        repl = urlres.group(2)
        sval = sval.replace(urlres.group(0),repl)
    return sval

def urlshorten(sval,path=False):
    while True and sval:
        urlres = urlre.search(sval)
        if not urlres: break
        if path and jenkre.search(urlres.group(3)):
            repl = urlres.group(2)+'/'+jenkshorten(urlres.group(3))
        else:
            repl = urlres.group(2)
        sval = sval.replace(urlres.group(0),repl)
    return sval

def shorten(value,maxlen=30):
    sval = value
    #raise Exception(value)
    sval = urlshorten(sval)

    for sep in ['** Unstructured','** Details','** Email contents']: sval = sval and sval.replace(sep,'') or ''
    for sep in ['\n','\r']: sval = sval.replace(sep," ")
    while "  " in sval: sval = sval.replace("  "," ")
    sval = sval.strip()
    sval = len(sval)<maxlen and sval or sval[0:maxlen]+'..'

    return sval

def parse_diff(jps,o1,o2,maxlen,v1rev,v2rev,supress=False):
    schanges=[] ; lchanges=[] ; cnt=0
    new_task=False
    for jp in jps:
        cnt+=1
        try:
            op = jp['op']
            if op=='remove':
                path=jp['path']
                value=None
                fr=None
                assert len(list(jp.keys()))==2
                opi='-='
            elif op in ['add','replace']:
                if op=='add': opi='+='
                else: opi='->'
                path = jp['path'] ; 
                value = jp['value'] ; 
                fr=None
                assert len(list(jp.keys()))==3
            elif op in ['move']:
                path=jp['path']
                fr = jp['from']
                value = jp['value']
            else:
                raise Exception('what is op %s'%op,jp)
        except KeyError:
            sys.stderr.write(" ".join(['KeyError',jp]))
            raise
        except Exception as e:
            raise
        spl = path.split('/')
        fn = path.replace('/','.')[1:]
        fnp = fn.split('.')[0]



        if op=='add' and value==None: continue
        if path in ['/external_thread_id','/created_at','/path','/cross_links_raw']: continue
        #karma is a special case
        if path in ['/branches','/journal','/links'] and op=='add' and value==[]:
            continue
        # this is a little digest we put aside inside the json, it is not a source of truth
        if path.startswith('/journal_digest'):
            continue
        if path=='/karma' and op=='add':
            chng=None
            for dt,kv in list(value.items()):
                trcv=defaultdict(int)
                for giver,krcvs in list(kv.items()):
                    for rcv,pts in list(krcvs.items()):
                        trcv[rcv]+=pts
                chng = ",".join(["%s+=%s"%(k,v) for k,v in list(trcv.items())])
            if not chng: continue
            lchange='karma(%s)'%chng

        elif path in ['/_id'] and op=='add':
            lchange='tid=%s'%value
            new_task=True
        elif path.startswith('/karma/') and op=='add':
            lchange='karma(%s+=%s)'%(path.split('/')[-1],value)


        #journal is a special case
        elif path.startswith('/journal') and op=='add' and path!='/journal_digest':
            if type(value)==list:
                vlist = value
            else:
                vlist = [value]
            cont=''
            for value in vlist:
                creators=[]
                if not len(value['content'].strip()):
                    cont+=" "+(','.join(['%s=%s'%(k,v) for k,v in list(value['attrs'].items())]))
                else:
                    cont+=" "+(shorten(value['content'],maxlen))
                if value['creator'] not in creators: creators.append(value['creator'])
            lchange='journal+=%s(%s)'%(cont,",".join(set(creators)))

        elif path.startswith('/links/') and (op in ['add'] or (op=='replace' and len(spl)==3)):
            if op=='add': lval=(urlshorten(value['url'],True),value['anchor'])
            elif op=='replace': lval=(urlshorten(value['url'],True),value['anchor'])
            lchange='links+=%s(%s)'%lval
        elif path in ['/links'] and op=='add':
            lval = (urlshorten(value[0]['url']),value[0]['anchor'])
            lchange='links+=%s(%s)'%lval
        elif path.startswith('/links/') and op in ['replace'] and len(spl)==4:
            try:
                lkey = int(spl[2])
                lfld = spl[3]
            except IndexError:
                print(jp)
                raise 
            except Exception as e:
                raise
            if lfld=='url': lidx='anchor'
            elif lfld=='anchor': lidx='url'
            else: raise Exception('unknown lfld %s'%lfld)
            lchange='links(%s)=%s'%(o1['links'][lkey][lidx],value)
        elif path.startswith('/links/') and op=='remove':
            lkey = int(spl[2])
            try:
                l = o2['links'][lkey-1]
            except IndexError:
                raise
            lchange='links-=%s(%s)'%(l['anchor'],urlshorten(l['url'],True))
        #appending/replace lists
        elif lstre.search(path) and op in ['add','replace']:
            lchange='%s%s%s'%(fnp,opi,value)
        elif path in ['/tags','/informed'] and op=='add':
            lchange='%s=%s'%(fn,",".join(value))
        elif path in ['/detail','/points'] and op=='remove':
            continue
        #skip moving of elements in std lists
        elif path in '/id':
            continue
        elif lstre.search(path) and op=='move':
            continue
        #initial assigning
        elif fn in ['unstructured','content','assignee','summary','status','handled_by','creator']:
            sval = shorten(value,maxlen)
            lchange='%s=%s'%(fn,sval)

        #initial appending of cross links
        elif path=='/cross_links' and op=='add':
            lchange='cross_links=%s'%','.join(value)
        elif path=='/dependencies' and op=='add':
            lchange='dependencies=%s'%','.join(value)
        elif re.compile('/journal/.*/attrs/work estimate$').search(path) and op=='replace':
            lchange='work_estimate=%s'%value
        #removal
        elif lstre.search(path) and op=='remove':
            tkey = spl[1]
            tidx = int(spl[2])
            try:
                tval = o1[tkey][tidx] #raise Exception(o1[tkey][tidx])
            except IndexError:
                print("cannot find",tkey,tidx,o2[tkey])
                raise
            except Exception as e:
                raise
            lchange='%s-=%s'%(fn,tval)
        elif supress:
            lchange='(unparsed)'+json.dumps(jp)
        else:
            raise Exception(fn,jp,v1rev,v2rev)
        lchanges.append(lchange)
        
    return cnt,list(set(lchanges)),new_task

def clean(o):
    for fn in ['notifications','orig_subj','external_msg_id','external_thread_id','external_id']:
        if fn in o: del o[fn]
    if '_rev' in o: del o['_rev']    
    for je in o.get('journal',[]):
        if 'created_at' in je:
            del je['created_at']


def parse(C,ts,rev=None,supress=False,limit=None):
    print('parse(%s,%s)'%([t._id for t in ts],rev))
    from couchdb import Task,get_children
    from pg import get_revisions
    rt=[]
    for t in ts:
        doc = get_revisions(C,t._id,limit=limit)
        revs = list(doc.keys())
        revs.reverse()
        if rev:
            rs = rev.split('_')
            try:
                lower = [r for r in revs if r.startswith(rs[0])]
                upper = [r for r in revs if r.startswith(rs[1])]
                assert len(lower)==1 and len(upper)==1,"could not find %s in %s"%(rs,revs)
                upper = upper[0]
                lower = lower[0]
            except IndexError:
                print('cannot find shit in revs',len(revs))
                raise

            revs = [lower,upper]
        for i in range(0,len(revs)-1):
            v1rev = revs[i]
            v2rev = revs[i+1]
            try:
                v1 = doc[v1rev]
                v2 = doc[v2rev]
            except:
                raise
                print(t._id,v1rev,v2rev,json.dumps(['NOTFOUNDERR']))
                continue
            j1 = v1['contents']
            j2 = v2['contents']
            clean(j1) ; clean(j2)
            try:
                jps = jsonpatch.JsonPatch.from_diff(j1,j2)
            except:
                print(t._id,v1rev,v2rev,json.dumps(['JSONPATCHERR']))
                continue
            if jps:
                try:
                    lcnt,lchanges,nt = parse_diff(jps,j1,j2,maxlen=30,v1rev=v1rev,v2rev=v2rev,supress=supress)
                    scnt,schanges,nt = parse_diff(jps,j1,j2,maxlen=10,v1rev=v1rev,v2rev=v2rev,supress=supress)
                    rt.append({'tid':t._id,
                               'lchanges_cnt':lcnt,
                               'lchanges':lchanges,
                               'schanges_cnt':scnt,
                               'schanges':schanges,
                               'nt':nt,
                               'v1rev':v1rev,
                               'v2rev':v2rev,
                               'changed_at':v2['changed_at'],
                               'changed_by':v2['changed_by'],
                               'jp':jps})
                except:
                    raise
                    print(t._id,v1rev,v2rev,json.dumps(['PARSEDIFFERR']))
                    rt.append({'tid':t._id,
                               'cnt':cnt,
                               'lchanges':json.dumps(['PARSEDIFFERR']),
                               'nt':nt,
                               'v1rev':v1rev,
                               'v2rev':v2rev,
                               'changed_at':v2['changed_at'],
                               'changed_by':v2['changed_by'],
                               'jp':jps})
                    
                    continue
                print(t._id,v1rev,v2rev,json.dumps(['OK',lchanges,schanges]))
        return rt

# expected usage in order to test how notifications behave:
# 1. parse all revisions into an intermediate results file
# sd/notif.py parse | pv -s 10574005 > notifications-5.json
# 2. test the results for indicators such as length
# grep -v NOTFOUND notifications-5.json | grep '"OK"' | sd/notif.py test | grep -v  _OK | sort -k5n

def get_pending_notifications(C,tid=None):
    print('get_pending_notifications(%s)'%tid)
    qry="select * from task_history_notifications where notified_at is null"
    args=[]
    if tid:
        qry+=" and  id=%s"
        args.append(tid)
    C.execute(qry,args)
    return C.fetchall()

def notification_logic(P,C,tid,supress,notify):
    from couchdb import Task
    from pg import get_children,revfmt

    pns = get_pending_notifications(C,tid)
    print('got',len(pns),'pending notifications.')
    for pn in pns:
        frev = revfmt(pn['sys_period'].lower,pn['sys_period'].upper)
        print('walking pending notification',frev)
        t = Task.get(C,pn['id'])
        notifs = parse(C,[t],rev=frev,supress=supress)
        print('walking',len(notifs),'notifs')
        if notify:
            done = False
            for nt in notifs:
                done = t._notify(P,C,user='notify-trigger',lc=nt)
                print('done=',done)

            print('inserting notification confirmation')
            qry = "insert into task_notifications (task_id,sys_period,created_at,details) values(%s,%s,now(),%s)"
            args = (t._id,pn['sys_period'],json.dumps(notifs,default=datahandler))
            C.execute(qry,args)
            P.commit()
    
def main(C):
    kwargs=dict([a.split('=') for a in sys.argv[1:] if '=' in a])
    flags = list(set([a for a in sys.argv[1:] if '=' not in a]))
    notification_logic(P,C,
                       tid=kwargs.get('tid'),
                       supress='supress' in flags,
                       notify='notify' in flags
    )


if __name__=='__main__':
    from docs import initvars,P
    import config as cfg
    initvars(cfg)
    with P as p:
        C = p.cursor()
        main(C)
