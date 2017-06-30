from builtins import str
from builtins import range
import notif
import sys
import re
import jsonpatch
import pg
from config import PG_DSN
def init_conn():
    p = pg.ConnectionPool(dsn=PG_DSN)
    #print 'obtaining db'
    return p


class Task(object):
    _id = None
    parent_id = None
    contents = None
    show_in_gantt = True
    changed_at = None
    changed_by = None

    # def get(self,tid):
    #     pass
    
    # emulating old style task objects
    @staticmethod
    def get(C,tid=None):
        qry = "select * from tasks where id=%s"
        C.execute(qry,(tid,))
        row = C.fetchall()[0]['contents']
        return Task(**row)
    def __init__(self,**kwargs):
        for k,v in kwargs.items(): setattr(self,k,v)
            
    def __getitem__(self, key):
        if key==0: raise Exception('why am i being asked for 0?',self.__dict__)
        #print("asked for",key,"got",self.__dict__)
        try:
            rt = self.__dict__[key]
        except KeyError:
            print('could not obtain key',key,'from',self.__dict__.keys())
            raise
        return rt
            
    def save(self,P,C,user=None,notify=True,fetch_stamp=None):
        try:
            if self._id and user!='notify-trigger':
                pg.validate_save(C,self._id,fetch_stamp)
            pg.migrate_one(self,
                           C,
                           fetch_stamp=user!='notify-trigger' and fetch_stamp or None,
                           user=user)
            P.commit()
        except:
            print('could not save task %s'%self._id)
            raise
        if not notify: return
        if notify:
            import tasks
            tasks.notifications.apply_async((user,self._id),countdown=10)
        
    def _notify(self,P,C,user,lc=None):
        #raise Exception('in notify of %s action by user %s'%(lc,user))
        #print 'in notify'
        import sendgrid,sendgrid.helpers.mail
        import config as cfg
        import notif
        from pg import get_participants,last_change
        participants = get_participants(C,disabled=True)
        if not lc:
            # last change
            lc = notif.parse(C,[self],supress=False,limit=2)
            if len(lc): lc=lc[0]
        if not lc: return
        cnt = lc['lchanges_cnt']
        rev = lc['v2rev']
        lchanges = lc['lchanges']
        schanges = lc['schanges']
        isnew=lc['nt']
        #cnt,rev,lchanges,schanges,isnew = lc
        if not cnt or not len(lchanges):
            #print 'no notifications needed'
            return

        if not hasattr(self,'notifications'): self.notifications={}
        if rev in self.notifications: return
        text = ("\n\n".join(lchanges))+"\n\n\n %s changes"%len(lchanges)

        imptags = set(['critical','priority','email','bug','ops'])
        imptstr = ",".join([impt.upper() for impt in imptags.intersection(set(self.tags))])
        nsubj = str(self.summary)+(imptstr and " [%s] "%imptstr or "")
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
            print('no recipients. breaking')
            return
        print('SENDING MAIL from %s TO %s with subject %s'%(snd,",".join(rems),nsubj))

        for rcpt in rems:
            # fucking dangerous! creates loops
            # if hasattr(self,'external_id') and getattr(self,'external_id'):
            #     for cca in cfg.EMAIL_RECIPIENTS_CC:
            #         print 'adding Cc',cca
            #         msg.add_cc(cca)

            sg = sendgrid.SendGridAPIClient(apikey=cfg.SENDGRID_APIKEY)

            m = sendgrid.helpers.mail.Mail(Email(snd),
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
        ts = Task.get(C,self._id)
        if not hasattr(ts,'notifications'): ts.notifications={}
        ts.notifications[rev]=notif
        print('saving notification')
        ts.save(P,C,user='notify-trigger',notify=False)
        print('done')

        
def push_views(d):
    # from couchdbkit.loaders import FileSystemDocsLoader
    # loader = FileSystemDocsLoader('couchdb/_design/task')
    # loader.sync(d,verbose=True)
    print('pushing views')
    push('couchdb/_design/task',d,force=True)

################################################################################
from json import dumps, loads, JSONEncoder, JSONDecoder
import pickle
import datetime

class PythonObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (list, dict, str, int, float, bool, type(None))):
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

def get_task(C,tid):
    #print "have been given task %s to obtain"%tid
    rt= Task.get(C=C,tid=tid)
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



def all_changes(t,d):
    ch={}
    doc = d.open_doc(t._id,revs=True)
    revs = doc['_revisions']['ids']
    nots = list(getattr(t,'notifications',{}).keys())
    lastrevi,lastrevh = t._rev.split('-')
    idxdiff = (int(lastrevi)-len(revs))
    revs.reverse()
    revs = ['%s-%s'%(i+idxdiff,revs[i-1]) for i in range(1,len(revs)+1)]
    prev = None
    for rev in revs:
        if not prev: prev='initial-%s'%t._id
        notified = prev in nots
        print(prev,rev,'notified:',notified)
        if notified: continue
        try:
            t1 = Task.get(t._id,rev=rev)
            if not prev.startswith('initial-'):
                t2 = Task.get(t._id,rev=prev)
            else:
                t2 = Task()
        except ResourceNotFound as e:
            print('could not find one of',prev,rev)
            prev=rev
            continue
        j1 = t1.to_json() ; notif.clean(j1)
        j2 = t2.to_json() ; notif.clean(j2)
        jps = jsonpatch.JsonPatch.from_diff(j2,j1)
        cnt,lchanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=100)
        cnt,schanges,isnew = notif.parse_diff(jps,j1,j2,maxlen=10)
        print(cnt,'differences',lchanges)
        ch[rev]=(cnt,prev,lchanges,schanges)
        prev = rev
    return ch
if __name__=='__main__':
    from docs import initvars
    from pg import get_participants
    D,P = init_conn()
    import config as cfg
    initvars(cfg)
    if 'children' in sys.argv[1:]:
        ts = get_children(sys.argv[1])
    else:
        ts = [Task.get(sys.argv[1])]

    for t in ts:
        print('task',t._id)
        ch = all_changes(t,D)
        for rev,sch in list(ch.items()): #(cnt,rev,lchanges,schanges)
            if 'notify' in sys.argv[1:]:
                t._notify(user='notify-trigger',lc=sch)

