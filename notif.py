from __future__ import print_function
from builtins import range
#!/usr/bin/env python

#from deepdiff import DeepDiff
import jsonpatch
import json
import re
import sys
from collections import defaultdict

vers={}

lstre = re.compile('^/(cross_links|branches|tags|informed)')
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
    while True:
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

    for sep in ['** Unstructured','** Details','** Email contents']: sval = sval.replace(sep,'')
    for sep in ['\n','\r']: sval = sval.replace(sep," ")
    while "  " in sval: sval = sval.replace("  "," ")
    sval = sval.strip()
    sval = len(sval)<maxlen and sval or sval[0:maxlen]+'..'

    return sval

def parse_diff(jps,o1,o2,maxlen,v1rev,v2rev):
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
        elif path.startswith('/journal') and op=='add':
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
        #skip moving of elements in std lists
        elif lstre.search(path) and op=='move':
            continue
        #initial assigning
        elif fn in ['unstructured','content','assignee','summary','status','handled_by','creator']:
            sval = shorten(value,maxlen)
            lchange='%s=%s'%(fn,sval)

        #initial appending of cross links
        elif path=='/cross_links' and op=='add':
            lchange='cross_links=%s'%','.join(value)

        #removal
        elif lstre.search(path) and op=='remove':
            tkey = spl[1]
            tidx = int(spl[2])
            try:
                tval=(o2[tkey][tidx-1])
            except IndexError:
                sys.stderr.write(" ".join(["cannot find ",tkey,tidx,o2[tkey]]))
                raise
            except Exception as e:
                raise
            lchange='%s-=%s'%(fn,tval)
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


def parse(C,ts,rev=None):
    from couchdb import Task,get_children
    from pg import get_revisions
    for t in ts:
        doc = get_revisions(C,t._id)
        revs = list(doc.keys())
        #revs.reverse()
        for i in range(0,len(revs)-1):
            v1rev = revs[i]
            v2rev = revs[i+1]
            if rev and v1rev!=rev: continue
            try:
                v1 = doc[v1rev]
                v2 = doc[v2rev]
            except: #ResourceNotFound:
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
                    cnt,lchanges = parse_diff(jps,j2,j1,maxlen=30,v1rev=v2rev,v2rev=v1rev)
                    cnt,schanges = parse_diff(jps,j2,j1,maxlen=10,v1rev=v2rev,v2rev=v1rev)
                except:
                    raise
                    print(t._id,v1rev,v2rev,json.dumps(['PARSEDIFFERR']))
                    continue
                print(t._id,v1rev,v2rev,json.dumps(['OK',lchanges,schanges]))


# expected usage in order to test how notifications behave:
# 1. parse all revisions into an intermediate results file
# sd/notif.py parse | pv -s 10574005 > notifications-5.json
# 2. test the results for indicators such as length
# grep -v NOTFOUND notifications-5.json | grep '"OK"' | sd/notif.py test | grep -v  _OK | sort -k5n


def main(C):

    from couchdb import Task
    from pg import get_children
    if sys.argv[1]=='parse':

        if len(sys.argv)>2:
            ts = [Task.get(C,sys.argv[2])]+get_children(C,sys.argv[1])
        else:
            ts = Task.view('task/all')
        parse(C,ts,len(sys.argv)>3 and sys.argv[3] or None)
    elif sys.argv[1]=='test':
        for ln in sys.stdin:
            spl = ln.strip().split(" ")
            tid = spl[0]
            r1 = spl[1]
            r2 = spl[2]
            jn = " ".join(spl[3:])
            j = json.loads(jn)
            st,lch,sch = j
            schs = "; ".join(sch)
            if len(schs)>150:
                print(tid,r1,r2,'SCHANGE_TOOLONG',len(schs))
            else:
                print(tid,r1,r2,'SCHANGE_OK',schs)

    else:
        raise Exception('argh')

if __name__=='__main__':
    from docs import initvars,P
    import config as cfg
    initvars(cfg)
    with P as p:
        C = p.cursor()
        main(C)
