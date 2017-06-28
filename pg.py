from __future__ import print_function
from builtins import object
import psycopg2
import psycopg2.extras
from gevent.lock import BoundedSemaphore as Semaphore
from gevent.local import local as gevent_local
from config import PG_DSN,DONESTATES
from gevent import sleep

# migration stuff
import json,re
from datetime import datetime,date

import decimal

class ConnectionPool(object):
    def __init__(self, dsn, max_con=12, max_idle=3,
                 connection_factory=psycopg2.extras.RealDictConnection):
        self.dsn = dsn
        self.max_con = max_con
        self.max_idle = max_idle
        self.connection_factory = connection_factory
        self._sem = Semaphore(max_con)
        self._free = []
        self._local = gevent_local()

    def __enter__(self):
        self._sem.acquire()
        try:
            if getattr(self._local, 'con', None) is not None:
                con = self._local.con
                print('WARNING: returning existing connection (re-entered connection pool)!')
            if self._free:
                con = self._free.pop()
            else:
                con = psycopg2.connect(
                    dsn=self.dsn, connection_factory=self.connection_factory)
            self._local.con = con
            return con
        except: # StandardError:
            #print('releasing')
            self._sem.release()
            #print('released')
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self._local.con is None:
                raise RuntimeError("Exit connection pool with no connection?")
            if exc_type is not None:
                self.rollback()
            else:
                self.commit()
            if len(self._free) < self.max_idle:
                self._free.append(self._local.con)
            self._local.con = None
        finally:
            self._sem.release()
            #print('released')

    def commit(self):
        self._local.con.commit()

    def rollback(self):
        self._local.con.rollback()
	
def connect():
    #raise Exception('from where')
    pg = psycopg2.connect(PG_DSN)
    pgc = pg.cursor(cursor_factory=psycopg2.extras.DictCursor)
    pg.set_client_encoding('utf-8')
    return pg,pgc

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        serial = obj.isoformat()
    elif isinstance(obj,decimal.Decimal):
        serial = float(obj)
    elif isinstance(obj,set):
        serial = list(obj)
    elif isinstance(obj,date):
        serial = obj.isoformat()
    else:
        raise Exception(type(obj))
    return serial
    raise TypeError ("Type not serializable")

def get_journals(P,C,assignee=None,metastate_group='merge',archive=False):
    qry = "select * from tasks where 1=1" #journal_entries where 1=1" 
    args=[]
    if assignee=='all': assignee=None
    if assignee:
        qry+=" and contents->>'assignee'=%s"
        args.append(assignee)
    if metastate_group:
        if metastate_group!='production':
            if not archive:                #and t['status'] in cfg.DONESTATES: continue
                qry+=" and contents->>'status' not in %s"
                args.append(tuple(DONESTATES))
            elif archive: #and t['status'] not in cfg.DONESTATES: continue
                qry+=" and status in %s"
                args.append(tuple(DONESTATES))
            else:
                raise Exception('wtf')
    
    args = tuple(args) ;

    C.execute(qry,args)
    rt=[]
    for r in C.fetchall():
        rt.append(r)
    return rt
def journal_digest(j):
    rt={}
    for i in j:
        cat = i['created_at']
        jc = i['content']
        ja = i['creator']
        for k,v in list(i['attrs'].items()):
            if k not in rt: rt[k]={'created_at':cat}
            if rt[k]['created_at']<=cat:
                rt[k]['created_at']=cat
                rt[k]['value']=v
    return rt

def validate_save(C,tid,fetch_stamp,exc=True):
    C.execute("select changed_at,changed_by from tasks where id=%s",(tid,))
    res = C.fetchone()
    if res and fetch_stamp and res['changed_at'] and res.get('changed_by')!='notify-trigger':
        eq = res['changed_at']==fetch_stamp
        if exc:
            assert eq,"task %s: fetch stamp!=changed_at by %s (%s , %s)"%(tid,res.get('changed_by'),fetch_stamp,res and res['changed_at']) or None
        else:
            return eq,res['changed_at'],res['changed_by']
    return True,res and res.get('changed_at') or None,res and res.get('changed_by') or None
    
def migrate_one(t,pgc,fetch_stamp=None,user=None):
    td={}
    tid = t._id
    parid = "/".join(tid.split("/")[0:-1])
    if not parid: parid=None

    for k in t.__dict__:
        if k not in ['_dynamic_properties','_doc']:
            if t.__dict__[k] is not None:
                assert k not in td,"%s already exists with value %s (!= %s) for %s"%(k,td[k],t.__dict__[k],t._id)
                td[k]=t.__dict__[k]
    if 'journal' in td and len(td['journal']):
        td['journal_digest']=journal_digest(td['journal'])
    tdj = json.dumps(td,default=json_serial)
    pgc.execute("select * from tasks where id=%s",(tid,))
    res = pgc.fetchone()
    if not res:
        op='ins'
        qry = "insert into tasks (contents,parent_id,changed_at,changed_by,id) values(%s,%s,%s,%s,%s)"
        chat=datetime.now() ; chatf='now'
        suser = user
    else:
        excont = res['contents']
        nwcont = json.loads(tdj)
        
        # exf = open('/tmp/ex.json','w') ; exf.write(json.dumps(excont)) ; exf.close()
        # nwf = open('/tmp/nw.json','w') ; nwf.write(json.dumps(nwcont)) ; nwf.close()
        if nwcont==excont and user not in ['notify-trigger']:
            chat = res['changed_at'] ; chatf='existing'
            suser = res['changed_by']
        else:
            chatf='now'
            chat = datetime.now() ;
            suser = user


        #raise Exception(type(nwcont),type(excont),len(nwcont),len(excont),nwcont==excont)
        op='upd'
        qry = "update tasks set contents=%s,parent_id=%s,changed_at=%s,changed_by=%s where id=%s"

    data = (tdj,parid,chat,suser,t._id)
    #print qry,data
    print((op,t._id,parid))
    pgc.execute(qry,data)

# -- create table tasks (id varchar primary key, parent_id varchar references tasks(id) , contents json);

def get_repos(C):
    C.execute("select name from repos")
    res = C.fetchall()
    return [r['name'] for r in res]
def get_usernames(C):
    C.execute("select username from participants where active=true order by username")
    res = C.fetchall()
    return [r['username'] for r in res]

def hasperm_db(C,perm,user):
    qry = "select count(*) cnt from participants where username=%s and %s=any(perms) and active=true"
    C.execute(qry,(perm,user))
    o = C.fetchone()
    rt = o['cnt'] and True or False
    return rt

def hasperm(perms,perm):
    rt = perm in perms
    #print(qry,(user,perm),'=>',rt)
    return rt

def get_participants(C,sort=True,disabled=False):
    qry = "select * from participants "
    if not disabled: qry+=" where active=true "
    if sort: qry+=" order by username"
    C.execute(qry)
    rt = {}
    for r in C.fetchall():
        if r['username'] not in rt: rt[r['username']]={}
        for k in list(r.keys()):
            rt[r['username']][k]=r[k]
    
    return rt #dict([(r['username'],dict([(k,r[k]) for k in r.keys()])) for r in C.fetchall()])

def get_all_journals(C,day=None,creator=None):
    qry = "select * from journal_entries where 1=1 "
    cnd=[]
    if day:
        qry+=" and created_at::date between %s and %s"
        cnd.append(day[0]) ; cnd.append(day[1])
        
    if creator:
        qry+=" and creator=%s"
        cnd.append(creator)
    C.execute(qry,cnd)

    jes = C.fetchall()
    return [{'creator':je['creator'],
             'content':je['cnt'],
             'attrs':je['attrs'],
             'created_at':je['created_at'],
             'tid':je['tid']} for je in jes]
    


# parents retrieval:
# with recursive allparents as (select id,parent_id from tasks t where id='832/408/8/1' union all select t.id,t.parent_id from tasks t join allparents on allparents.parent_id=t.id) select * from allparents order by id

# children retrieval:
def get_children(C,tid):
    from couchdb import Task
    qry="select t.* from task_hierarchy th,tasks t where %s=any(th.path_info) and th.id<>%s and t.id=th.id"
    opts=(tid,tid)
    C.execute(qry,opts)
    rows = [t['contents'] for t in C.fetchall()]
    rt=[]
    for r in rows:
        r['created_at']=datetime.strptime( r['created_at'].split('.')[0].split('Z')[0], "%Y-%m-%dT%H:%M:%S" )
        t = Task(**r)
        rt.append(t)
    return rt

def get_cross_links(C,tid):
    C.execute("select clid from cross_links where id=%s",(tid,))
    rt = C.fetchall()
    return [r['clid'] for r in rt]

def get_new_idx(C,parent=None):
    if parent==None:
        qry = "select max((regexp_split_to_array(id,'/'))[1]::integer)+1 new_idx from tasks"
        conds=()
    else:
        pars = str(parent).split("/")
        parlen=len(pars)+1
        like=str(parent)+'/%'
        qry = "select max((regexp_split_to_array(id,'/'))["+str(parlen)+"]::integer)+1 new_idx from tasks where id like %s"
        conds=(like,)
    #print('QUERYING',qry,conds)
    C.execute(qry,conds)
    nid = C.fetchall()[0]['new_idx']
    if nid==None:
        nid='1'
    if parent:
        nid=str(parent)+'/'+str(nid)
    rt= str(nid)
    #if parent: raise Exception(parent,nid,'=>',rt)
    assert re.compile('^([0-9]+)([0-9\/]*)$').search(rt),"%s does not match"%rt
    return rt

def get_task(C,tid):
    from couchdb import Task
    C.execute("select contents from tasks where id=%s",(tid,))
    c = C.fetchall()[0]['contents']
    return Task(**c)

def get_tags(C):
    C.execute("select tag,count(*) from task_tags group by tag")
    res = C.fetchall()
    return dict([(r['tag'],r['count']) for r in res])


def get_revisions(C,tid):
    C.execute("select * from tasks where id=%s union select * from tasks_history where id=%s order by sys_period desc",(tid,tid))
    res = C.fetchall()
    return dict([((r['sys_period'].lower and r['sys_period'].lower.strftime('%Y-%m-%dT%H:%I:%S') or '')+
                  '_'+
                 (r['sys_period'].upper and r['sys_period'].upper.strftime('%Y-%m-%dT%H:%I:%S') or ''),r) for r in res])
