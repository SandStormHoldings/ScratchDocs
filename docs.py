#!/usr/bin/env python
# coding=utf-8
from __future__ import division
from __future__ import print_function
from past.builtins import cmp
from builtins import map
from builtins import str
from builtins import range
from past.utils import old_div
import argparse

from prettytable import PrettyTable
import os
from mako.template import Template
from mako.lookup import TemplateLookup
import datetime
import orgparse
import hashlib
import re
import codecs
import json
import tempfile
import time
import subprocess
import shlex
from dulwich.repo import Repo as DRepo
import gc
from couchdb import *
from pg import get_new_idx,get_tags

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

P = init_conn()

def gantt_info_row(grow,excl=('status','created_at','summary','parent_id','tid')):
    gantt = dict([(k,v) for k,v in list(grow.items()) if k not in excl])
    l = [x for x in [gantt['t_f'],gantt['c_f']] if x is not None]
    u = [x for x in [gantt['t_l'],gantt['c_l']] if x is not None]
    task_activity_frame=[len(l) and min(l) or None,
                         len(u) and max(u) or None]
    
    # (as a percentage:)
    thrs = gantt['t'] and (gantt['t'].days + old_div(float(gantt['t'].seconds),86400)) or 0
    wehrs = gantt['we'] and (gantt['we'].days + old_div(float(gantt['we'].seconds),86400)) or None
    if wehrs:
        complete_estimate = old_div(thrs, wehrs)
    else:
        complete_estimate = None

    gantt['ce'] = complete_estimate
    gantt['taf']=task_activity_frame
    
    # this is where we guess delivery date
    if task_activity_frame[0] and not task_activity_frame[1]: raise Exception(gantt)

    # if task is done, then duration is the de-facto frame
    if grow['status'] in ('DONE','CANCELLED',):
        if len([x for x in task_activity_frame if x is not None])>1:
            today = datetime.datetime.now().date()
            if task_activity_frame[1]>today:
                duration = (today-task_activity_frame[0]).days
                dt='Db'
            else:
                duration = (task_activity_frame[1]-task_activity_frame[0]).days
                dt='D'
        else:
            duration = None
            dt='DN'
    # otherwise, duration is an estimation of when it's going to be complete based on its progress
    else:
        if complete_estimate:
            dursofar = datetime.datetime.now().date() - task_activity_frame[0]
            estimate = old_div(float(dursofar.days), complete_estimate)
            duration = int(estimate)
            dt='E'
            #raise Exception('going to estimate ',r['tid'],' based on ',gr,dursofar,estimate)
        # if we have no work estimate we cannot make a completionestimation
        else:
            duration = None
            dt='EN'
    gantt['dt']=dt
    gantt['dur'] = duration
    gantt['s']=True
    return gantt
    
def gantt_info(C,tid):
    gantt_labels = {'we':'work estimate',
                    's':'show in gantt',
                    'dt':'duration estimate type',
                    'dur':'duration estimate',
                    't_l':'tracked last',
                    't_f':'tracked first',
                    'c_f':'commited first',
                    'c_l':'committed last',
                    't':'tracked',
                    'c':'lines added',
                    'finish_date':'finish date estimate',
                    'ce':'completion estimate',
                    'taf':'task activity frame'}
    C.execute("select * from gantt where tid=%s",(tid,))
    grow = C.fetchone()
    if grow:
        return gantt_labels,gantt_info_row(grow)
    else:
        return gantt_labels,{'s':False}
    
def org_render(ins):
    proc = subprocess.Popen([os.path.join(os.path.dirname(__file__),'orgmode-render.php')],
                            stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            close_fds=True)
    inss = ins.encode('utf-8')
    ops = proc.communicate(input=inss)[0]
    return ops.decode('utf-8')

def gso(cmd,close_fds=True,shell=False,executable=None):
    if type(cmd)==list:
        spl = cmd
    else:
        spl = shlex.split(cmd) #; spl[0]+='sadf'
    p = subprocess.Popen(spl,
                         stdout=subprocess.PIPE,
                         close_fds=close_fds,
                         shell=shell,
                         executable=executable)
    out, err = p.communicate()
    return p.returncode,out


def load_templates():
    if not os.path.exists(cfg.MAKO_DIR): os.mkdir(cfg.MAKO_DIR)
    _prefix = os.path.dirname(__file__)
    if cfg.TPLDIR:
        tpldir = cfg.TPLDIR
    else:
        tpldir = os.path.join(_prefix,'templates')
    lk = TemplateLookup(directories=['.'])
    rt = {}
    taskfn = os.path.join(tpldir,'task.org')
    assert os.path.exists(taskfn),"%s does not exist ; am in %s"%(taskfn,os.getcwd())
    rt['task'] = Template(filename=(taskfn),lookup = lk,module_directory=cfg.MAKO_DIR)
    rt['iterations'] = Template(filename=os.path.join(tpldir,'iterations.org'),lookup = lk,module_directory=cfg.MAKO_DIR)
    rt['tasks'] = Template(filename=os.path.join(tpldir,'tasks.org'),lookup = lk,module_directory=cfg.MAKO_DIR)
    rt['taskindex'] = Template(filename=os.path.join(tpldir,'taskindex.org'),lookup = lk,module_directory=cfg.MAKO_DIR)            
    rt['iteration'] = Template(filename=os.path.join(tpldir,'iteration.org'),lookup = lk,module_directory=cfg.MAKO_DIR)            
    rt['new_story_notify'] = Template(filename=os.path.join(tpldir,'new_story_notify.org'),lookup = lk,module_directory=cfg.MAKO_DIR)
    rt['change_notify'] = Template(filename=os.path.join(tpldir,'change_notify.org'),lookup = lk,module_directory=cfg.MAKO_DIR)
    rt['changes'] = Template(filename=os.path.join(tpldir,'changes.org'),lookup = lk,module_directory=cfg.MAKO_DIR)     
    rt['demo'] = Template(filename=os.path.join(tpldir,'demo.org'),lookup = lk,module_directory=cfg.MAKO_DIR)     
    return rt

ckre = re.compile('^'+re.escape('<!-- checksum:')+'([\d\w]{32})'+re.escape(' -->'))
def md5(fn):
    st,op = gso('md5sum %s'%fn); assert st==0
    op = op.split(' ')
    return op[0]

def loadcommits():
    global commits
    if not len(commits):
        if not os.path.exists(commitsfn):
            commits={}
        else:
            commits = json.load(open(commitsfn,'r'))
    return commits

tpls={}
def render(tplname,params,outfile=None,mode='w'):
    """helper to renders one of the mako templates defined above"""
    global tpls
    if not len(tpls):
        tpls = load_templates()

    t = tpls[tplname]
    for par,val in list(params.items()):
        try:
            if type(val)==str:
                val = str(val.decode('utf-8'))
                params[par]=val
        except:
            print(val)
            raise
    r= t.render(**params)

    if outfile:
        #print 'working %s'%outfile;        print params
        fp = codecs.open(outfile,mode,encoding='utf-8') ; fp.write(r) ; fp.close()
        #print 'written %s %s'%(tplname,pfn(outfile))

        return True
    return r

def purge_task(task,force=False):
    t = get_task(task)
    dn = os.path.dirname(t['path'])
    assert os.path.isdir(dn)
    ch = get_children(task)
    if len(ch) and not force:
        raise Exception('will not purge task with children unless --force is used.')
    st,op = gso('rm -rf %s'%dn) ; assert st==0
    return True

def pfn(fn):
    if cfg.CONSOLE_FRIENDLY_FILES:
        return 'file://%s'%os.path.abspath(fn)
    else:
        return fn

linkre = re.compile(re.escape('[[')+'([^\]]+)'+re.escape('][')+'([^\]]+)'+re.escape(']]'))
tokre = re.compile('^\- ([^\:]+)')
stokre = re.compile('^  \- (.+)')
date_formats = ['%Y-%m-%d %a','%Y-%m-%d','%Y-%m-%d %a %H:%M']

def parse_attrs(node,pth,no_tokagg=False):
    try:
        rt= dict([a[2:].split(' :: ') for a in node.split('\n') if a.startswith('- ') and ' :: ' in a])
        tokagg={}

        intok=False
        for ln in node.split('\n'):
            tokres = tokre.search(ln)
            if not tokres: 
                if intok:
                    stok = stokre.search(ln)
                    if stok:
                        stok = stok.group(1)
                        res = linkre.search(stok)
                        if res:
                            url,anchor = res.groups()
                            tokagg[tok].append({'url':url,'anchor':anchor})
                        else:
                            tokagg[tok].append(stok)
                    else:
                        raise Exception('wtf is %s (under %s) parsing %s'%(ln,tok,pth))
            else:
                tok = tokres.group(1)
                tokagg[tok]=[]
                if tok in ['informed','links','repobranch']:
                    intok=True
    except:
        print(node.split('\n'))
        raise
    for k,v in list(rt.items()):
        if k.endswith('date'):
            for frm in date_formats:
                try:
                    rt[k]=datetime.datetime.strptime(v.strip('<>[]'),frm)
                    break
                except ValueError:
                    pass
        if k in ['created_at']:
            dt = v.strip('<>[]').split('.')
            rt[k]=datetime.datetime.strptime(dt[0],'%Y-%m-%d %H:%M:%S')
            if len(dt)>1:
                rt[k]+=datetime.timedelta(microseconds=int(dt[1]))
    if not no_tokagg:
        for ta,tv in list(tokagg.items()):
            rt[ta]=tv

    return rt

taskfiles_cache={}
def flush_taskfiles_cache():
    global taskfiles_cache
    taskfiles_cache={}

def filterby(fieldname,value,rtl):
    raise Exception('filterby',fieldname,value,rtl)
    if fieldname in ['tagged']:
        values = value.split(',')
    else:
        values = [value]

    while len(values):
        value = values.pop()
        adir = os.path.join(cfg.DATADIR,fieldname,value)
        fcmd = 'find %s -type l -exec basename {} \;'%adir
        print(fcmd)
        st,op = gso(fcmd)  ; assert st==0,fcmd
        atids = [atid.replace('.','/') for atid in op.split('\n')]
        afiles = [os.path.join(cfg.DATADIR,atid,'task.org') for atid in atids]
        rf = set(rtl).intersection(set(afiles))
        rtl = list(rf)
    return rtl

def get_latest(C,tags='email',newer_than=None,limit=300):
    nt = datetime.datetime.strptime(newer_than.translate({None: ':-'}), "%Y-%m-%dT%H:%M:%S")
    args = []
    qry = """select je.* 
from 
journal_entries je,
task_tags t 
where 
1=1"""
    if tags:
        qry+=" and t.tag in %s"
        args.append(tuple(tags))

    qry+=""" and je.tid=t.id and 
je.created_at>=%s 
order by je.created_at desc 
limit %s"""
    args+=[nt,limit]
    
    C.execute(qry,args)
    tv = C.fetchall()
    trets = [(t['created_at'],
              get_task(C,t['tid']),
              [], #TODO: tags
              t['assignee'],
              t['attrs'],
              0 #TODO: num of journal updates
              )
              for t in tv]
    trets.sort(key=lambda x:x[0],reverse=True)
    return trets

def intersect(*d):
    sets = iter(map(set, d))
    result = next(sets)
    for s in sets:
        result = result.intersection(s)
    return result

def get_fns(C,assignee=None,created=None,handled_by=None,informed=None,status=None,tag=None,recurse=True,query=None,newer_than=None,tids=None,recent=False):
    """return task filenames according to provided criteria"""
    #raise Exception(assignee,created,informed)
    qry = "select * from tasks t,tasks_pri_comb_lean p where t.id=p.id"
    conds=[]
    trets=[]
    cnd=""
    if assignee:
        cnd+=" and contents->>'assignee'=%s"
        conds.append(assignee)
    if informed:
        cnd+=" and contents->>'informed'=%s"
        conds.append(informed)
    if handled_by:
        cnd+=" and contents->>'handled_by'=%s"
        conds.append(handled_by)
    if created:
        cnd+=" and contents->>'creator'=%s"
        conds.append(created)
    if status:
        cnd+=" and contents->>'status'=%s"
        conds.append(status)
    if tag:
        cnd+=""" and contents->'tags' @> '"%s"'"""
        conds.append(tag)
    if tids:
        cnd+=" and t.id in %s"
        conds.append(tuple(tids))
    if query:
        raise Exception('query unimpl')
        # qitems = [q.strip().lower() for q in query.split(' ') if len(q.strip())]
        # tretcands = dict([(qi,[r['value'][0] for r in Task.view('task/index',key=qi)]) for qi in qitems])
        # tretvals = list(tretcands.values())
        # result = set(tretvals[0]).intersection(*tretvals)
        # trets.append([Task.get(r) for r in result])
    if recent:
        newer_than=14
    if newer_than:
        cnd+=" and (contents->>'created_at')::timestamp>=now()-interval '%s day'"
        conds.append(newer_than)
    if not recurse:
        cnd+= ' and parent_id is null'
    print('QUERYING',qry+cnd,conds)
    C.execute(qry+cnd,conds)
    its = C.fetchall()
    return its

    # if len(trets)==1:
    #     its = dict([(t._id,t) for t in trets[0]])
    # elif len(its):
    #     print(trets)
    #     raise NotImplementedError('need intersection between all results here')
    # # ids = tuple(its.keys())    
    # # if len(ids):
    # #     priqry = "select id,comb_pri from tasks_pri_comb where id in %s"
    # #     C.execute(priqry,(ids,))
    # #     pris = C.fetchall()
    # #     for pri in pris:
    # #         its[pri['id']].pri = pri['comb_pri']
            
    # # for k,v in list(its.items()):
    # #     if not hasattr(v,'pri'):
    # #         its[k].pri = 0
    # return list(its.values())

def get_parent(tid,tl=False):
    spl = tid.split('/')
    if len(spl)>1:
        if tl:
            return spl[0]
        else:
            return spl[-2]
    else:
        return spl[0]

def status_srt(s1,s2):
    cst = dict([(cfg.STATUSES[i],i) for i in range(len(cfg.STATUSES))])
    return cmp(cst[s1[1]['status']],cst[s2[1]['status']])

def taskid_srt(s1,s2):
    cst = dict([(cfg.STATUSES[i],i) for i in range(len(cfg.STATUSES))])
    s1i = int(s1[1]['story'].split(cfg.STORY_SEPARATOR)[0])
    s2i = int(s2[1]['story'].split(cfg.STORY_SEPARATOR)[0])
    return cmp(s1i,s2i)

def hours_srt(s1,s2):
    s1v = s1[1].get('total_hours',0)
    s2v = s2[1].get('total_hours',0)
    if not s1v and not s2v:
        s1v = int(s1[1]['story'].split(cfg.STORY_SEPARATOR)[0])
        s2v = int(s2[1]['story'].split(cfg.STORY_SEPARATOR)[0])
    return cmp(s1v,s2v)

def hours_srt_2(h1,h2):
    return cmp(h1[1]['last_tracked'],h2[1]['last_tracked'])*-1

def parse_iteration(pth):
    iteration_name = os.path.basename(os.path.dirname(pth))
    rt={'path':pth,'name':os.path.basename(os.path.dirname(pth))}
    root = orgparse.load(pth)
    for node in root[1:]:
        head = node.get_heading()
        if node.get_heading()=='Attributes':
            attrs = parse_attrs(str(node),pth)
            for k,v in list(attrs.items()): rt[k]=v
    return rt

def get_table_contents(fn,force=False):
    assert force==True,"get_table_contents is deprecated. everything is off to pg (%s)."%fn
    ffn = os.path.join(fn)
    fp = open(ffn,'r') ; gothead=False
    def parseline(ln):
        return [f.strip() for f in ln.split('|')][1:-1]
    rt=[]
    while True:
        ln = fp.readline()
        if not ln: break
        if '|' in ln and not gothead:
            headers = parseline(ln)
            gothead=True
            continue
        if ln.startswith('|-'): continue
        row = parseline(ln)
        row = dict([(headers[i],row[i]) for i in range(len(row))])

        rt.append(row)
        #only active ones:
    return rt

def get_participants(DATADIR,disabled=False,sort=False,force=False):
    tconts = get_table_contents(os.path.join(DATADIR,'participants.org'),force=force)
    rt={}
    for row in tconts:
        if disabled or row['Active']=='Y':
            rt[row['Username']]=row

    if sort:
        rt = list(rt.items())
        rt.sort(lambda r1,r2: cmp(r1[0],r2[0]))
    return rt

def get_story_trans():
    tconts = get_table_contents(os.path.join(cfg.DATADIR,'taskmap.org'))
    rt = {}
    for t in tconts:
        rt[t['Task']]=t['Target']
    return rt
    #raise Exception(tconts)

def add_notification(whom,about,what):
    send_notification(whom,about,what,how=None,justverify=True)

    t = get_task(about,read=True)
    if os.path.exists(t['metadata']):
        meta = loadmeta(t['metadata'])
    else:
        meta={}
    if 'notifications' not in meta: meta['notifications']=[]
    meta['notifications'].append({'whom':whom,'about':about,'what':what,'added':datetime.datetime.now().isoformat()})
    savemeta(t['metadata'],meta)

def parse_change(t,body,descr=True):
    ch = body.get('change',[])
    if u'--- /dev/null' in ch:
        verb='created'
    else:
        verb='changed'
    if descr:
        app = u' - %s'%t['summary']
    else:
        app = u''
    stchangere=re.compile('^(\-|\+)\* (%s)'%'|'.join(cfg.STATUSES))
    stch = [r for r in ch if stchangere.search(r)]
    canlines=0
    if len(stch)==2:
        sw = stchangere.search(stch[0]).group(2)
        sn = stchangere.search(stch[1]).group(2)
        scdigest=('%s -> %s'%(sw,sn))
        app+='; %s'%scdigest
        canlines+=1
    asgnchangere=re.compile('^(\-|\+)'+re.escape('- assigned to :: ')+'(.+)')
    asch = [r for r in ch if asgnchangere.search(r)]
    if len(asch)==2:
        aw = asgnchangere.search(asch[0]).group(2)
        an = asgnchangere.search(asch[1]).group(2)
        asdigest=('reassigned %s -> %s'%(aw,an))
        app+='; %s'%asdigest
        canlines+=1
    laddre = re.compile('^(\+)')
    laddres = [r for r in ch[4:] if not r.startswith('+++') and laddre.search(r) or False] #skipping diff header
    lremre = re.compile('^(\-)')
    lremres = [r for r in ch[4:] if not r.startswith('+++') and lremre.search(r) or False] #skipping diff header
    if len(laddres)==len(lremres):
        if canlines!=len(laddres):
            app+='; %sl'%(len(laddres))
    elif verb=='changed':
        app+=';'
        if len(laddres): app+=' +%s'%len(laddres)
        if len(lremres):  app+='/-%s'%len(lremres)
    subject = '%s ch. by %s'%(t['story'],body.get('author_username','Uknown'))+app
    return subject

def send_notification(whom,about,what,how=None,justverify=False,body={},nonotify=False):
    assert cfg.RENDER_URL,"no RENDER_URL specified in config."
    assert cfg.SENDER,"no sender specified in config."

    p = get_participants(cfg.DATADIR)
    try:
        email = p[whom]['email']
    except KeyError:
        #print '%s not in %s'%(whom,p.keys())
        return False
    t= get_task(about,read=True)
    tpl = what+'_notify'
    tf = tempfile.NamedTemporaryFile(delete=False,suffix='.org')

    #try to figure out what changed
    subject = parse_change(t,body)

    #construct the rendered mail template informing of the change
    if what=='change':

        assert cfg.GITWEB_URL
        assert cfg.DOCS_REPONAME
        rdt = {'t':t,'url':cfg.RENDER_URL,'recipient':p[whom],'commit':how,'gitweb':cfg.GITWEB_URL,'docsrepo':cfg.DOCS_REPONAME,'body':body}
    elif what in ['new_story']:
        return False
    else:
        raise Exception('unknown topic %s for %s'%(what,about))
    notify = render(tpl,rdt,tf.name)
    #print open(tf.name,'r').read() ; raise Exception('bye')
    if justverify:
        return False
    cmd = 'emacs -batch --visit="%s" --funcall org-export-as-html-batch'%(tf.name)
    st,op = gso(cmd) ; assert st==0,cmd
    expname = tf.name.replace('.org','.html')
    #print 'written %s'%expname
    assert os.path.exists(expname)
    if body and body.get('authormail'):
        sender = body.get('authormail')
    else:
        sender = cfg.SENDER
    subject_utf8 = subject.encode('utf-8')
    message = MIMEMultipart('alternative')
    message['subject'] = subject_utf8
    message['From'] = sender
    message['To'] = '%s <%s>'%(p[whom]['Name'],email)
    part = MIMEText(ody,'html')
    message.attach(part)
    message.add_to(email,p[whom]['Name'])
    if not cfg.NONOTIFY and not nonotify:
        s = smtplib.SMTP(cfg.SMTP_HOST)
        s.sendmail(sender,email,message.as_string())
        s.quit()
    return True

def add_iteration(name,start_date=None,end_date=None):
    raise Exception('TODO')
    itdir = os.path.join(cfg.DATADIR,name)
    itfn = os.path.join(itdir,'iteration.org')
    assert not os.path.exists(itdir),"%s exists."%itdir
    os.mkdir(itdir)
    render('iteration',{'start_date':start_date,'end_date':end_date},itfn)

def add_task(P,C,parent=None,params={},force_id=None,tags=[],user=None,fetch_stamp=None):
    print('in add_task')
    if parent:
        if force_id:
            newidx = force_id
        else:
            newidx = get_new_idx(C,parent)
    else:
        print('is a top level task')
        if force_id:
            #make sure we don't have it already
            newidx = str(force_id)
        else:
            print('getting a new index')
            newidx = get_new_idx(C)
    fullid = newidx

    if type(params)==dict:
        pars = dict(params)
    else:
        pars = params.__dict__

    if 'created_at' not in pars:
        pars['created_at'] = datetime.datetime.now()
    if 'creator' not in pars:
        pars['creator'] = cfg.CREATOR
    if 'status' not in pars:
        pars['status'] = cfg.DEFAULT_STATUS

    for k in ['summary','assignee','points','detail']:
       if k not in pars: pars[k]=None

    if pars['summary'] and type(pars['summary'])==list:
        pars['summary']=' '.join(pars['summary'])

    for ai in cfg.ALWAYS_INFORMED:
        if ai not in pars['informed']: pars['informed'].append(ai)

    pars['tags']=tags
    #print 'rendering'
    t = Task()
    t._id = fullid
    t.path = fullid.split('/')
    t.journal=[]
    for k in pars:
        setattr(t,k,pars[k])
    t.save(P,C,user=user,fetch_stamp=fetch_stamp)
    return t

def makehtml(notasks=False,files=[]):
    pth = cfg.DATADIR
    findcmd = 'find %s ! -wholename "*orgparse*" ! -wholename "*templates*" ! -wholename "*.git*" -iname "*.org" -type f'%(pth)
    st,op = gso(findcmd) ; assert st==0

    if len(files):
        orgfiles = files
    else:
        orgfiles = [fn for fn in op.split('\n') if fn!='']
    cnt=0
    for orgf in orgfiles:
        cnt+=1
        if notasks and (os.path.basename(orgf)==cfg.TASKFN or os.path.exists(os.path.join(os.path.dirname(orgf),cfg.TASKFN))):
            continue
        outfile = os.path.join(os.path.dirname(orgf),os.path.basename(orgf).replace('.org','.html'))
        needrun=False
        if os.path.exists(outfile): #emacs is darn slow.
            #invalidate by checksum
            st,op = gso('tail -1 %s'%outfile) ; assert st==0
            res = ckre.search(op)
            if res and os.path.exists(orgf): 
                ck = res.group(1)
                md = md5(orgf)
                if ck!=md:
                    needrun=True
            else:
                needrun=True
        else:
            needrun=True
        #print('needrun %s on %s'%(needrun,outfile))
        if needrun:
            cmd = 'emacs -batch --visit="%s" --funcall org-export-as-html-batch'%(orgf)
            st,op = gso(cmd) ; assert st==0,"%s returned %s"%(cmd,op)
            print('written %s'%pfn(outfile))

            if os.path.exists(orgf):
                md = md5(orgf)
                apnd = '\n<!-- checksum:%s -->'%(md)
                fp = open(outfile,'a') ; fp.write(apnd) ; fp.close()

        assert os.path.exists(outfile)

    print('processed %s orgfiles.'%cnt)

def by_status(stories):
    rt = {}
    for s in stories:
        st = s[1]['status']
        if st not in rt: rt[st]=[]
        rt[st].append(s)
    for st in rt:
        rt[st].sort(hours_srt,reverse=True)
    return rt

def get_current_iteration(iterations):
    raise Exception('TODO')
    nw = datetime.datetime.now() ; current_iteration=None
    for itp,it in iterations:
        if ('start date' in it and 'end date' in it):
            if (it['start date'].date()<=nw.date() and it['end date'].date()>=nw.date()):
                current_iteration = (itp,it)
    assert current_iteration,"no current iteration"
    return current_iteration

def makeindex(C):
    recent = [(tf,parse_fn(tf,read=True,gethours=True)) for tf in get_fns(C,recent=True)]
    recent.sort(hours_srt,reverse=True)
        
    assignees={}
    #create the dir for shortcuts
    if not os.path.exists(cfg.SDIR): os.mkdir(cfg.SDIR)

    #and render its index in the shortcuts folder
    idxstories = [(fn,parse_fn(fn,read=True,gethours=True)) for fn in get_fns(C,recurse=True)]
    vardict = {'term':'Index','value':'','stories':by_status(idxstories),'relpath':True,'statuses':cfg.STATUSES,'statusagg':{}}
    routfile= os.path.join(cfg.SDIR,'index.org')
    #print 'rendering %s'%routfile
    render('tasks',vardict,routfile)

    #print 'walking iteration %s'%it[0]
    taskfiles = get_fns(C,recurse=True)
    stories = [(fn,parse_fn(fn,read=True,gethours=True)) for fn in taskfiles]
    stories_by_id = dict([(st[1]['id'],st[1]) for st in stories])
    stories.sort(taskid_srt,reverse=True)        

    #let's create symlinks for all those stories to the root folder.
    for tl in stories:
        tpath = tl[0]
        taskid = '-'.join(tl[1]['story'].split(cfg.STORY_SEPARATOR))
        spath = os.path.join(cfg.SDIR,taskid)
        dpath = '/'+tl[1]['story']
        ldest = os.path.join('..',os.path.dirname(tpath))
        cmd = 'ln -s %s %s'%(ldest,spath)
        needrun=False
        if os.path.islink(spath):
            ls = os.readlink(spath)
            #print 'comparing %s <=> %s'%(ls,ldest)
            if ls!=ldest:
                os.unlink(spath)
                needrun=True
                #print 'needrun because neq'
        else:
            needrun=True
            #print 'needrunq because nex %s'%(spath)
        if needrun:
            st,op = gso(cmd) ; assert st==0,"%s returned %s"%(cmd,st)

        shallowstories = [st for st in stories if len(st[1]['story'].split(cfg.STORY_SEPARATOR))==1]

        #aggregate subtask statuses
        statusagg = {}
        for st in stories:
            #calcualte children
            chids = ([sst[1]['id'] for sst in stories if sst[1]['id'].startswith(st[1]['id']) and len(sst[1]['id'])>len(st[1]['id'])])
            if len(chids):
                statuses = {}
                for chid in chids:
                    sti = stories_by_id[chid]
                    if sti['status'] not in statuses: statuses[sti['status']]=0
                    statuses[sti['status']]+=1
                statusagg[st[1]['id']]=statuses

        vardict = {'term':'Iteration','value':it[1]['name'],'stories':by_status(shallowstories),'relpath':True,'statuses':cfg.STATUSES,'iteration':False,'statusagg':statusagg} #the index is generated only for the immediate 1-level down stories.
        itidxfn = os.path.join(cfg.DATADIR,it[0],'index.org')
        fp = open(itidxfn,'w') ; fp.write(open(os.path.join(cfg.DATADIR,it[0],'iteration.org')).read()) ; fp.close()
        stlist = render('tasks',vardict,itidxfn,'a') 

        #we show an iteration index of the immediate 1 level down tasks
        for st in stories:

            #aggregate assignees
            if st[1]['assigned to']:
                asgn = st[1]['assigned to']
                if asgn not in assignees: assignees[asgn]=0
                assignees[asgn]+=1

            #storycont = open( st[0],'r').read()
            storyidxfn = os.path.join(os.path.dirname(st[0]),'index.org')
            #print storyidxfn
            ch = get_children(st[1]['story'])
            for c in ch:
                c['relpath']=os.path.dirname(c['path'].replace(os.path.dirname(st[1]['path'])+'/',''))
            #print 'written story idx %s'%pfn(storyidxfn)

            pars = {'children':ch,'story':st[1],'TASKFN':cfg.TASKFN,'GITWEB_URL':cfg.GITWEB_URL,'pgd':parsegitdate,'RENDER_URL':cfg.RENDER_URL}
            if os.path.exists(pars['story']['metadata']):
                pars['meta']=loadmeta(pars['story']['metadata'])
            else:
                pars['meta']=None
            
            render('taskindex',pars,storyidxfn,'w')
            fp = open(storyidxfn,'a') ; fp.write(open(st[1]['path']).read()) ; fp.close()

            #print idxcont
    participants = get_participants(cfg.DATADIR)

    assigned_files={} ; excl=[]
    for asfn in ['alltime','current']:
        for assignee,storycnt in list(assignees.items()):
            if assignee!=None and assignee not in participants:
                if assignee not in excl:
                    #print 'excluding %s'%assignee
                    excl.append(assignee)
                continue
            afn = 'assigned-'+assignee+'-'+asfn+'.org'
            ofn = os.path.join(cfg.DATADIR,afn)
            if assignee not in assigned_files: assigned_files[assignee]={}
            
            assigned_files[assignee][asfn]=afn

            tf = get_fns(C,assignee=assignee,recurse=True)
            stories = [(fn,parse_fn(fn,read=True,gethours=True,hoursonlyfor=assignee)) for fn in tf]
            stories.sort(status_srt)
            vardict = {'term':'Assignee','value':'%s (%s)'%(assignee,storycnt),'stories':by_status(stories),'relpath':False,'statuses':cfg.STATUSES,'statusagg':{}}
            cont = render('tasks',vardict,ofn)


    vardict = {
               'stories':stories,
               'assigned_files':assigned_files,
               'assignees':assignees,
               'recent_tasks':recent,
               'statusagg':{}
               }
    idxfn = os.path.join(cfg.DATADIR,'index.org')
    itlist = render('iterations',vardict,idxfn)

    cfn = os.path.join(cfg.DATADIR,'changes.org')
    render('changes',{'GITWEB_URL':cfg.GITWEB_URL,'DOCS_REPONAME':cfg.DOCS_REPONAME,'pfn':parse_fn},cfn)

def list_stories(C,iteration=None,assignee=None,status=None,tag=None,recent=False):
    files = get_fns(C,assignee=assignee,status=status,tag=tag,recent=recent)
    pt = PrettyTable(['id','summary','assigned to','status','tags'])
    pt.align['summary']='l'
    cnt=0
    for fn in files:
        sd = parse_fn(fn,read=True)
        if iteration and iteration.startswith('not ') and sd['iteration']==iteration.replace('not ',''): 
            continue
        elif iteration and not iteration.startswith('not ') and sd['iteration']!=str(iteration): continue
        if len(sd['summary'])>60: summary=sd['summary'][0:60]+'..'
        else: summary = sd['summary']
        pt.add_row([sd['story'],summary,sd['assigned to'],sd['status'],','.join(sd.get('tags',''))])
        cnt+=1
    pt.sortby = 'status'
    print(pt)
    print('%s stories.'%cnt)

def tokenize(n):
    return '%s-%s'%(n['whom'],n.get('how'))

def imp_commits(args):
    print('importing commits.')
    if not os.path.exists(cfg.REPO_DIR): os.mkdir(cfg.REPO_DIR)
    excommits = loadcommits()
    for repo in cfg.REPOSITORIES:
        print('running repo %s'%repo)
        repon = os.path.basename(repo).replace('.git','')
        repodir = os.path.join(cfg.REPO_DIR,os.path.basename(repo))
        if not os.path.exists(repodir):
            print('cloning.')
            cmd = 'git clone -b staging %s %s'%(repo,repodir)
            st,op = gso(cmd) ; assert st==0,"%s returned %s\n%s"%(cmd,st,op)
        prevdir = os.getcwd()
        os.chdir(repodir)
        #refresh the repo
        
        if not args.nofetch:
            print('fetching at %s.'%os.getcwd())
            st,op = gso('git fetch -a') ; assert st==0,"git fetch -a returned %s\n%s"%(st,op)

        print('running show-branch')
        cmd = 'git show-branch -r'
        st,op = gso(cmd) ; assert st==0,"%s returned %s\n%s"%(cmd,st,op)
        commits=[] ; ignoredbranches=[]
        for ln in op.split('\n'):
            if ln=='': continue
            if ln.startswith('warning:'): 
                if 'ignoring' not in ln:
                    print(ln)
                else:
                    ign = re.compile('origin/([^;]+)').search(ln).group(1)
                    ignoredbranches.append(ign)
                continue
            if ln.startswith('------'): continue
            res = commitre.search(ln)
            if res:
                exact = res.group(1) ; branch = exact
                #strip git niceness to get branch name
                for sym in ['~','^']:branch = branch.split(sym)[0]
                commits.append([exact,branch,False])
            else:
                if not re.compile('^(\-+)$').search(ln):
                    print('cannot extract',ln)
        #now go over the ignored branches
        if len(ignoredbranches): 
            for ign in set(ignoredbranches):
                st,op = gso('git checkout origin/%s'%(ign)); assert st==0,"checkout origin/%s inside %s returned %s\n%s"%(ign,repodir,st,op)
                st,op = gso('git log --pretty=oneline --since=%s'%(datetime.datetime.now()-datetime.timedelta(days=30)).strftime('%Y-%m-%d')) ; assert st==0
                for lln in op.split('\n'):
                    if lln=='': continue
                    lcid = lln.split(' ')[0]
                    commits.append([lcid,ign,True])
                    #print 'added ign %s / %s'%(lcid,ign)

        cnt=0 ; branches=[]
        print('going over %s commits.'%len(commits))
        for relid,branch,isexact in commits:
            if isexact:
                cmd = 'git show %s | head'%relid
            else:
                cmd = 'git show origin/%s | head'%relid
            st,op = gso(cmd) ; assert st==0,"%s returned %s\n%s"%(cmd,st,op)
            if op.startswith('fatal'):
                raise Exception('%s returned %s'%(cmd,op))
            cres = cre.search(op)
            dres = dre.search(op)
            if not dres: raise Exception(op)
            dt = dres.groups()[0]
            cid = cres.group(1)
            author,email = are.search(op).groups()
            un = cfg.COMMITERMAP(email,author)
            storyres = sre.search(op)
            if storyres:
                task = storyres.group(1)
            else:
                task = None
            cinfo = {'s':dt,'br':[branch],'u':un,'t':task} #'repo':repon, 'cid':cid <-- these are out to save space
            if branch not in branches: branches.append(branch)
            key = '%s/%s'%(repon,cid)

            if key not in excommits: 
                excommits[key]=cinfo
            else:
                if branch not in excommits[key]['br']:
                    excommits[key]['br'].append(branch)
            cnt+=1
            #print '%s: %s/%s %s by %s on task %s'%(dt,repon,branch,cid,un,task)
        print('found out about %s commits, branches %s'%(cnt ,branches))
        os.chdir(prevdir)        
        fp = open(commitsfn,'w')
        json.dump(excommits,fp,indent=True,sort_keys=True) ; fp.close()

def loadmeta(fn):
    if os.path.exists(fn):
        return json.load(open(fn))
    else:
        return {}

def savemeta(fn,dt):
    fp = open(fn,'w')
    json.dump(dt,fp,sort_keys=True,indent=True)
    fp.close()

numonths = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'.split('|')
redt = re.compile('^(Sun|Mon|Tue|Wed|Thu|Fri|Sat) ('+'|'.join(numonths)+') ([0-9]{1,2}) ([0-9]{2})\:([0-9]{2})\:([0-9]{2}) ([0-9]{4}) (\-|\+)([0-9]{4})')

def parsegitdate(s):
    dtres = redt.search(s)
    wd,mon,dy,hh,mm,ss,yy,tzsign,tzh = dtres.groups()
    dt = datetime.datetime(year=int(yy),
                           month=int(numonths.index(mon)+1),
                           day=int(dy),
                           hour=int(hh),
                           minute=int(mm),
                           second=int(ss))
    return dt

def assign_commits(C):
    exc = json.load(open(commitsfn,'r'))
    metas={}
    print('going over commits.')
    for ck,ci in list(exc.items()):

        #HEAD actually means staging in our book.
        branches = [cibr.replace('HEAD','staging') for cibr in ci['br']]
        #check if commit is on staging and exclude from other branches if so
        if 'staging' in branches: branches=['staging']
        if not ci['t']: continue

        repo,cid = ck.split('/')
        t = get_task(C,ci['t'],exc=False)
        
        if not t: 
            strans = get_story_trans()
            if ci['t'] in strans:
                print('translating %s => %s'%(ci['t'],strans[ci['t']]))
                if strans[ci['t']]=='None':
                    continue
                t = get_task(C,strans[ci['t']])
            else:
                print('could not find task %s, which was referenced in %s: %s'%(ci['t'],ck,ci))
                continue

        #metadata cache
        if t['metadata'] not in metas: 
            m = loadmeta(t['metadata'])
            metas[t['metadata']]=m
            m['commits_qty']=0 #we zero it once upon load to be incremented subsequently
        else: m = metas[t['metadata']]

        dt = parsegitdate(ci['s'])

        m['commits_qty']+=1
        if not m.get('last_commit') or dt>=parsegitdate(m['last_commit']): m['last_commit']=ci['s']

        repocommiter = '-'.join([repo,ci['u']])
        if 'commiters' not in m: m['commiters']=[]
        if repocommiter not in m['commiters']: m['commiters'].append(repocommiter)
        
        for cibr in branches:
            repobranch = '/'.join([repo,cibr])
            if 'branches' not in m: m['branches']=[]
            if repobranch not in m['branches']: m['branches'].append(repobranch)

        lastdatekey = '%s-%s'%(repo,ci['u'])
        if 'lastcommits' not in m: m['lastcommits']={}
        if lastdatekey not in m['lastcommits'] or parsegitdate(m['lastcommits'][lastdatekey])<dt:
            m['lastcommits'][lastdatekey]=ci['s']

        for cibr in branches:
            lastbranchkey = '%s/%s'%(repo,cibr)
            if 'branchlastcommits' not in m: m['branchlastcommits']={}
            if lastbranchkey not in m['branchlastcommits'] or parsegitdate(m['branchlastcommits'][lastbranchkey])<dt:
                m['branchlastcommits'][lastbranchkey]=ci['s']

    print('saving.')
    for fn,m in list(metas.items()):
        savemeta(fn,m)
    print('%s metas touched.'%(len(metas)))

def tasks_validate(C,tasks=None,catch=True,amend=False,checkhours=True,checkreponames=True):
    cnt=0 ; failed=0
    tasks = [t for t in tasks if t!=None]
    p = get_participants(cfg.DATADIR,disabled=True)
    firstbad=None
    if tasks:
        tfs = [get_task(C,taskid)['path'] for taskid in tasks]
    else:
        tfs = get_fns(C)
    for tf in tfs:
        try:
            t = parse_fn(tf)
            if checkreponames and t.get('meta') and t['meta'].get('branchlastcommits'):
                for blc in t['meta'].get('branchlastcommits'):
                    try:
                        assert '/' in blc,"%s has no /"%(blc)
                        assert len(blc.split('/'))<=2,"%s has too many /"%(blc)
                        assert 'HEAD' not in blc,"%s has HEAD"%(blc)
                    except Exception as e:
                        if amend:
                            print('amending %s'%e)
                            for fn in ['lastcommits','commits_qty','branchlastcommits','commiters','last_commit','branches']:
                                if t['meta'].get(fn):
                                    del t['meta'][fn]
                            savemeta(t['metadata'],t['meta'])
                        else:
                            raise
            if t.get('meta') and t['meta'].get('commiters'):
                for blc in t['meta'].get('commiters'):
                    br,person = blc.split('-')
                    assert '.' not in person,"bad commiter - %s"%person

            if checkhours and t.get('person_hours'): 
                for person,hrs in t.get('person_hours'):
                    try:
                        assert '@' not in person,"hours in person: %s is bad"%(person)
                    except Exception as e:
                        if amend:
                            print('amending %s'%e)
                            hrsfn = t['metadata'].replace('meta.json','hours.json')
                            hrsm = loadmeta(hrsfn)
                            for hdt,items in list(hrsm.items()):
                                if person in items:
                                    if not firstbad or hdt<firstbad: firstbad=hdt

                            hrsfn = hrsfn
                            assert os.path.exists(hrsfn)
                            savemeta(hrsfn,{})
                        else:
                            raise
            assert t['summary']
            assert t['assigned to']
            assert t['created by']
            assert t['status']
            if t['assigned to'] and t['assigned to']!='None':
                assert t['assigned to'] in p
            if t['created by'] and t['created by']!='None':
                assert t['created by'] in p
            #checking for dupes
            cmd = "find %s -type f -iregex '^([^\]+)/%s$'"%(cfg.DATADIR,'/'.join([t['id'],'task.org']))
            st,op = gso(cmd) ; assert st==0
            dfiles = op.split('\n')
            assert len(dfiles)==1,"%s is not 1 for %s"%(dfiles,cmd)
            #print '%s : %s , %s , %s, %s'%(t['id'],t['summary'] if len(t['summary'])<40 else t['summary'][0:40]+'..',t['assigned to'],t['created by'],t['status'])
            cnt+=1
        except Exception as e:
            if not catch: raise
            print('failed validation for %s - %s'%(tf,e))
            failed+=1

    print('%s tasks in all; %s failed; firstbad=%s'%(cnt,failed,firstbad))
    return failed

def addlink(C,tsaves,tid,r):
    if tid not in tsaves: tsaves[tid]=get_task(C,tid)
    assert r>tid,"%s>%s ?"%(r,tid)
    t = tsaves[tid]
    if 'cross_links' not in t.__dict__:
        t.cross_links=[]
    if r not in t.cross_links:
        tcheck = get_task(C,r)
        print('task.%s -> +%s'%(t._id,r))
        t.cross_links.append(r)
        return True
    return False

def rmlink(C,tsaves,tid,r):
    if tid not in tsaves: tsaves[tid]=get_task(C,tid)
    t = tsaves[tid]
    if t['cross_links'] and r in t.cross_links:
        print('task.%s -> -%s'%(t._id,r))
        t.cross_links.remove(r)
        return True
    return False

def get_karma_receivers(C):
    karma={}
    C.execute("select id,dt,reciever,sum(points) points from karma group by id,dt,reciever order by dt desc")
    return C.fetchall()

def get_karma(C,date,user):
    C.execute("select * from karma where reciever=%s and dt=%s",(user,date))
    return C.fetchall()

def deps_validate(C,tsaves,tid,deps):
    print(('deps_validate',tid,deps))
    t = tsaves[tid]

    # avoid adding task itself as its own dependency
    avoid=[tid]

    # avoid circular dependencies
    C.execute("select tid from tasks_deps_hierarchy where depid=%s",(tid,))
    depids = [d['tid'] for d in C.fetchall()]
    avoid+=depids

    # make sure they indeed are valid tasks
    for d in deps:
        try:
            Task.get(C,d)
        except IndexError:
            avoid.append(d)

    # clean the disallowed deps    
    for av in avoid:
        if str(av) in deps:
            deps.remove(av)
            t.dependencies.remove(av)


    # unique the remainging list
    t.dependencies = list(set(t.dependencies))
    deps = list(set(deps))    

    #print(tid,'just retained deps',t.dependencies)
    return deps

def rewrite(P,C,tid,o_params={},safe=True,user=None,fetch_stamp=None):
    tsaves={} #this dict contains all couchdb task objects we're working with
    tsaves[tid] = get_task(C,tid)
    assert tid
    #print 'working %s'%tid
    clinks = list(set(o_params['cross_links']))
    deps = list(set(o_params['dependencies']))
    t = tsaves[tid]


    #raise Exception('clr',o_params['cross_links_raw'])
    e = [ce.split("-") for ce in o_params['cross_links_raw'].split(",") if ce!='']
    #remove previous cross links
    for cxa in e:
        cxas = sorted(cxa)
        assert len(cxas)==2,"%s wrong length"%cxas
        rmlink(C,tsaves,cxas[0],cxas[1])
    
    #because cross links are bidirectional, we want to always set them on the lower of the pair,
    #the view Task/crosslinks allows us to see the crosslink from both its ends

    clpairs = [sorted([tid,cli]) for cli in clinks]
    for clk,cld in clpairs:
        addlink(C,tsaves,clk,cld)

    params = {
              'status':t['status'],
              'summary':t['summary'],
#              'created_at':t['created_at'], # DO NOT TOUCH CREATED AT
#              'creator':t['creator'], # DO NOT TOUCH CREATOR!
              'tags':t['tags'],
              'assignee':t['assignee'],
              'dependencies':hasattr(t,'dependencies') and t.dependencies or [],
              #'points':t.get('points','?'),
              'informed':hasattr(t,'informed') and t.informed or [],
              'links':t.links,
              'unstructured':t.unstructured.strip(),
              'branches':t.branches,
              'external_id':hasattr(t,'external_id') and t.external_id or None,
              'external_thread_id':hasattr(t,'external_thread_id') and t.external_thread_id or None,
              'external_msg_id':hasattr(t,'external_msg_id') and t.external_msg_id or None,
              }

    for k,v in list(o_params.items()):
        if k in ['cross_links','cross_links_raw','created_at','creator']: continue
        if k not in ['karma','orig_subj','handled_by']: assert k in params,"%s not in %s"%(k,params)
        params[k]=v
    for k,v in list(params.items()):
        if 'cross_links' in k: continue
        if k not in ['informed','external_id','external_thread_id','external_msg_id','karma','orig_subj','handled_by','dependencies']:
            assert hasattr(t,k),"task does not have %s"%k
        if k=='dependencies': v=list(v)
        #print('setattr(',t,k,v,')',type(v))
        setattr(t,k,v)
    deps = deps_validate(C,tsaves,tid,deps)
    #print('deps of tsaves',tid,'is ',tsaves[tid].dependencies)
        
    for tk,ts in list(tsaves.items()):
        print(ts,'save(user=%s)'%user)
        ts.save(P,C,user=user,fetch_stamp=tk==tid and fetch_stamp or None)

def make_demo(iteration,tree=False,orgmode=False):     
    from tree import Tree
    tf = [parse_fn(tf) for tf in get_fns(C,iteration=iteration,recurse=True)]
    def tf_srt(s1,s2):
        rt=cmp(len(s1['id'].split(cfg.STORY_SEPARATOR)),len(s2['id'].split(cfg.STORY_SEPARATOR)))
        if rt!=0: return rt
        return 0
    tf.sort(tf_srt)
    tr = {'children':{}}
    tr2 = Tree('Iteration: '+iteration)
    for s in tf:
        spointer = tr
        spointer2 = tr2
        parts = s['id'].split(cfg.STORY_SEPARATOR)
        #print 'walking parts %s'%parts
        initparts = list(parts)
        joinedparts=[]
        while len(parts):
            prt = parts.pop(0)
            joinedparts.append(prt)
            tsk = get_task(cfg.STORY_SEPARATOR.join(joinedparts))
            tags = (tsk['assigned to'],)+tuple(tsk['tags'])
            summary = (tsk['summary'] if len(tsk['summary'])<80 else tsk['summary'][0:80]+'..')
            if 'priority' in tsk['tags']: summary='_%s_'%summary
            tname = ('[[file:%s][%s]]'%(tsk['path'],prt) if orgmode else prt)+' '+tsk['status']+'\t'+summary+('\t\t:%s:'%(':'.join(tags)) if len(tags) else '')
            tpt = Tree(tname)
            if prt not in spointer['children']: 
                spointer['children'][prt]={'children':{}}
                spointer2.children = spointer2.children+(tpt,)
            spointer=spointer['children'][prt]
            fnd=False
            for ch in spointer2.children:
                if ch.name==tname:
                    spointer2=ch
                    fnd=True
            assert fnd,"could not find \"%s\" in %s, initparts are %s"%(tname,[ch.name for ch in spointer2.children],initparts)
        spointer['item']={'summary':s['summary'],'assignee':s['assigned to'],'status':s['status'],'id':s['id']}
    if tree:
        print(str(tr2))
    else:
        render('demo',{'trs':tr,'iteration':iteration,'rurl':cfg.RENDER_URL},'demo-%s.org'%iteration)
    
def index_assigned(C,tid=None,dirname='assigned',idxfield='assigned to'):
    asgndir = os.path.join(cfg.DATADIR,dirname)
    if tid:
        st,op = gso('find %s -type l -iname %s -exec rm {} \;'%(asgndir,tid.replace('/','.'))) ; assert st==0
        tfs = [get_task(tid)['path']]
    else:
        tfs = get_fns(C)
        st,op = gso('rm -rf %s/*'%(asgndir)) ; assert st==0

    assert os.path.exists(asgndir),"%s does not exist"%asgndir

    print('reindexing %s task files'%(len(tfs)))
    acnt=0
    for fn in tfs:
        #print 'parsing %s'%fn
        pfn = parse_fn(fn,read=False,getmeta=False)
        #print 'parsed %s ; getting task'%pfn['id']
        t = get_task(pfn['id'],read=True)
        #print t['id'],t['assigned to']
        if type(t[idxfield]) in [str,str]:
            myidxs=[t[idxfield]]
        else:
            myidxs=t[idxfield]

        for myidx in myidxs:
            blpath = os.path.join(asgndir,myidx)
            if not os.path.exists(blpath):
                os.mkdir(blpath) 
                assert os.path.exists(blpath)
                # st,op = gso('mkdir %s'%blpath) ; assert st==0
                acnt+=1
            tpath = os.path.join(blpath,t['id'].replace('/','.'))
            lncmd = 'ln -s %s %s'%(fn,tpath)
            #print lncmd
            if not os.path.exists(tpath):
                os.symlink(fn,tpath)
                #st,op = gso(lncmd) ; assert st==0,lncmd
                assert os.path.exists(tpath)
    print('indexed under %s %s'%(acnt,idxfield))
        
def index_tasks(tid=None,reindex_attr=None):
    dnf = {'creators':'created by',
           'assigned':'assigned to',
           'tagged':'tags'}
    if reindex_attr: assert reindex_attr in list(dnf.keys())
    for dn,attr_name in list(dnf.items()):
        if reindex_attr and reindex_attr!=dn: continue
        print('reindexing %s (tid %s)'%(dn,tid))
        fdn = os.path.join(cfg.DATADIR,dn)
        st,op = gso('rm -rf %s/*'%fdn); assert st==0
        index_assigned(tid,dn,attr_name)

def initvars(cfg_ref):
    global commits,commitsfn,commitre,cre,are,sre,dre,cfg
    cfg=cfg_ref
    commits = {}
    commitsfn = os.path.join(cfg.DATADIR,'commits.json')
    commitre = re.compile('\[origin\/([^\]]+)\]')
    cre = re.compile('commit ([0-9a-f]{40})')
    are = re.compile('Author: ([^<]*) <([^>]+)>')
    sre = re.compile('#([0-9'+re.escape(cfg.STORY_SEPARATOR)+']+)')
    dre = re.compile('Date:   (.*)')

if __name__=='__main__':
    import config as cfg    
    initvars(cfg)

    parser = argparse.ArgumentParser(description='Task Control',prog='tasks.py')
    subparsers = parser.add_subparsers(dest='command')

    idx = subparsers.add_parser('reindex')
    idx.add_argument('--reindex-attr',dest='reindex_attr',action='store')

    lst = subparsers.add_parser('list')
    lst.add_argument('--assignee',dest='assignee')
    lst.add_argument('--status',dest='status')
    lst.add_argument('--tag',dest='tag')
    lst.add_argument('--recent',dest='recent',action='store_true')

    gen = subparsers.add_parser('index')

    html = subparsers.add_parser('makehtml')
    html.add_argument('--notasks',dest='notasks',action='store_true')
    html.add_argument('files',nargs='*')

    nw = subparsers.add_parser('new')
    nw.add_argument('--parent',dest='parent')
    nw.add_argument('--assignee',dest='assignee')
    nw.add_argument('--id',dest='id')
    nw.add_argument('--tag',dest='tags',action='append')
    nw.add_argument('summary',nargs='+')

    purge = subparsers.add_parser('purge')
    purge.add_argument('tasks',nargs='+')
    purge.add_argument('--force',dest='force',action='store_true')

    show = subparsers.add_parser('show')
    show.add_argument('tasks',nargs='+')

    move = subparsers.add_parser('move')
    move.add_argument('fromto',nargs='+')

    ed = subparsers.add_parser('edit')
    ed.add_argument('tasks',nargs='+')
    
    pr = subparsers.add_parser('process_notifications')
    pr.add_argument('--nocommit',dest='nocommit',action='store_true')
    pr.add_argument('--nonotify',dest='nonotify',action='store_true')
    pr.add_argument('--renotify',dest='renotify')


    ch = subparsers.add_parser('changes')
    ch.add_argument('--notifications',dest='notifications',action='store_true')
    ch.add_argument('--feed',dest='feed',action='store_true')

    git = subparsers.add_parser('fetch_commits')
    git.add_argument('--nofetch',dest='nofetch',action='store_true')
    git.add_argument('--import',dest='imp',action='store_true')
    git.add_argument('--assign',dest='assign',action='store_true')

    git = subparsers.add_parser('makedemo')
    git.add_argument('--tree',dest='tree',action='store_true')
    git.add_argument('--orgmode',dest='orgmode',action='store_true')

    val = subparsers.add_parser('validate')
    val.add_argument('--nocatch',action='store_true',default=False)
    val.add_argument('--nocheckhours',action='store_true',default=False)
    val.add_argument('--amend',action='store_true',default=False)
    val.add_argument('tasks',nargs='?',action='append')
    
    commit = subparsers.add_parser('commit')
    commit.add_argument('--tasks',dest='tasks',action='store_true')
    commit.add_argument('--metas',dest='metas',action='store_true')
    commit.add_argument('--hours',dest='hours',action='store_true')
    commit.add_argument('--nopush',dest='nopush',action='store_true')

    tt = subparsers.add_parser('time_tracking')
    tt.add_argument('--from',dest='from_date')
    tt.add_argument('--to',dest='to_date')

    rwr = subparsers.add_parser('rewrite')
    rwr.add_argument('--safe',dest='safe',action='store_true')
    rwr.add_argument('tasks',nargs='?',action='append')

    args = parser.parse_args()

    if args.command=='list':
        list_stories(C,assignee=args.assignee,status=args.status,tag=args.tag,recent=args.recent)
    if args.command=='reindex':
        index_tasks(reindex_attr=args.reindex_attr)
    if args.command=='index':
        makeindex()
    if args.command=='makehtml':
        makehtml(notasks=args.notasks,files=args.files)

    if args.command=='new':
        task = add_task(P,C,parent=args.parent,params=args,force_id=args.id,tags=args.tags)
    if args.command=='purge':
        for task in args.tasks:
            purge_task(task,bool(args.force))
    if args.command=='show':
        for task in args.tasks:
            t = get_task(task)
            print(t)
    if args.command=='move':
        tasks = args.fromto[0:-1]
        dest = args.fromto[-1]
        for task in tasks:
            move_task(task,dest)
    if args.command=='edit':
        tfiles = [get_task(t)['path'] for t in args.tasks]
        cmd = 'emacs '+' '.join(tfiles)
        st,op=gso(cmd)
    if args.command=='process_notifications':
        process_notifications(args)
    if args.command=='fetch_commits':
        if args.imp:
            imp_commits(args)
        if args.assign:
            assign_commits(C)
    if args.command=='makedemo':
        make_demo(tree=args.tree,orgmode=args.orgmode)
    if args.command=='validate':
        tasks_validate(C,args.tasks,catch=not args.nocatch,amend=args.amend,checkhours = not args.nocheckhours)
    if args.command=='commit':
        prevdir = os.getcwd()
        os.chdir(cfg.DATADIR)
        st,op = gso('git pull') ; assert st==0
        commitm=[]
        if args.tasks:
            st,op = gso('git add *task.org') ; assert st==0
            commitm.append('tasks commit')
        if args.metas:
            st,op = gso('git add *meta.json') ; assert st==0
            commitm.append('metas commit')
        if args.hours:
            st,op = gso('git add *hours.json') ; assert st==0
            commitm.append('hours commit')
        st,op = gso('git status') ; assert st==0
        print(op)
        cmd = 'git commit -m "%s"'%("; ".join(commitm))
        st,op = gso(cmd) ; 
        if 'no changes added to commit' in op and st==256:
            print('nothing to commit')
        else:
            assert st==0,"%s returned %s\n%s"%(cmd,st,op)
            if not args.nopush:
                cmd = 'git push'
                st,op = gso(cmd) ; assert st==0,"%s returned %s\n%s"%(cmd,st,op)
                print('pushed to remote')
            os.chdir(prevdir)
    if args.command=='rewrite':
        atasks = [at for at in args.tasks if at]
        if not len(atasks):
            tasks = [parse_fn(tf)['id'] for tf in get_fns(C)]
        else:
            tasks = atasks
        for tid in tasks:
            rewrite(P,C,tid,safe=args.safe)

    if args.command=='time_tracking':
        if args.from_date:from_date = datetime.datetime.strptime(args.from_date,'%Y-%m-%d').date()
        else:from_date = (datetime.datetime.now()-datetime.timedelta(days=1)).date()
        if args.to_date:to_date = datetime.datetime.strptime(args.to_date,'%Y-%m-%d').date()
        else:to_date = (datetime.datetime.now()-datetime.timedelta(days=1)).date()
        files = get_fns(C)
        metafiles = [os.path.join(os.path.dirname(fn),'hours.json') for fn in files]
        agg={} ; tagg={} ; sagg={} ; pagg={} ; tcache={}

        maxparts=0
        for mf in metafiles:
            m = loadmeta(mf)
            tf=  parse_fn(mf)
            sid = tf['story']
            sparts = sid.split(cfg.STORY_SEPARATOR)
            tlsid = sparts[0]
            if len(sparts)>maxparts: maxparts=len(sparts)
            for k in m:
                mk = datetime.datetime.strptime(k,'%Y-%m-%d').date()
                if mk>=from_date and mk<=to_date:
                    #print mk,m[k],sid
                    for person,hours in list(m[k].items()):
                        if sid not in agg: 
                            agg[sid]={}
                        if tlsid not in tagg:
                            tagg[tlsid]={}
                        if tlsid not in sagg:
                            sagg[tlsid]={}
                        if person not in pagg:
                            pagg[person]=0

                        if person not in agg[sid]: 
                            agg[sid][person]=0
                        
                        if person not in tagg[tlsid]:
                            tagg[tlsid][person]=0
                        if '--' not in sagg[tlsid]:
                            sagg[tlsid]['--']=0
                            
                        agg[sid][person]+=hours
                        tagg[tlsid][person]+=hours
                        sagg[tlsid]['--']+=hours
                        pagg[person]+=hours

        print('* per-Participant (time tacked) view')
        ptp = PrettyTable(['Person','Hours'])
        ptp.sortby='Hours'
        htot=0
        for person,hours in list(pagg.items()):
            ptp.add_row([person,hours])
            htot+=hours
        ptp.add_row(['TOT',htot])
        print(ptp)

        for smode in ['detailed','tl','sagg']:
            headers = ['Summary','Person','Hours']
            if smode=='detailed':
                tcols = ['Task %s'%i for i in range(maxparts)] + headers
                mpadd=3
                cyc = list(agg.items())
                print('* Detailed view')
            elif smode=='tl':
                tcols = ['Task 0'] + headers
                mpadd=1
                cyc = list(tagg.items())
                print('* Top Level Task view')
            elif smode=='sagg':
                tcols=['Task 0']+ ['Summary','Hours']
                mpadd=0
                cyc = list(sagg.items())
                print('* per-Task view')
            pt = PrettyTable(tcols)
            pt.align['Summary']='l'
            hrs=0
            if smode=='sagg':
                pt.sortby='Hours'
            for sid,people in cyc:
                for person,hours in list(people.items()):
                    if sid not in tcache:
                        tcache[sid] = get_task(sid)
                    td = tcache[sid]
                    summary = td['summary'] if len(td['summary'])<60 else td['summary'][0:60]+'..'
                    sparts = sid.split(cfg.STORY_SEPARATOR)
                    while len(sparts)<maxparts:
                        sparts.append('')
                    dt = [summary,person,"%4.2f"%hours]
                    if smode =='detailed':
                        dt=sparts+dt
                    elif smode=='tl':
                        dt=[sparts[0]]+dt
                    elif smode=='sagg':
                        dt=[sparts[0]]+[summary,hours]
                    hrs+=hours
                    pt.add_row(dt)
                if smode!='sagg':
                    pt.add_row(['--' for i in range(maxparts+mpadd)])
            pt.add_row(['TOT']+['--' for i in range(maxparts+mpadd-2)]+["%4.2f"%hrs])
            print(pt)
                    

def get_parent_descriptions(tid):
    #print 'getting parent descriptions of %s'%tid
    #obtain parent descriptions
    parents = tid.split('/')
    opar=[]
    for i in range(len(parents)-1): opar.append('/'.join(parents[:i+1]))
    parents = [(pid,get_task(pid)['summary']) for pid in opar]
    return parents

def read_current_metastates_worker(items,metainfo=False):
    rt={} ; 
    for i in items:
        if i.get('content'):
            content={
                #'value':org_render(i['content']),
                'raw':i['content'],
                'updated':i['created_at'],
                'updated by':i['creator']}
        for attr,attrv in list(i['attrs'].items()):
            if metainfo:
                rt[attr]={'value':attrv,
                          'updated':i['created_at'],
                          'updated by':i['creator']}
            else:
                rt[attr]=attrv
    return rt

def read_current_metastates(t,metainfo=False):
    content=None
    items = t['journal']
    return read_current_metastates_worker(items,metainfo),content

def read_journal(t,date_limit=None,state_limit=None):
    assert not date_limit,NotImplementedError('date_limit')
    assert not state_limit,NotImplementedError('state_limit')
    try:
        rt = (t['journal'])
    except:
        raise Exception(t)
        # print t
        raise
    return rt

def get_all_journals(day=None):
    return get_journals(day)

def render_journal_content(user,content,metastates):
    now = datetime.datetime.now()
    cnt = """\n** <%s> :%s:\n"""%(now.strftime(date_formats[2]),user)
    if len(metastates):
        cnt+="*** Attributes\n"
        for ms,msv in list(metastates.items()):
            cnt+="- %s :: %s\n"%(ms,msv)
    if len(content):
        cnt+="*** Content\n"
        cnt+=content.replace('\r','')+'\n'
    return cnt

def append_journal_entry(P,C,task,adm,content,metastates={},created_at=None):
    try:
        assert len(metastates) or len(content)
    except TypeError as e:
        print(('metastates',metastates,'content',content))
        raise
    for k,v in list(metastates.items()):
        assert k in cfg.METASTATES_FLAT,"%s not in metastates"%k
        if type(cfg.METASTATES_FLAT[k])==tuple:
            assert v in cfg.METASTATES_FLAT[k],"%s not in %s"%(v,cfg.METASTATES_FLAT[k])
        else:
            inptp,inpstp = cfg.METASTATES_FLAT[k].split('(')
            inpstp = inpstp.split(')')[0]
            if inptp=='INPUT':
                if inpstp=='number': assert re.compile('^([0-9\.]+)$').search(v)
                elif inpstp.lower()=='date':
                    assert re.compile('^([0-9]{4})-([0-9]{2})-([0-9]{2})$').search(v)
                else: raise Exception('unknown inpstp %s'%inpstp)
            elif inptp=='ID': #allow unique identifiers in journal entries
                pass
            else:
                raise Exception('unknown inptp %s'%inptp)
    tid = task._id
    item = {'content':content,'created_at':created_at and created_at or datetime.datetime.now(),'attrs':metastates,'creator':adm}
    task.journal.append(item)
    task.save(P,C,user=adm)

def metastates_agg(C,nosuper=True,tags_limit=[]):
    unqkeys={}
    unqtypes={}
    unqtypes_nosuper={}

    qry = "select * from journal_digest_attrs"
    args = []
    if tags_limit:
        qry+=" where tags && ARRAY[%s]"
        args.append(tuple(tags_limit))
    C.execute(qry,args)        
    ts = C.fetchall()

    cnt=0 ; col=[]
    for t in ts:
        tags = set(t['tags'])
        if len(tags_limit):
            inter = tags.intersection(set(tags_limit))
            if len(inter)<len(tags_limit): continue
        try:
            kv = '='.join([str(t['attr_key']).replace(' ','-'),
                           t['attr_value'].replace(' ','-')])
        except TypeError:
            print(t)
            raise
        if t['id'] not in unqkeys: unqkeys[t['id']]=[]
        if kv not in unqkeys[t['id']]: 
            unqkeys[t['id']].append(kv)
            if kv=='status=TODO': 
                cnt+=1 
                col.append(t['id'])
        #print 'attr',kv.replace('=',' '),t['id']

    #raise Exception(len([t for t in ts if get_task(t['id']).status=='TODO']))
    import itertools
    for tid,kvs in list(unqkeys.items()):
        kvss = ','.join(sorted(kvs))
        if kvss not in unqtypes: unqtypes[kvss]=[]
        if tid not in unqtypes[kvss]: 
            unqtypes[kvss].append(tid)
        else:
            raise Exception('%s already in %s'%(tid,kvss))

    if nosuper:
        for kvs,tids in list(unqtypes.items()):
            unqtypes_nosuper[kvs]=metastates_nosuper_qry(kvs,tids,unqkeys,unqtypes)
            print('%s (%s) => (%s)'%(kvs,len(unqtypes[kvs]),len(unqtypes_nosuper[kvs])))
    #raise Exception(len(unqtypes['status=TODO']),len(unqtypes_nosuper.get('status=TODO',[])))
    return unqkeys,unqtypes,unqtypes_nosuper

def metastates_nosuper_qry(arg,its,unqkeys,unqtypes):
    #print 'starting off with ',len(its)
    nosuper_rt=its
    for unqt,tids in list(unqtypes.items()):
        if unqt==arg: continue
        nosuper_rt=set(nosuper_rt)-set(tids)
        #print 'after removal of',unqt,'we are left with',len(nosuper_rt)
    return nosuper_rt

def metastates_qry(C,arg,nosuper=True,tags_limit=[]):
    sets={}
    try:
        conds = dict([k.split('=') for k in arg.replace('-',' ').split(',')])
    except ValueError:
        print(arg,tags_limit)
        raise
    for cnd,cndv in list(conds.items()):
        qry = "select * from journal_digest_attrs where attr_key=%s and attr_value=%s"
        args=[cnd,cndv]
        C.execute(qry,args)
        ts = C.fetchall()
        cndp = cnd.replace(' ','-')+' '+cndv.replace(' ','-')
        tids=[]
        for t in ts:
            tags = set(t['tags'])
            if len(tags_limit):
                inter = tags.intersection(set(tags_limit))
                if len(inter)<len(tags_limit): continue
            tids.append(t['id'])
        tids = set(tids)
        sets[cndp]=tids
        print(cndp,len(tids))
    setvs = list(sets.values())
    its = setvs[0].intersection(*setvs)
    #print len(its),'intersection items.'
    if nosuper:
        unqkeys,unqtypes,_ = metastates_agg(C,nosuper=False)
        nosuper_rt = metastates_nosuper_qry(arg,its,unqkeys,unqtypes)
    else:
        nosuper_rt = ()
    return sets,its,nosuper_rt


