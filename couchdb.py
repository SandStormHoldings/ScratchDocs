#!/usr/bin/env python
#-coding=utf-8
from couchdbkit import *
from couchdbkit.exceptions import ResourceNotFound
import notif
import sys
import re
import jsonpatch
import pg
from config import COUCHDB_URI,PG_DSN
def init_conn():
    #print 'creating server'
    if COUCHDB_URI:
        s = Server(uri=COUCHDB_URI)
    else:
        s = Server()

    p = pg.ConnectionPool(dsn=PG_DSN)
    
    #print 'obtaining db'
    d = s.get_or_create_db("tasks")
    Task.set_db(d)
    return s,d,p

class JournalEntry(Document):
    pass

class Task(Document):
    id = StringProperty()
    summary = StringProperty()
    content = StringProperty()

    creator = StringProperty()
    assignee = StringProperty()
    created_at = DateTimeProperty()

    def save(self,P,C,user=None,notify=True,fetch_stamp=None):
        try:
            from pg import migrate_one,validate_save
            if self._id and user!='notify-trigger':
                validate_save(C,self._id,fetch_stamp)
            Document.save(self)
            migrate_one(self,C,fetch_stamp=user!='notify-trigger' and fetch_stamp or None,user=user)
            P.commit()
        except:
            print 'could not save task %s'%self._id
            raise
        if not notify: return
        if notify:
            import tasks
            tasks.notifications.apply_async((user,self._id),countdown=10)
        
    def _notify(self,user,lc=None):
        #raise Exception('in notify of %s action by user %s'%(lc,user))
        #print 'in notify'
        import sendgrid
        from sendgrid.helpers.mail import *
        import config as cfg
        from docs import P,D
        from pg import get_participants
        with P as p:
            C = p.cursor()
            participants = get_participants(C,disabled=True)
        if not lc:
            lc = last_change(self,D)
        if not lc: return

        cnt,rev,lchanges,schanges,isnew = lc
        if not cnt or not len(lchanges):
            #print 'no notifications needed'
            return

        if not hasattr(self,'notifications'): self.notifications={}
        if rev in self.notifications: return
        text = ("\n\n".join(lchanges))+"\n\n\n %s changes"%len(lchanges)

        imptags = set(['critical','priority','email','bug','ops'])
        imptstr = ",".join([impt.upper() for impt in imptags.intersection(set(self.tags))])
        nsubj = unicode(self.summary)+(imptstr and " [%s] "%imptstr or "")
        if not isnew and not nsubj.startswith('Re:'): nsubj=u'Re: '+nsubj
        tre = re.compile('\[t/([0-9\/]+)\]') #subject task id regexp

        while True:
            if tre.search(nsubj): nsubj='[t/'.join(nsubj.split('[t/')[0:-2])
            else: break

        if not tre.search(nsubj): nsubj=nsubj+' [t/%s]'%self._id
            
        if user in participants:
            spl = participants[user]['email'].split('@')
            #print 'snd = @.join',spl,cfg.EMAIL_POSTFIX
            snd = '@'.join([spl[0]+cfg.EMAIL_POSTFIX,spl[1]])
            #print 'snd = %s'%snd
        else:
            snd = cfg.SENDER

        # the recipients are everyone except the author of change, unless the task is new and then the author gets an e-mail confirmation.
        inf=[]
        for k in ['creator','assignee','handled_by']:
            if hasattr(self,k):
              inf.append(getattr(self,k))

        rcpts = set(self.informed+inf )-(not isnew and user and set([user]) or set())
        rems = [(r in participants and participants[r]['email'] or r) for r in rcpts if r]

        if snd in rems: rems.remove(snd)
        for ignm in cfg.EMAIL_RECIPIENTS_IGNOREMASK:
            if ignm in rems: rems.remove(snd)
        to = ', '.join(rems)
        if not len(rems):
            print 'no recipients. breaking'
            return
        print 'SENDING MAIL from %s TO %s with subject %s'%(snd,",".join(rems),nsubj)

        for rcpt in rems:
            # fucking dangerous! creates loops
            # if hasattr(self,'external_id') and getattr(self,'external_id'):
            #     for cca in cfg.EMAIL_RECIPIENTS_CC:
            #         print 'adding Cc',cca
            #         msg.add_cc(cca)

            sg = sendgrid.SendGridAPIClient(apikey=cfg.SENDGRID_APIKEY)

            m = Mail(Email(snd),
                       nsubj,
                       Email(rcpt),
                       Content('text/plain',text)
                       )
            response = sg.client.mail.send.post(request_body=m.get())
            status = response.status_code
            assert status in [200,202],"status code is %s"%status # 202 - accepted, 200 - sandbox mode
        notif = {'notified_at':datetime.datetime.now(),
                 'user':user,
                 'informed':rcpts}
        ts = Task.get(self._id)
        if not hasattr(ts,'notifications'): ts.notifications={}
        ts.notifications[rev]=notif
        print 'saving notification'
        with P as p:
            C = p.cursor()
            ts.save(P,C,user='notify-trigger',notify=False)
        print 'done'

        
def push_views(d):
    # from couchdbkit.loaders import FileSystemDocsLoader
    # loader = FileSystemDocsLoader('couchdb/_design/task')
    # loader.sync(d,verbose=True)
    print 'pushing views'
    push('couchdb/_design/task',d,force=True)

################################################################################
from json import dumps, loads, JSONEncoder, JSONDecoder
import pickle
import datetime

class PythonObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (list, dict, str, unicode, int, float, bool, type(None))):
            return JSONEncoder.default(self, obj)
        elif isinstance(obj,(datetime.datetime)):
            return obj.strftime('%Y-%m-%d')
        return {'_python_object': pickle.dumps(obj)}

def as_python_object(dct):
    if '_python_object' in dct:
        return pickle.loads(str(dct['_python_object']))
    return dct
################################################################################

def get_all():
    return Task.view('task/all')

def get_task(tid):
    #print "have been given task %s to obtain"%tid
    rt= Task.get(tid)
    return rt

def get_cross_links(tid):
    return [[cl['key'],cl['value']] for cl in Task.view('task/crosslinks',key=tid)]

def get_children(tid):
    onelch = [Task.get(t['value']) for t in Task.view('task/children2',key=tid)]
    for chtid in onelch:
        onelch+=get_children(chtid._id)
    return onelch

def get_parents(tid):
    ints = [int(tp) for tp in tid.split('/')]
    keys=[]
    for l in range(1,len(ints)):
        keys.append(ints[0:l])    
    tasks = Task.view('task/children',
                      keys=keys)
    return tasks

def get_by_tag(tag):
    return Task.view('task/tags',key=tag)

def get_related(rel):
    return Task.view('task/related',key=rel)

def get_by_status(st):
    return Task.view('task/status',key=st)

def get_ids():
    ids = Task.view('task/ids')
    return [r['id'] for r in ids]

def get_new_idx(par=''):
    #print 'getting new idx %s'%par
    par = str(par)
    allids = get_ids()
    agg={}
    for tid in allids:
        pth = tid.split('/')
        val = pth[-1]
        aggk = '/'.join(map(lambda x:str(x),pth[0:-1]))
        if aggk not in agg: agg[aggk]=0
        if int(agg[aggk])<int(val): agg[aggk]=val
        if tid not in aggk: agg[tid]=0
    #raise Exception(agg)
    assert (not par) or (par in agg),"%s not in agg %s"%(par,agg.keys())
    # print 'returning %s + / + %s'%(par,int(agg[par])+1)
    # print 'par = "%s" ; agg[par] = "%s"'%(par,agg[par])
    rt= (par and str(par)+'/'or '')+str(int(agg.get(par,0))+1)
    return rt

def get_journals(day=None):
    if day:
        if type(day)==list:
            day = [k.strftime('%Y-%m-%d') for k in day]
            return Task.view('task/journals_by_day',startkey=day[0],endkey=day[1],classes={None: JournalEntry})
        else:
            day = day.strftime('%Y-%m-%d')
            return Task.view('task/journals_by_day',key=day,classes={None: JournalEntry})
    else:
        return Task.view('task/journals')

def get_tags():
    tags = [t['key'] for t in Task.view('task/tag_ids')]
    agg={}
    for t in tags:
        if t not in agg: agg[t]=0
        agg[t]+=1
    return agg

def last_change(t,d,specific_rev=None):
    #print 'notifying over last_change in %s, %s, %s'%(t,d,specific_rev)
    doc = d.open_doc(t._id,revs=True)
    i=len(doc['_revisions']['ids'])
    pdc={} ; prev = None
    revs = doc['_revisions']['ids']
    lastrevi = int(t._rev.split('-')[0])
    idxdiff = lastrevi-len(revs)
    revs.reverse()
    revs = ['%s-%s'%(i+idxdiff,revs[i-1]) for i in range(1,len(revs)+1)]
    if specific_rev:
        while len(revs) and revs[-1]!=specific_rev:
            revs.pop()
    if len(revs)<2:
        prev=None
    else:
        prev = revs[-2]
    obt = revs[-1]
    j1 = t.to_json() ; notif.clean(j1)
    if prev:
        #print 'obtaining task %s rev %s'%(t._id,prev)
        t2 = Task.get(t._id,rev=prev)
    else:
        print 'prev does not exist. starting with an empty task.'
        prev='initial-%s'%t._id
        t2 = Task()
    j2 = t2.to_json() ; notif.clean(j2)
    jps = jsonpatch.JsonPatch.from_diff(j2,j1)
    cnt,lchanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=100)
    cnt,schanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=10)

    if cnt: print '%s differences, %s lchanges between %s and %s'%(cnt,len(lchanges),prev,obt)
    return cnt,obt,lchanges,schanges,isnew

def all_changes(t,d):
    ch={}
    doc = d.open_doc(t._id,revs=True)
    revs = doc['_revisions']['ids']
    nots = getattr(t,'notifications',{}).keys()
    lastrevi,lastrevh = t._rev.split('-')
    idxdiff = (int(lastrevi)-len(revs))
    revs.reverse()
    revs = ['%s-%s'%(i+idxdiff,revs[i-1]) for i in range(1,len(revs)+1)]
    prev = None
    for rev in revs:
        if not prev: prev='initial-%s'%t._id
        notified = prev in nots
        print prev,rev,'notified:',notified
        if notified: continue
        try:
            t1 = Task.get(t._id,rev=rev)
            if not prev.startswith('initial-'):
                t2 = Task.get(t._id,rev=prev)
            else:
                t2 = Task()
        except ResourceNotFound as e:
            print 'could not find one of',prev,rev
            prev=rev
            continue
        j1 = t1.to_json() ; notif.clean(j1)
        j2 = t2.to_json() ; notif.clean(j2)
        jps = jsonpatch.JsonPatch.from_diff(j2,j1)
        cnt,lchanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=100)
        cnt,schanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=10)
        print cnt,'differences',lchanges
        ch[rev]=(cnt,prev,lchanges,schanges)
        prev = rev
    return ch
if __name__=='__main__':
    from docs import initvars
    from pg import get_participants
    S,D,P = init_conn()
    import config as cfg
    initvars(cfg)
    if 'children' in sys.argv[1:]:
        ts = get_children(sys.argv[1])
    else:
        ts = [Task.get(sys.argv[1])]

    for t in ts:
        print 'task',t._id
        ch = all_changes(t,D)
        for rev,sch in ch.items(): #(cnt,rev,lchanges,schanges)
            if 'notify' in sys.argv[1:]:
                t._notify(user='notify-trigger',lc=sch)
