import psycopg2
import psycopg2.extras
from gevent.lock import BoundedSemaphore as Semaphore
from gevent.local import local as gevent_local
from config import PG_DSN
from gevent import sleep

# migration stuff
import json
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
        #print('acquired')
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
            self._sem.release()
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

def journal_digest(j):
    rt={}
    for i in j:
        cat = i['created_at']
        jc = i['content']
        ja = i['creator']
        for k,v in i['attrs'].items():
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
    for dn in ['_doc','_dynamic_properties']:
        for k in t.__dict__[dn]:
            assert k not in td or td[k]==t.__dict__['_doc'][k] ,"%s already exists with value %s (!= %s from %s) for %s"%(k,td[k],t.__dict__[dn][k],dn,t._id)
            td[k]=t.__dict__[dn][k]

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
        excont = res['contents'] ; del excont['_rev']
        nwcont = json.loads(tdj) ; del nwcont['_rev']
        
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
    print(op,t._id,parid)
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

def hasperm(C,perm,user):
    qry = "select count(*) cnt from participants where username=%s and %s=any(perms) and active=true"
    C.execute(qry,(perm,user))
    o = C.fetchone()
    rt = o['cnt'] and True or False
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
        for k in r.keys():
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
             'content':je['cnt'].decode('utf-8'),
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
        r['created_at']=datetime.strptime( r['created_at'], "%Y-%m-%dT%H:%M:%SZ" )
        t = Task(r)
        rt.append(t)
    return rt
