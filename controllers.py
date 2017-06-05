# -*- coding: utf-8 -*-
'''
filedesc: default controller file
'''
from noodles.http import Response

import dateutil.parser
from tasks import gso
from config import STATUSES,RENDER_URL,DATADIR,URL_PREFIX,NOPUSH,NOCOMMIT,METASTATES,APP_DIR
from config_local import WEBAPP_FORCE_IDENTITY
from noodles.http import Redirect,BaseResponse,Response,ajax_response,Error403
from webob import exc
from noodles.templates import render_to
from docs import initvars
from pg import get_repos,get_usernames,hasperm,get_participants,get_all_journals,get_children
import config as cfg
initvars(cfg)
from docs import cre,date_formats,parse_attrs,get_fns,get_parent_descriptions,get_task,rewrite,get_new_idx,add_task,get_parent,flush_taskfiles_cache,tasks_validate, get_karma, get_karma_receivers
from docs import loadmeta,org_render,parsegitdate,read_current_metastates,read_journal,render_journal_content,append_journal_entry,get_journals,get_tags,Task,get_latest,metastates_agg,metastates_qry,P, gantt_info,gantt_info_row
from couchdb import get_cross_links
import codecs
import copy
import datetime
import orgparse
import os
import re
import redis
import json
import humanize
from functools import partial


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
    
    rt = {'user':u,
          'hasperm':partial(hasperm,C,u)}
    rt2 = rt.copy()
    rt2.update(ext)
    return rt2

# task sorting functions/accessories
def srt(t1,t2):
    t1ids = [int(tp) for tp in (t1._id.split('/'))]
    t2ids = [int(tp) for tp in (t2._id.split('/'))]

    t1ids.insert(0,int('priority' in t1['tags']))
    t2ids.insert(0,int('priority' in t2['tags']))
    t1idsc = copy.copy(t1ids)
    t2idsc = copy.copy(t2ids)
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
           'id':lambda x,y: cmp(x['id'],y['id']),
           'assignee':lambda x,y: cmp(x['assignee'],y['assignee']),
           'summary':lambda x,y: cmp(x['summary'].lower(),y['summary'].lower()),
           'status':lambda x,y: cmp(x['status'],y['status']),
           'parents':lambda x,y: cmp(x['id'],y['id']),
}

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
    in_tasks = get_fns(assignee=person,created=created,handled_by=handled_by,informed=informed,recurse=recurse,query=query,tag=tag,newer_than=newer_than,tids=tids,recent=recent)
    tasks={}
    print 'got initial ',len(in_tasks),' tasks; cycling'
    for t in in_tasks:
        tlp = get_parent(t._id,tl=True)
        assert hasattr(t,'status'),"%s with no status"%t._id
        st = t['status']
        #print 'st of %s setting to status of tlp %s: %s'%(t._id,tlp,st) 
        if st not in tasks: tasks[st]=[]

        showtask=False
        if not notdone: showtask=True
        if str(t['status']) not in cfg.DONESTATES: showtask=True
        if showtask:
            tasks[st].append(t)

    sortmode = request.params.get('sortby','default')

    for st in tasks:
        tasks[st].sort(sortmodes[sortmode],reverse=True)
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
    if not hasperm(C,adm,'karma'): return Error403('no sufficient permissions for %s'%adm)    
    received={}
    k = get_karma_receivers()
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

@render_to('task.html')
@db
def task(request,P,C,task):
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
    cross_links_raw = get_cross_links(task)
    cross_links=[]

    for k,v in request.params.items():
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
                links.append({'url':v,'anchor':unicode(tn,'utf-8')})
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
    lna = request.params.get('link-new-anchor')
    lnu = request.params.get('link-new-url')
    ncl = request.params.get('add-cross_link')

    if task and task!='new':
        karma = getattr(get_task(task),'karma',{})
    else:
        karma = {}

    nkarma = request.params.get('karma-new')
    if nkarma:
        kdt = datetime.datetime.now().date().strftime('%Y-%m-%d')
        nkarmaval = request.params.get('karma-plus') and 1 or -1
        # find out what's our expense for today
        mykarma = sum([k['value'][1] for k in get_karma(kdt,adm)])
        if (nkarmaval>0 and mykarma<cfg.KARMA_POINTS_PER_DAY) or nkarmaval<0:
            if kdt not in karma: karma[kdt]={}
            if adm not in karma[kdt]: karma[kdt][adm]={}
            if nkarma not in karma[kdt][adm]: karma[kdt][adm][nkarma]=0
            newval = karma[kdt][adm][nkarma]+nkarmaval
            if newval>=0: karma[kdt][adm][nkarma]=newval

    if ncl:
        for ncli in ncl.split(','):
            cross_links.append(ncli)
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
        t = get_task(request.params.get('id'))
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
                    'informed':informed,
                    'branches':branches}
        print o_params
        rewrite(P,C,tid,o_params,safe=False,user=adm,fetch_stamp=fstamp)
        t = get_task(tid)
        cross_links_raw = get_cross_links(tid)
        if request.params.get('content-journal'):
            tj = get_task(task)
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
        print 'redircting to %s'%redir
        rd = Redirect(redir)
        return rd
    if task=='new':
        ch=[]
    else:
        #raise Exception('eff off',task)
        #print('getting children')
        ch = get_children(C,task)
        sortmode = request.params.get('sortby','default')
        ch.sort(sortmodes[sortmode],reverse=True)
        print('got',len(ch),'kids')

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
        t = get_task(task)
        par = task ; parents=[]
        parents = task.split('/')
        opar = []
        for i in xrange(len(parents)-1):
            opar.append('/'.join(parents[:i+1]))
    parents = [(pid,get_task(pid)['summary']) for pid in opar]
    prt = get_usernames(C)
    metastates,content = read_current_metastates(t,True)
    zerodelta = datetime.timedelta(seconds=0)
    if gantt.get('t') and gantt.get('we'):
        remaining_hours = gantt.get('we')-gantt.get('t')
    else:
        remaining_hours=zerodelta
    #journal
    jitems = t.journal
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



    return basevars(request,P,C,{'task':t,
                                 'changed_at':changed_at,
            'gantt':gantt,
            'gantt_labels':gantt_labels,
            'zerodelta':zerodelta,
            'branches_by_target':btgts,
            'get_task':get_task,
            'cross_links':cross_links_raw,
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
    })

@render_to('tags.html')
@db
def tags(request,P,C):
    tags = get_tags()
    tags = tags.items()
    tags.sort(lambda x1,x2: cmp(x1[1],x2[1]),reverse=True)
    rt = {'tags':tags}
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

    print 'obtaining journals'
    gaj = get_all_journals(C,day=day,creator=creator)
    print 'obtained; reading %s journals'%len(gaj)
    for jt in gaj:
        jtd = jt
        jt = get_task(jt['tid'])
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

    print 'finished reading. sorting'
    ai.sort(lambda x1,x2: cmp(x1['created_at'],x2['created_at']))
    print 'sorted'
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
    rt['headline'] = '%s tasks %s belonging to state %s%s'%(len(tids),excl and 'exclusively' or '',",".join(res[0].keys()),(tags and ", having tags "+(",".join(tags)) or ""))
    return rt

@render_to('incoming.html')
@db
def incoming(request,P,C,tags=[],limit=300):
    if type(tags) in [str,unicode]:
        tags = tags.split(",")

    adm = get_admin(request,'unknown')    
    newer_than = (datetime.datetime.now()-datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S')
    t = get_latest(tags=tags,newer_than=newer_than,limit=limit)
    return basevars(request,P,C,{'tasks':t,
                             'now':datetime.datetime.now(),
                             'humanize':humanize,
                             're':re,
                             'user':adm,
                             'tags':tags,
                             'newer_than':newer_than,
                             'get_task':get_task
    })

@ajax_response
def gantt_save(request):
    o = json.loads(request.params.get('obj'))
    with P as p:
        C = p.cursor()
        C.execute("select * from gantt where tid in %(items)s",{'items':tuple([d['id'] for d in o['data']])})
        gts = C.fetchall()
    for g in gts:
        t = Task.get(g['tid'])
        t['gantt_links']=[]
        t.save()
    for l in o['links']:
        s = Task.get(l['source'])
        if 'gantt_links' not in s: s['gantt_links']=[]
        s['gantt_links'].append(l)
        s.save()
    
    return {'res':'ok'}

                      
@render_to('time_tracking_dashboard.html')
@db
def time_tracking_dashboard(request,P,C,rangeback='7 day',persons=None,mode='provider',tids=None):
    adm = get_admin(request,'unknown')
    if not hasperm(C,adm,'gantt'): return Error403('no sufficient permissions for %s'%adm)

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
        print qry
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
        'summary':t['summary'].decode('latin-1'),
                'status':t['status']} for t in tasks]

    dates = set([t['startDate_raw'].date() for t in tasks_t])
    providers = set([t['taskName'] for t in tasks_t])
    

    tasks_rt=[]
    for p in providers:
        for d in dates:
            #print('going over provider, task',p,d)
            tasks_p = filter(lambda x: x['taskName']==p and x['startDate_raw'].date()==d,tasks_t)
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
                    print(t,pt)
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
    if not hasperm(C,adm,'gantt'): return Error403('no sufficient permissions for %s'%adm)    
    res = C.execute("select id from tasks where show_in_gantt=false")
    fa = C.fetchall()
    dismissed = [r['id'] for r in fa if r]

    C.execute("select * \
from gantt where \
(we is not null and t is not null ) and ( (t_l>=now()-interval '2 weeks' or c_l>=now()-interval '2 weeks'))")
    #and created_at>=now()-interval '12 month'
    res = C.fetchall()
    print(len(res),'initial tasks fetched')

    # retrieve missing parents?
    while True:
        missing = set([r['parent_id'] for r in res if
                       r['parent_id'] and
                       r['parent_id'] not in dismissed and
                       r['parent_id'] not in [r2['tid'] for r2 in res]])
        print('calculated',len(missing),'missing parents:',missing)

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
        ct = Task.get(tid)
        if 'gantt_links' in ct:
            for tl in ct['gantt_links']:
                links.append(tl)
    
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
    if assignee=='me':
        assignee=get_admin(request,'unknown')
    queue={}
    #print 'cycling journals'
    for t in get_journals():
        if assignee and t.assignee!=assignee: continue

        if metastate_group!='production':
            if not archive and t['status'] in cfg.DONESTATES: continue
            elif archive and t['status'] not in cfg.DONESTATES: continue

        tid = t._id
        #print t
        assert t.status,"could not get status for %s"%tid
        #print 'reading metastates'
        cm,content = read_current_metastates(t,True)

        #skip this task if has no metastates relevant to us
        relevant_metastates=False
        for cmk in cm:
            if cmk in cfg.METASTATES[metastate_group]:
                relevant_metastates=True
                break
        if not relevant_metastates: continue
        #print 'reading journal'
        jitems = read_journal(t)
        lupd = sorted(cm.values(),lambda x1,x2: cmp(x1['updated'],x2['updated']),reverse=True)
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
        queue[tid]={'states':dict([(cmk,cmv['value']) for cmk,cmv in cm.items()]),
                    #'total_hours':t.get('total_hours',0),
                    'fullstates':cm,
                    'last updated':lupd,
                    'status':t['status'],
                    'summary':t['summary'],
                    'last entry':content,
                    'tags':t['tags'],
                    'assignee':t.assignee,
                    'merge':[l['url'] for l in t.links if l['anchor']=='merge doc'],
                    'job':[l['url'] for l in t.links if l['anchor']=='job'],
                    'specs':[l['url'] for l in t.links if l['anchor']=='specs']}
    print 'done. itemizing'
    queue = queue.items()
    print 'sorting'
    queue.sort(lambda x1,x2: cmp((x1[1]['last updated'] and x1[1]['last updated'] or datetime.datetime(year=1970,day=1,month=1)),(x2[1]['last updated'] and x2[1]['last updated'] or datetime.datetime(year=1970,day=1,month=1))),reverse=True)


    metastate_url_prefix = dict (zip(cfg.METASTATE_URLS.values(),cfg.METASTATE_URLS.keys()))[metastate_group]
    print 'rendering'
    return basevars(request,P,C,{'queue':queue,
            'metastate_group':metastate_group,
            'metastate_url_prefix':metastate_url_prefix,
            'metastates':METASTATES,
            'colors':cfg.METASTATES_COLORS,
            'overrides':cfg.METASTATES_OVERRIDES})


@render_to('journal.html')
@db
def journal(request,P,C,task):
    t = get_task(task)
    jitems = read_journal(t)
    return basevars(request,P,C,{'task':t,'j':{'%s existing entries'%t._id:jitems},'metastates':METASTATES})

@render_to('task_history.html')
def history(request,task):
    t = get_task(task)
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
        t = get_task(tid)
        #print '%s = %s + %s'%(msk,t['total_hours'],v)
        #v = "%4.2f"%(float(t.get('total_hours',0))+float(v))
    else:
        t =  get_task(tid)

    print 'setting %s.%s = %s'%(tid,msk,v)
    append_journal_entry(P,C,t,adm,'',{msk:v})
    return {'status':'ok'}

def favicon(request):
    response = BaseResponse()
    response.headerlist=[('Content-Type', 'image/x-icon')]
    f = open(os.path.join(APP_DIR,'favicon.ico')).read()
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
        f = open(fname).read()
        response.headerlist=[('Content-Type', map[r_type])]
        response.body = f
        return response
    except:
        return exc.HTTPNotFound(fname)

    
