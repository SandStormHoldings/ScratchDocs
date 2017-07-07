# -*- coding: utf-8 -*-
'''
filedesc: default controller file
'''
from __future__ import print_function
from past.builtins import cmp
from builtins import zip
from builtins import chr
from builtins import str
from builtins import range
from noodles.http import Response
import dateutil.parser
from tasks import gso
from config import STATUSES,RENDER_URL,DATADIR,URL_PREFIX,NOPUSH,NOCOMMIT,METASTATES,APP_DIR
from config_local import WEBAPP_FORCE_IDENTITY
from noodles.http import Redirect,BaseResponse,Response,ajax_response,Error403
from webob import exc
from noodles.templates import render_to
from docs import initvars
from pg import get_repos,get_usernames,hasperm,hasperm_db,get_participants,get_all_journals,get_children,get_journals,get_cross_links,get_task,get_tags
from notif import parse
import config as cfg
initvars(cfg)
from docs import cre,date_formats,parse_attrs,get_fns,get_parent_descriptions,rewrite,get_new_idx,add_task,get_parent,flush_taskfiles_cache,tasks_validate, get_karma, get_karma_receivers, deps_validate
from docs import loadmeta,org_render,parsegitdate,read_current_metastates,read_journal,render_journal_content,append_journal_entry,Task,get_latest,metastates_agg,metastates_qry,P, gantt_info,gantt_info_row
import codecs
import copy
import datetime
import orgparse
import os
import re
import redis
import json
import humanize
from functools import partial,reduce,cmp_to_key


def db(function):
    """ this decorator acquires a db connection from the pool as well as a cursor from the connection and passes both on to its client. """
    def wrap_function(*args, **kwargs):
        with P as p:
            kwargs['P']=p
            kwargs['C']=p.cursor()
            return function(*args, **kwargs)
    return wrap_function


# needed for n_templates/base.html
def basevars(request,P,C,ext):
    u = get_admin(request,'unknown')
    C.execute("select unnest(perms) p from participants where username=%s and active=true",(u,))
    perms = C.fetchall()
    if len(perms):
        perms = [r['p'] for r in perms]
    else:
        perms = []

    rt = {'user':u,
          'hasperm':partial(hasperm,perms),
          'upr':'',
          'C':C,
    }
    rt2 = rt.copy()
    rt2.update(ext)
    return rt2

# task sorting functions/accessories
def srt(t1,t2):
    t1ids = [int(tp) for tp in (t1._id.split('/'))]
    t2ids = [int(tp) for tp in (t2._id.split('/'))]

    t1ids.insert(0,hasattr(t1,'pri') and getattr(t1,'pri') or 0)
    t2ids.insert(0,hasattr(t2,'pri') and getattr(t2,'pri') or 0)
    t1idsc = copy.copy(t1ids)
    t2idsc = copy.copy(t2ids)
    #print('cmp:',t1ids,t2ids)
    while True and len(t1ids) and len(t2ids):
        t1id = t1ids.pop(0)
        t2id = t2ids.pop(0)
        #print 'comparing %s & %s which were extracted from %s, %s'%(t1id,t2id,t1idsc,t2idsc)
        rt= cmp(t1id,t2id)
        if rt!=0: break
    return rt
def srt_crat(t1,t2): return cmp(t1['created_at'],t2['created_at'])
sortmodes={'default':srt,
           'created':srt_crat,
           'id':lambda x,y: cmp(x['_id'],y['_id']),
           'assignee':lambda x,y: cmp(x['assignee'],y['assignee']),
           'summary':lambda x,y: cmp(x['summary'].lower(),y['summary'].lower()),
           'status':lambda x,y: cmp(x['status'],y['status']),
           'parents':lambda x,y: cmp(x['id'],y['id']),
           'pri':lambda x,y: cmp(x['pri'],y['pri']),
}

@ajax_response
@db
def tag_pri(request,P,C):
    adm = get_admin(request,'unknown')
    if not hasperm_db(C,adm,'prioritization'): return Error403('no sufficient permissions for %s'%adm)
    
    qry = "INSERT INTO tags (name, pri) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET pri = %s"
    nm = request.params.get('name')
    val = request.params.get('val')
    with P as p:
        C = p.cursor()
        C.execute(qry,(nm,val,val))
    return {'name':nm,'val':val}
def get_admin(r,d):

    if WEBAPP_FORCE_IDENTITY:
        return WEBAPP_FORCE_IDENTITY
    if not r.headers.get('Authorization'):
        return d
        #raise AuthErr('no authorization found')

    username = re.compile('username="([^"]+)"').search(r.headers.get('Authorization'))
    if username:
        rt= username.group(1)
        rt = rt.split('@')[0].replace('.','_')
        return rt
    return d

@render_to('participants.html')
@db
def participants(request,P,C):
    pts = get_participants(C,sort=True)
    return basevars(request,P,C,{'pts':pts,'request':request})


def asgn(request,
         P,
         C,
         person=None,
         created=None,
         informed=None,
         handled_by=None,
         iteration=None,
         recurse=True,
         notdone=False,
         query=None,
         tag=None,
         newer_than=None,
         tids=None,
         recent=False,
         gethours=False):
    in_tasks = get_fns(C,assignee=person,created=created,handled_by=handled_by,informed=informed,recurse=recurse,query=query,tag=tag,newer_than=newer_than,tids=tids,recent=recent)
    tasks={}
    #print 'got initial ',len(in_tasks),' tasks; cycling'
    for td in in_tasks:
        t = Task(**td['contents'])
        t.pri = td['comb_pri']
        tlp = get_parent(t._id,tl=True)
        assert hasattr(t,'status'),"%s with no status"%t._id
        st = t.status
        if st not in tasks: tasks[st]=[]

        showtask=False
        if not notdone: showtask=True
        if str(t['status']) not in cfg.DONESTATES: showtask=True
        if showtask:
            tasks[st].append(t)

    sortmode = request.params.get('sortby','default')

    for st in tasks:
        tasks[st].sort(key=cmp_to_key(sortmodes[sortmode]),reverse=True)
    return basevars(request,P,C,{'tasks':tasks,'statuses':STATUSES,'request':request,'gethours':gethours})

@render_to('iteration.html')
@db
def assignments(request,P,C,person,gethours):
    if gethours=='False': gethours=False
    rt= asgn(request,P,C,person,gethours=gethours)
    rt['headline']='Assignments for %s'%person
    return rt

@render_to('iteration.html')
@db
def created(request,P,C,person,gethours):
    rt= asgn(request,P,C,created=person,gethours=gethours)
    rt['headline']='Created by %s'%person
    return rt

@render_to('iteration.html')
@db
def informed(request,P,C,person,gethours):
    rt= asgn(request,P,C,informed=person,gethours=gethours)
    rt['headline']='%s informed'%person
    return rt

@render_to('iteration.html')
@db
def handled_by(request,P,C,person,gethours):
    rt= asgn(request,P,C,handled_by=person,gethours=gethours)
    rt['headline']='handled by %s'%person
    return rt

@render_to('iteration.html')
@db
def assignments_mode(request,P,C,person,mode,gethours):
    if mode=='notdone': notdone=True
    else: notdone =False
    rt = asgn(request,P,C,person=person,notdone=notdone,gethours=gethours)
    rt['headline']='Assignments for %s, %s'%(person,mode)
    return rt

def assignments_itn_func(request,P,C,person=None,iteration=None,mode='normal',query=None,tag=None,gethours=False):
    notdone=False
    headline=''
    if mode=='notdone':
        notdone=True
        headline+='Current Tasks'
    else:
        headline+=''
    rt=asgn(request,P,C,person=person,notdone=notdone,query=query,tag=tag,gethours=gethours)
    rt['headline']=headline
    return rt

@render_to('iteration.html')
def assignments_itn(request,person,iteration,mode='normal',tag=None):
    return assignments_itn_func(request,person,iteration,mode,tag=tag)

@render_to('iteration.html')
@db
def index(request,P,C,gethours=False):
    rt= assignments_itn_func(request
                             ,P
                             ,C
                             ,get_admin(request,'unknown')
                             ,mode='notdone'
                             ,gethours=gethours)
    return rt

@ajax_response
@db
def test(request,P,C):
    """ used to debug database pool issues """
    rt= {}
    return rt

@render_to('iteration.html')
@db
def iteration(request,P,C,iteration):
    rt = asgn(request,P,C,iteration=iteration,recurse=False)
    rt['headline']='Iteration %s'%iteration
    return rt

@render_to('iteration.html')
@db
def iteration_all(request,P,C,iteration):
    rt = asgn(request,P,C,iteration=iteration,recurse=True)
    rt['headline']='Iteration %s with all tasks'%iteration
    return rt

@render_to('iteration.html')
@db
def top_level(request,P,C):
    rt = asgn(request,P,C,recurse=False)
    rt['headline']='Top Level'
    rt['status'] = 'PARENT'
    return rt

@render_to('iteration.html')
@db
def storage(request,P,C):
    rt = asgn(request,P,C,recurse=True)
    rt['headline']='Storage'
    rt['status'] = 'STORAGE'
    return rt

@render_to('iteration.html')
@db
def latest(request,P,C,max_days=14,gethours=False):
    rt = asgn(request,P,C,recurse=True,recent=True,newer_than=int(max_days),gethours=gethours)
    rt['headline']='Latest created'
    return rt

@render_to('iteration.html')
@db
def iteration_notdone(request,P,C,iteration):
    rt = asgn(request,P,C,iteration=iteration,recurse=True,notdone=True)
    rt['headline']='Iteration %s with all tasks (and parents) that are not done'%iteration
    return rt

@render_to('karma.html')
@db
def karma(request,P,C):
    adm = get_admin(request,'unknown')
    if not hasperm_db(C,adm,'karma'): return Error403('no sufficient permissions for %s'%adm)

    received={}
    k = get_karma_receivers(C)
    return basevars(request,P,C,{'receivers':k})

@ajax_response
@db
def validate_save(request,P,C,task):
    fstamp = request.params.get('changed_at')
    if fstamp and fstamp!='None': fstamp = datetime.datetime.strptime( fstamp, "%Y-%m-%d %H:%M:%S.%f" )
    else: fstamp=None
    from pg import validate_save
    vs = validate_save(C,task,fstamp,exc=False)
    return {'tid':task,
            'valid':vs[0],
            'changed_at':vs[1],
            'changed_by':vs[2],
    }

@render_to('prioritization.html')
@db
def prioritization(request,P,C):
    adm = get_admin(request,'unknown')
    if not hasperm_db(C,adm,'prioritization'): return Error403('no sufficient permissions for %s'%adm)
    
    fields = ['ages','statuses','assignees','handlers']
    agesl = ['new','recent','old','ancient']
    ages = dict([(agesl[i],chr(ord('a')+i)) for i in range(len(agesl))])
    C.execute("select * from statuses")
    statuses = dict([(r['status'],r['cnt']) for r in C.fetchall()])
    C.execute("select * from assignees")
    assignees = dict([(r['assignee'],r['cnt']) for r in C.fetchall()])
    C.execute("select * from handlers")
    handlers = dict([(r['hndlr'],r['cnt']) for r in C.fetchall()])
    
    rt={'fields':fields,
        'values':{}}
    if not len(request.params):
        setall=True
    else:
        setall=False
    for fn in fields:
        if setall:
            vset = list(locals()[fn].keys())
            if fn=='statuses':
                for ds in cfg.DONESTATES:
                    if ds in vset: vset.remove(ds)
            elif fn=='ages':
                vset.remove('ancient')
                #vset.remove('old')
        else:
            vset = ['-'.join(k.split('-')[1:]) for k in request.params if k.startswith(fn+'-')]

        rt['values'][fn]={'avail':locals()[fn],
                          'set':vset}
    qry ="select * from tasks_pri_comb where 1=1"
    params=[]
    for fn in fields:
        vset1 = rt['values'][fn]['set']
        vsetraw = [v=='None' and None or v for v in vset1]
        vset = tuple(vsetraw)
        if vset and fn=='statuses':
            qry+=" and st in %s"
            params.append(vset)
        elif vset and fn=='assignees':
            qry+=" and asgn in %s"
            params.append(vset)
        elif vset and fn=='handlers':
            qry+=" and hby in %s"
            params.append(vset)
        elif vset and fn=='ages':
            qry+=" and age in %s"
            params.append(vset)
        elif vset:
            raise Exception(fn,vset)
    qry+=" order by comb_pri desc,crat desc "
    #print('executing:',qry,params)
    C.execute(qry,params)
    orders={}
    cnt=0
    assignees={}
    assignee_pri={}
    handlers={}
    statuses={}
    for tp in C.fetchall():
        cnt+=1
        a = tp['asgn']
        if a not in orders: orders[a]=[]
        orders[a].append(tp)

        if a not in assignees:
            assignees[a]=0
            assignee_pri[a]=0
        assignees[a]+=1
        assignee_pri[a]+=tp['comb_pri']
        h = tp['hby']
        if h not in handlers: handlers[h]=0
        handlers[h]+=1
        s = tp['st']
        if s not in statuses: statuses[s]=0
        statuses[s]+=1
    rt['fresh'] = datetime.datetime.now().date()-datetime.timedelta(days=3)
    rt['tasks_cnt']=cnt
    rt['handlers']=handlers
    rt['statuses']=statuses
    rt['assignees']=assignees
    rt['orders'] = orders
    rt['recent'] = datetime.datetime.now()-datetime.timedelta(days=30)
    rt['humanize'] = humanize
    rt['doingstates'] = cfg.DOINGSTATES
    rt['donestates'] = cfg.DONESTATES
    rt['assignee_pri'] = assignee_pri
    return basevars(request,P,C,rt)

@render_to('task_changes.html')
@db
def task_changes(request,P,C,task):
    t=Task.get(C,task)
    diffs = parse(C,[t],supress=True)[::-1]
    return basevars(request,P,C,{'diffs':diffs,'t':t})

@render_to('task.html')
@db
def task(request,P,C,task,rev=None):
    # fetch_stamp is a hidden form input used to protect task updates against overwrite by older forms of the task submitted
    fstamp = request.params.get('changed_at')
    if fstamp and fstamp!='None': fstamp = datetime.datetime.strptime( fstamp, "%Y-%m-%d %H:%M:%S.%f" )
    else: fstamp=None

    now = datetime.datetime.now()
    if task.endswith('/'): task=task[0:-1]
    gwu = cfg.GITWEB_URL
    if task.startswith('new/'):
        under='/'.join(task.split('/')[1:])
        task='new'
    else:
        under=None
    msg=None
    adm = get_admin(request,'unknown')
    repos = get_repos(C)
    usernames = get_usernames(C)

    tags=[] ; links=[] ; informed=[] ; branches=[] ;
    cross_links_raw = get_cross_links(C,task)
    cross_links=[]
    dependencies=[]
    for k,v in list(request.params.items()):
        if k.startswith('tag-'):
            tn = k.replace('tag-','')
            if tn=='new':
                for nt in [nt.strip() for nt in v.split(',') if nt.strip()!='']:
                    tags.append(nt)
            else:
                tags.append(tn)
        if k.startswith('link-'):
            tn = k.replace('link-','')
            if tn in ['new-url','new-anchor']:
                continue #raise Exception('newlink')
            else:
                links.append({'url':v,'anchor':tn})
        if k.startswith('informed-'):
            tn = k.replace('informed-','')
            if tn=='new': continue
            informed.append(tn)
        if k.startswith('branches-'):
            tn = k.replace('branches-','')
            if tn in ['new-repo','new-branch']: continue
            branches.append(tn)
        if k.startswith('cross_link-'):
            cln = k.replace('cross_link-','')
            cross_links.append(cln)
        if k.startswith('dependency-'):
            dln = k.replace('dependency-','')
            dependencies.append(dln)
    lna = request.params.get('link-new-anchor')
    lnu = request.params.get('link-new-url')
    ncl = request.params.get('add-cross_link')
    ndl = request.params.get('add-dependency')

    if task and task!='new':
        karma = getattr(get_task(C,task),'karma',{})
    else:
        karma = {}

    nkarma = request.params.get('karma-new')
    if nkarma:
        kdt = datetime.datetime.now().date().strftime('%Y-%m-%d')
        nkarmaval = request.params.get('karma-plus') and 1 or -1
        # find out what's our expense for today
        mykarma = sum([k['value'][1] for k in get_karma(C,kdt,adm)])
        if (nkarmaval>0 and mykarma<cfg.KARMA_POINTS_PER_DAY) or nkarmaval<0:
            if kdt not in karma: karma[kdt]={}
            if adm not in karma[kdt]: karma[kdt][adm]={}
            if nkarma not in karma[kdt][adm]: karma[kdt][adm][nkarma]=0
            newval = karma[kdt][adm][nkarma]+nkarmaval
            if newval>=0: karma[kdt][adm][nkarma]=newval

    if ncl:
        for ncli in ncl.split(','):
            cross_links.append(ncli)
    if ndl:
        for ndli in ndl.split(','):
            dependencies.append(ndli)

    if lna and lnu:
        links.append({'anchor':lna,'url':lnu})

    inn = request.params.get('informed-new')
    if inn and inn not in informed:
        informed.append(inn)

    nrb = request.params.get('branches-new-branch','')
    assert '/' not in nrb,"branch name may not contain '/'"
    if nrb: branches.append(request.params.get('branches-new-repo')+'/'+nrb)


    tags = list(set([tag for tag in tags if tag!='']))

    uns = request.params.get('unstructured','').strip()
    if len(uns) and not uns.startswith('**'):
        uns='** Details\n'+uns
    assignees=[request.params.get('assignee')]

    if request.params.get('id') and request.params.get('id')!='None':
        t = get_task(C,request.params.get('id'))
        assignees.append(t.assignee)
        tid = request.params.get('id')
        o_params = {'summary':request.params.get('summary'),
                    'karma':dict(karma),
                    'tags':tags,
                    'status':request.params.get('status'),
                    'assignee':request.params.get('assignee'),
                    'handled_by':request.params.get('handled_by'),
                    'unstructured':uns,
                    'links':links,
                    'cross_links_raw':request.params.get('cross_links'),
                    'cross_links':cross_links,
                    'dependencies':dependencies,
                    'informed':informed,
                    'branches':branches}
        print(o_params)
        rewrite(P,C,tid,o_params,safe=False,user=adm,fetch_stamp=fstamp)
        t = get_task(C,tid)
        cross_links_raw = get_cross_links(C,tid)
        if request.params.get('content-journal'):
            tj = get_task(C,task)
            metastates={}
            append_journal_entry(P,C,tj,adm,request.params.get('content-journal'),metastates)
        assert request.params.get('id')



    if request.params.get('create'):
        o_params = {'summary':request.params.get('summary'),
                    'status':request.params.get('status'),
                    'assignee':request.params.get('assignee'),
                    'creator':get_admin(request,'unknown'),
                    'handled_by':request.params.get('handled_by'),
                    'unstructured':uns,
                    'links':links,
                    'informed':informed,
                    'branches':branches}
        if request.params.get('under'):
            parent = request.params.get('under')
        else:
            parent=None
        rt = add_task(P,C,parent=parent,params=o_params,tags=tags,user=adm)
        redir = '/'+URL_PREFIX+rt._id
        print('redircting to %s'%redir)
        rd = Redirect(redir)
        return rd
    if task=='new':
        ch=[]
    else:
        #raise Exception('eff off',task)
        #print('getting children')
        ch = get_children(C,task)
        sortmode = request.params.get('sortby','default')
        ch.sort(key=cmp_to_key(sortmodes[sortmode]),reverse=True)
        print(('got',len(ch),'kids'))

    if task=='new':
        t = Task(created_at=None,
                 summary='',
                 unstructured='',
                 status='TODO',
                 assignee=adm,
                 creator=adm,
                 tags=[],
                 links=[],
                 branches=[],
                 karma={},
                 journal=[])
        opar=[]
        gantt_labels={} ; gantt={}
        changed_at=None
    else:
        gantt_labels,gantt = gantt_info(C,task)
        C.execute("select changed_at from tasks where id=%s",(task,))
        fo = C.fetchone()
        if fo:
            changed_at = fo['changed_at']
        else:
            changed_at = None
        if rev:
            t = Task.get_rev(C,task,rev)
        else:
            t = get_task(C,task)
        par = task ; parents=[]
        parents = task.split('/')
        opar = []
        for i in range(len(parents)-1):
            opar.append('/'.join(parents[:i+1]))
    parents = [(pid,get_task(C,pid)['summary']) for pid in opar]
    prt = get_usernames(C)
    metastates,content = read_current_metastates(t,True)
    zerodelta = datetime.timedelta(seconds=0)
    if gantt.get('t') and gantt.get('we'):
        remaining_hours = gantt.get('we')-gantt.get('t')
    else:
        remaining_hours=zerodelta
    #journal
    jitems = t.journal
    dependencies = getattr(t,'dependencies',[])
    branchtargets=[(re.compile("pre"),"preproduction"),
                   (re.compile("prod"),"production"),
                   (re.compile(".*"),"staging")]
    btgts={}
    for br in t.branches:
        for ptn,tgt in branchtargets:
            ptnres = ptn.search(br.split("/")[1])
            #print 'ptnres of',br,'in',tgt,'is',ptnres
            if ptnres: 
                if tgt not in btgts: btgts[tgt]=[]
                btgts[tgt].append(br)
                break

    C.execute("select * from tasks_pri_comb_lean where id=%s",(task,))
    pri = C.fetchall()
    if len(pri):
        pr = pri[0]
        pri = pr['tot_pri']
        dep_pri = pr['dep_pri']
    else:
        pri=0
        dep_pri=0

    C.execute("select depid,path_info from tasks_deps_hierarchy where tid=%s",(t._id,))
    fulldeps = [d for d in C.fetchall() if d['depid'] not in dependencies]
    C.execute("select tid,path_info from tasks_deps_hierarchy where depid=%s",(t._id,))
    dependants = [d for d in C.fetchall()]

    return basevars(request,P,C,{'task':t,
                                 'rev':rev,
                                 'changed_at':changed_at,
                                 'pri':pri,
                                 'dep_pri':dep_pri,
                                 'gantt':gantt,
                                 'gantt_labels':gantt_labels,
                                 'zerodelta':zerodelta,
                                 'branches_by_target':btgts,
                                 'get_task':partial(get_task,C),
                                 'cross_links':cross_links_raw,
                                 'dependencies':dependencies,
                                 'fulldeps':fulldeps,
                                 'dependants':dependants,
                                 'remaining_hours':remaining_hours,
                                 'total_hours':0,
                                 'j':{'%s existing entries'%t._id:jitems},
                                 'gwu':gwu,
                                 'url':RENDER_URL,
                                 'statuses':STATUSES,
                                 'participants':prt,
                                 'usernames':usernames,
                                 'msg':msg,
                                 'children':ch,
                                 'repos':repos,
                                 'parents':parents,
                                 'request':request,
                                 'metastates':metastates,
                                 'possible_metastates':cfg.METASTATES,
                                 'colors':cfg.METASTATES_COLORS,
                                 'overrides':cfg.METASTATES_OVERRIDES,
                                 'karma_per_day':cfg.KARMA_POINTS_PER_DAY,
                                 'diff_branches':cfg.DIFF_BRANCHES,
                                 'under':under,
                                 'humanize':humanize,
                                 'now':now,
                                 'reduce':reduce,
    })

@render_to('tags.html')
@db
def tags(request,P,C):
    tags = get_tags(C)
    tags_pri={}
    with P as p:
        C = p.cursor()
        C.execute("select * from tags")
        fa = C.fetchall()
        for tr in fa:
            tags_pri[tr['name']]=tr['pri']
    tags = list(tags.items())
    
    tags.sort(key=lambda x:x[1],reverse=True)
    rt = {'tags':tags,'pri':tags_pri}

    return basevars(request,P,C,rt)

@render_to('iteration.html')
@db
def bytag(request,P,C,tag):
    rt= assignments_itn_func(request,
                             P,
                             C
                             ,person=None
                             ,iteration=None
                             ,tag=tag
                             ,mode='normal')
    return rt

@render_to('iteration.html')
@db
def search(request,P,C):
    rt= assignments_itn_func(request,P,C
                                ,person=None
                                ,iteration=None
                                ,mode='normal'
                                ,query=request.params.get('q'))
    rt['headline']='Search results for "%s"'%request.params.get('q')
    return rt


@render_to('journal.html')
@db
def global_journal(request,P,C,creator=None,day=None,groupby=None,state=None):
    adm = get_admin(request,'unknown')
    ai = []
    if day=='current': 
        daya=datetime.datetime.now().date() #strftime('%Y-%m-%d')
        day = [daya,daya]
    elif day:
        if ':' in day:
            days = day.split(':')
            daya = datetime.datetime.strptime(days[0],'%Y-%m-%d').date()
            dayb = datetime.datetime.strptime(days[1],'%Y-%m-%d').date()
            day = [daya,dayb]
        else:
            daya = datetime.datetime.strptime(day,'%Y-%m-%d').date()
            day = [daya,daya]

    print('obtaining journals')
    gaj = get_all_journals(C,day=day,creator=creator)
    print('obtained; reading %s journals'%len(gaj))
    for jt in gaj:
        jtd = jt
        jt = get_task(C,jt['tid'])
        ji = [jtd]
        if creator: ji = [i for i in ji if i['creator']==creator]
        if state: 
            sk,sv = state.split('=')
            ji = [i for i in ji if dict(i)['attrs'].get(sk)==sv]
        #print('ji=',ji,type(ji))
        for jii in ji:
            jii['tid']=jt._id
        #print('appending entry',ji,'to list')
        ai+=ji

    print('finished reading. sorting')
    ai.sort(key=lambda x:x['created_at'])
    print('sorted')
    if groupby:
        rt={}
        for i in ai:
            assert groupby in i
            k = 'entries for %s'%i[groupby]
            if k not in rt: 
                rt[k]=[]
            rt[k].append(i)

        return basevars(request,P,C,{'j':rt,'task':None,'groupby':groupby})
    else:
        return basevars(request,P,C,{'j':{'all':ai},'task':None,'grouby':None})

@render_to('metastates.html')
@db
def metastates(request,P,C,tags=''):
    tags = [ts for ts in tags.split(',') if ts!='']
    unqkeys,unqtypes,unqtypes_nosuper = metastates_agg(tags_limit=tags)

    #assert unqtypes!=unqtypes_nosuper
    
    return basevars(request,P,C,{'unqtypes':unqtypes,
                             'tags':tags,
                             'unqtypes_nosuper':unqtypes_nosuper})

@render_to('iteration.html')
@db
def metastate(request,P,C,state,tags=''):
    tags = [ts for ts in tags.split(',') if ts!='']
    res = metastates_qry(state,tags_limit=tags)

    excl=False
    if request.params.get('exclusive'):excl=True

    if excl:
        tids = res[2]
    else:
        tids = res[1]
    rt = asgn(request,P,C,tids=tids)
    rt['headline'] = '%s tasks %s belonging to state %s%s'%(len(tids),excl and 'exclusively' or '',",".join(list(res[0].keys())),(tags and ", having tags "+(",".join(tags)) or ""))
    return rt

@render_to('incoming.html')
@db
def incoming(request,P,C,tags=[],limit=300):
    if type(tags) in [str,str]:
        tags = tags.split(",")

    adm = get_admin(request,'unknown')    
    newer_than = (datetime.datetime.now()-datetime.timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%S')
    t = get_latest(C,tags=tags,newer_than=newer_than,limit=limit)
    return basevars(request,P,C,{'tasks':t,
                             'now':datetime.datetime.now(),
                             'humanize':humanize,
                             're':re,
                             'user':adm,
                             'tags':tags,
                             'newer_than':newer_than,
                             'get_task':partial(get_task,C)
    })

@ajax_response
@db
def gantt_save(request,P,C):
    o = json.loads(request.params.get('obj'))
    with P as p:
        C = p.cursor()
        C.execute("select * from gantt where tid in %(items)s",{'items':tuple([d['id'] for d in o['data']])})
        gts = C.fetchall()
    for g in gts:
        t = Task.get(C,g['tid'])
        t['gantt_links']=[]
        t.save()
    for l in o['links']:
        s = Task.get(C,l['source'])
        if 'gantt_links' not in s: s['gantt_links']=[]
        s['gantt_links'].append(l)
        s.save()
    
    return {'res':'ok'}

                      
@render_to('time_tracking_dashboard.html')
@db
def time_tracking_dashboard(request,P,C,rangeback='7 day',persons=None,mode='provider',tids=None):
    adm = get_admin(request,'unknown')
    if not hasperm_db(C,adm,'gantt'): return Error403('no sufficient permissions for %s'%adm)

    if persons:
        cond = "dt>=now()-interval '%s' and provider in (%s)"%(rangeback,",".join(["'%s'"%p for p in persons.split(",")]))
    else:
        cond = "dt>=now()-interval '%s'"%rangeback
    # TODO: allow a tid rows mode
    # if tids:
    #     cond += " and ("+(" or ".join([" tids=any('%s')"%tid for tid in tids.split(",")])+")")
    with P as p:
        C = p.cursor()
        qry = "select provider,sum(tracked),min(dt),max(dt) from tracking_by_day where %s group by provider order by sum(tracked) desc"%cond
        C.execute(qry)
        trackers = C.fetchall()
        C.execute("select unnest(tids) tid,sum(tracked),min(dt),max(dt) from tracking_by_day where %s group by unnest(tids) order by sum(tracked) desc"%cond)
        tids = C.fetchall()
        qry = "select tbd.*,tbd.dt::timestamp dtt,t.contents->>'status' status,t.contents->>'summary' summary from tracking_by_day tbd,tasks t where t.id=any(tbd.tids) and %s order by provider,dt asc,tbd.tracked asc"%cond
        print(qry)
        C.execute(qry)
        tasks = C.fetchall()
    tasks_t = [{
        'startDate':t['dtt'].isoformat(),
        'startDate_raw':t['dtt'],
        'endDate':(t['dtt']+t['tracked']).isoformat(),
        'endDate_raw':(t['dtt']+t['tracked']),
        'tracked_raw':t['tracked'],
        'tracked':"%4.2f"%(float(t['tracked'].seconds)/60/60),
                'taskName':t['provider'], #",".join(t['tids']),
                'descr':",".join(t['tids']),
        'summary':t['summary'],
                'status':t['status']} for t in tasks]

    dates = set([t['startDate_raw'].date() for t in tasks_t])
    providers = set([t['taskName'] for t in tasks_t])
    

    tasks_rt=[]
    for p in providers:
        for d in dates:
            #print('going over provider, task',p,d)
            tasks_p = [x for x in tasks_t if x['taskName']==p and x['startDate_raw'].date()==d]
            inc=datetime.timedelta(0)
            for i in range(1,len(tasks_p)):
                pt = tasks_p[i-1]
                t = tasks_p[i]
                assert pt['taskName']==t['taskName'] and t['startDate_raw'].date()==pt['startDate_raw'].date(),"%s != %s"%(pt,t)
                inc+=pt['tracked_raw']
                try:
                    t['startDate_raw']+=inc
                    t['endDate_raw']+=inc

                    t['startDate']=t['startDate_raw'].isoformat()
                    t['endDate']=t['endDate_raw'].isoformat()
                except KeyError:
                    print((t,pt))
                    raise
            tasks_rt+=tasks_p
            #print('len of tasks_rt, increased by',len(tasks_rt),len(tasks_p))
                
    for t in tasks_t:
        for fn in ['tracked','startDate','endDate']:
            del t['%s_raw'%fn]

        
    return basevars(request,P,C,{'providers':[t['provider'] for t in trackers],
                                 'tids':[t['tid'] for t in tids],
                                 'mode':mode,
                                 'rangeback':rangeback,
                                 'tasks':tasks_rt,
                                 'json':json})

@render_to('gantt.html')
@db
def gantt(request,P,C):
    adm = get_admin(request,'unknown')
    if not hasperm_db(C,adm,'gantt'): return Error403('no sufficient permissions for %s'%adm)    
    res = C.execute("select id from tasks where show_in_gantt=false")
    fa = C.fetchall()
    dismissed = [r['id'] for r in fa if r]

    C.execute("select * \
from gantt where \
(we is not null and t is not null ) and ( (t_l>=now()-interval '2 weeks' or c_l>=now()-interval '2 weeks'))")
    #and created_at>=now()-interval '12 month'
    res = C.fetchall()
    print((len(res),'initial tasks fetched'))

    # retrieve missing parents?
    while True:
        missing = set([r['parent_id'] for r in res if
                       r['parent_id'] and
                       r['parent_id'] not in dismissed and
                       r['parent_id'] not in [r2['tid'] for r2 in res]])
        print(('calculated',len(missing),'missing parents:',missing))

        if not len(missing): break        
        #C.execute("select * from gantt where tid ANY %s",(list(missing),))
        C.execute("select * from gantt where tid in %(missing)s",{'missing':tuple(missing,)})
        res+=C.fetchall()


    tasks=[]
    links=[]    
    for r in res:
        gr = gantt_info_row(r,excl=())

        created_at=r['created_at']
        tid=r['tid']
        parent_id=r['parent_id']
        summary=r['summary']
        status=r['status']
        we=r['we']
        fd=r['finish_date']
        t=r['t'] # tracking
        t_f=r['t_f']
        t_l=r['t_l']
        c=r['c']
        c_f=r['c_f']
        c_l = r['c_l']
        assert re.compile('^([0-9\/]{3,})$').search(tid),Exception("got bad tid",tid,"from ",r)
        start_date = gr['taf'][0]
        
        if parent_id in dismissed: parent=None
        else: parent=parent_id
        text = summary #'%s:%s:%s'%(tid,gr['dt'],summary)
        nstart_date = start_date and start_date.strftime('%d-%m-%Y %H:%I') or None
        apnd = {'id':tid,
                'summary':summary,
                'status':status,
                'text':tid,
                'start_date':nstart_date, # when was it in fact started to be worked on
                'duration':gr['dur'], # total REAL or estimated duration
                'progress':gr['ce'], # progress estimation
                'parent':parent
        }
        #if parent_id in dismissed: raise Exception(apnd)
        tasks.append(apnd)
        ct = Task.get(C,tid)
        try:
            for tl in ct['gantt_links']:
                links.append(tl)
        except KeyError as e:
            pass
    
    return basevars(request,P,C,{'tasks':json.dumps({'data':tasks,
                                                 'links':links
    })})



@render_to('task_commits.html')
def task_commits(request,task):
    qry="""select * from
(select 
*,
json_object_keys(stats->'tids') tid,
cast(stats->>'ladds' as integer) ladds
from commits
where automergeto='' and mergefrom='')
foo where
tid=%s
order by created_at
"""
    C.execute(qry,(task,))
    return {'commits':C.fetchall()}

@ajax_response
def commit_validity(request,repo,rev):
    qry = "update commits set invalid=%s where repo=%s and rev=%s"
    arr = (request.params.get('invalid')=='true' and True or False,
           repo,
           rev)

    C.execute(qry,arr)
    P.commit()
    return {'result':0}

@render_to('queue.html')
@db
def queue(request,P,C,assignee=None,archive=False,metastate_group='merge'):
    #print('queue()')
    if assignee=='me':
        assignee=get_admin(request,'unknown')
    queue={}
    #print('get_journals()')
    gj = get_journals(P,C,
                      assignee=assignee,
                      metastate_group=metastate_group,
                    archive=archive
    )
    for tj in gj:
        t = tj['contents']
        tid = t['_id']
        #print('going over task',tid)
        cm,content = read_current_metastates(tj['contents'],True)

        #skip this task if has no metastates relevant to us
        relevant_metastates=False
        for cmk in cm:
            if cmk in cfg.METASTATES[metastate_group]:
                relevant_metastates=True
                break
        if not relevant_metastates: continue
        #print 'reading journal'
        jitems = read_journal(t)
        lupd = sorted(list(cm.values()),key=lambda x:x['updated'],reverse=True)
        if len(lupd): lupd=lupd[0]['updated']
        else: lupd=None
        #any journal update takes precedence
        if len(jitems):
            try:
                jlupd = jitems[-1]['created_at']
            except:
                raise Exception(jitems[-1])
            if not lupd or jlupd >=lupd:
                lupd = jlupd
        #assert t.get('total_hours')!='None'
        #print 'adding to queue'
        queue[tid]={'states':dict([(cmk,cmv['value']) for cmk,cmv in list(cm.items())]),
                    #'total_hours':t.get('total_hours',0),
                    'fullstates':cm,
                    'last updated':lupd,
                    'status':t['status'],
                    'summary':t['summary'],
                    'last entry':content,
                    'tags':t['tags'],
                    'assignee':t['assignee'],
                    'merge':[l['url'] for l in t['links'] if l['anchor']=='merge doc'],
                    'job':[l['url'] for l in t['links'] if l['anchor']=='job'],
                    'specs':[l['url'] for l in t['links'] if l['anchor']=='specs']}
    queue = list(queue.items())
    qsort = cmp_to_key(
        lambda x1,x2: 
        cmp((x1[1]['last updated'] and datetime.datetime.strptime(x1[1]['last updated'].split('.')[0],'%Y-%m-%dT%H:%M:%S') or datetime.datetime(year=1970,day=1,month=1)),
        (x2[1]['last updated'] and datetime.datetime.strptime(x2[1]['last updated'].split('.')[0],'%Y-%m-%dT%H:%M:%S') or datetime.datetime(year=1970,day=1,month=1))))
    queue.sort(key=qsort,reverse=True)


    metastate_url_prefix = dict (list(zip(list(cfg.METASTATE_URLS.values()),list(cfg.METASTATE_URLS.keys()))))[metastate_group]
    #print('rendering')
    return basevars(request,P,C,{'queue':queue,
            'metastate_group':metastate_group,
            'metastate_url_prefix':metastate_url_prefix,
            'metastates':METASTATES,
            'colors':cfg.METASTATES_COLORS,
            'overrides':cfg.METASTATES_OVERRIDES})


@render_to('journal.html')
@db
def journal(request,P,C,task):
    t = get_task(C,task)
    jitems = read_journal(t)
    return basevars(request,P,C,{'task':t,'j':{'%s existing entries'%t._id:jitems},'metastates':METASTATES})

@render_to('task_history.html')
@db
def history(request,task):
    t = get_task(C,task)
    st,op = gso('git log --follow -- %s'%(os.path.join(cfg.DATADIR,task,'task.org'))) ; assert st==0
    commitsi = cre.finditer(op)
    for c in commitsi:
        cid = c.group(1)
        url = '%(gitweb_url)s/?p=%(docs_reponame)s;a=commitdiff;h=%(cid)s'%{'cid':cid,'gitweb_url':cfg.GITWEB_URL,'docs_reponame':cfg.DOCS_REPONAME}
        op = op.replace(cid,"<a href='%(url)s'>%(cid)s</a>"%{'cid':cid,'url':url})
    
    t['summary'] = ''
    rt = basevars(request,P,C,{'op':op,'task':t,'request':request})
    return rt

def feed_worker(request,user=None):
    if not user: user = get_admin(request,'unknown')
    r = redis.Redis('localhost')
    f = r.get('feed_'+user)
    if not f: f='[]'
    lf = json.loads(f)
    nw = datetime.datetime.now()
    for fe in lf:
        fe['when'] = datetime.datetime.strptime( fe['when'], "%Y-%m-%dT%H:%M:%S" )
        fe['delta'] = nw - fe['when']
    return {'feed':lf,'gwu':cfg.GITWEB_URL,'docs_repo':cfg.DOCS_REPONAME}

@render_to('feed_ajax.html')
def feed(request,user=None):
    return feed_worker(request,user)

@render_to('feed_fs.html')
def feed_fs(request,user=None):
    return feed_worker(request,user)

@ajax_response
@db
def show_in_gantt(request,P,C,task):
    frm=(request.params.get('show_in_gantt')=='true' and True or False,
         task)
    C.execute("update tasks set show_in_gantt=%s where id=%s",frm);
    P.commit()
    return {'status':'ok'}

@ajax_response
@db
def metastate_set(request,P,C):
    k = request.params.get('k')
    v = request.params.get('v')
    spl = k.split('-')
    tid = spl[1]
    msk = '-'.join(spl[2:])
    #_,tid,msk = 

    adm = get_admin(request,'unknown')
    #special case
    if msk=='work estimate':
        t = get_task(C,tid)
        #print '%s = %s + %s'%(msk,t['total_hours'],v)
        #v = "%4.2f"%(float(t.get('total_hours',0))+float(v))
    else:
        t =  get_task(C,tid)

    print('setting %s.%s = %s'%(tid,msk,v))
    append_journal_entry(P,C,t,adm,'',{msk:v})
    return {'status':'ok'}

def favicon(request):
    response = BaseResponse()
    response.headerlist=[('Content-Type', 'image/x-icon')]
    f = open(os.path.join(APP_DIR,'favicon.ico'),'rb').read()
    response.body = f
    return response

def assets(request, r_type=None, r_file=None):
    map = {
        'css': 'text/css',
        'js': 'application/javascript',
        'fonts': 'application/octet-stream',
        'img': 'image/*',
    }
    fname = os.path.join(APP_DIR,'/'.join(['assets', r_type, r_file]))

    if r_type not in map:
        return HTTPNotFound(fname)
    if r_file is None:
        return HTTPNotFound(fname)

    try:
        response = BaseResponse()
        f = open(fname,'rb').read()
        response.headerlist=[('Content-Type', map[r_type])]
        response.body = f
        return response
    except:
        return exc.HTTPNotFound(fname)

    
