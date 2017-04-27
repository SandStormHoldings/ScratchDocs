#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
usage:

# for a fresh start
$ ./couchdb-backup.sh -f tasks.json -r -H localhost -d tasks #restore db from dump
$ sd/couchdb_query.py #push views
$ http://localhost:8090/s/new <-- create a new top level task for emails
# for an existing db
$ sd/emails_import.py --erase # get rid of all imported emails
$ sd/emails_import.py --fetch [--limit=XXX] > /tmp/helpdesk-XXX.json #have a fresh run
$ sd/emails_import.py --fetch --notmuch-filter="date:3days.." > new.json # or fetch new emails
$ FN=new.json ; sort -k2,1 $FN | pv -s $(wc -c $FN | awk '{print $1}') | sd/emails_import.py --insert
"""
from docs import initvars
import config as cfg
initvars(cfg)
import notmuch
from docs import Task,add_task,rewrite,get_task,append_journal_entry,P
from couchdb import get_children
import datetime
import sys

from collections import defaultdict
import re
import json
import hashlib
import codecs
sys.stdout = codecs.getwriter('utf8')(sys.stdout)


ptid = cfg.EMAIL_PARENT_TASK_ID
item_keys = ['dt_cr', 'team_sender', 'thread_id', 'subj', 'charset', 'mid', 'content', 'sndr', 'clean_subj','orig_subj', 'unq_key', 'is_reply','thread_task_ids','external_ids_task_ids','external_ids_msg_ids','recipients','assignee','rcpt_all']
overwrite=True

import re
import sys
from pg import get_participants
with P as p:
    C = p.cursor()
    p = get_participants(C,disabled=True)
shortemre = re.compile('^([^><@]+)@([^><@]+)$')
longemre = re.compile('^(.*)( |)<([^@]+)@([^>]+)>')
tre = re.compile('\[t/([0-9\/]+)\]') #subject task id regexp
pems = dict([(pv['email'].strip(),pk) for pk,pv in p.items()])
pnames = dict([(pv['name'].strip(),pk) for pk,pv in p.items()])

# here's a good method to obtain a list and frequency of appearance of unresolved email addresses (not in tasks):
# cat emails.json | cut -f3- -d" " | jq -c '.recipients' | sed 's/,/\n/g' | sed 's/\[//g' | sed 's/\]//g' | sed 's/\"//g' | sort | uniq -c | sort -n | grep '@'
def EMAIL_MATCH_TEAM(em):
    res = shortemre.search(em)
    res2 = longemre.search(em)

    ems = em.strip("'\"")
    if res2:
        name = res2.group(1)
        un = res2.group(3).lower()
        hn = res2.group(4).lower()
        emp = un+'@'+hn
    elif res:
        name = ''
        un = res.group(1).lower()
        hn = res.group(2).lower()
        emp = un+'@'+hn
    elif ems in pnames: #last resort - try and find by name
        emp = p[pnames[ems]]['E-Mail']
    else:
        sys.stderr.write("EMAIL_MATCH_TEAM: COULD NOT PARSE '%s'\n"%em)
        emp = None
    if emp in cfg.EMAIL_TRANS: emp = cfg.EMAIL_TRANS[emp]
    if emp in pems: return pems[emp]
    else: return False

def collect_data(m):
    dt = m.get_date()
    dt_cr = datetime.datetime.fromtimestamp(dt).strftime('%Y-%m-%dT%H:%M:%S')
    mid = m.get_message_id()
    thread_id = m.get_thread_id()
    #threads[thread_id]+=1

    rcpt_all = {'to':m.get_header('To').split(","),
                'cc':m.get_header('Cc').split(","),
                'bcc':m.get_header('Bcc').split(",")}
    recipients=[]
    for k,v in rcpt_all.items():
        rcpt_all[k] = list(set([r.strip() for r in v if r.strip()!='']))
        rcpt_all[k] = [EMAIL_MATCH_TEAM(r) and EMAIL_MATCH_TEAM(r) or r  for r in rcpt_all[k]]
        for recp in rcpt_all[k]:
            ignr = False
            for ignm in cfg.EMAIL_RECIPIENTS_IGNOREMASK:
                if ignm in recp: ignr=True
            if ignr: rcpt_all[k].remove(recp)
            if not ignr: recipients.append(recp)

    #will assign the first direct addressee available
    if len(rcpt_all['to']): assignee = rcpt_all['to'][0]
    else: assignee = None

    shdr = m.get_header('Subject')
    if not len(shdr): shdr='Untitled'
    orig_subj = clean_subj = subj = shdr
    #sys.stderr.write("ORIG_SUBJ '%s'\n"%orig_subj)
    for cf in ['Re:','Fwd:']:
        while cf in clean_subj: clean_subj = clean_subj.replace(cf,'')
    while True:
        if tre.search(clean_subj): clean_subj='[t/'.join(clean_subj.split('[t/')[0:-1])
        else: break

    clean_subj = clean_subj.strip()
    #assert len(clean_subj),"was '%s'"%(orig_subj)

    for cf in ['Re:']:
        if orig_subj.startswith(cf): orig_subj = orig_subj.replace(cf,'')
    orig_subj = orig_subj.strip()
    
    sndr = m.get_header('From')
    pts = m.get_message_parts()
    team_sender = EMAIL_MATCH_TEAM(sndr)
    #unq_key = hashlib.sha1('-'.join([clean_subj.encode('utf-8'),sndr.encode('utf-8')])).hexdigest()
    unq_key = '-'.join([thread_id,mid])
    content=None
    charset=None
    contents=[]
    for pt in pts:
        if pt.get('Content-Type').startswith('text/plain'):
            charset = pt.get_charset()
            content = pt.get_payload(decode=False) #.encode('utf-8','iso8859-1')
            try:
                content = content.decode(charset and charset or 'utf-8',errors='replace').strip()
            except UnicodeDecodeError, ud:
                sys.stderr.write("CONTENT:\n")
                #sys.stderr.write(content)
                sys.stderr.write("\nCOULD NOT DECODE!! with %s\n"%charset)
            if len(content):
                contents.append((charset,content))
    contents.sort(lambda x,y: cmp(len(x[1]),len(y[1])),reverse=True)

    #HACK ALERT: extract only the reply fom the message

    contents = map(lambda x: (x[0],"\n".join([ln for ln in x[1].split("\n") if not ln.startswith('>')])),contents)
    clidx=0
    for cl in contents:
        rt=[]
        for cli in cl[1].split("\n"):
            if re.compile('^On(.*)wrote\:').search(cli):
                break
            rt.append(cli)
        contents[clidx]=(cl[0],"\n".join(rt))
        clidx+=1


    #if len(contents)>1: raise Exception([(c[0],len(c[1])) for c in contents])
    contents = map(lambda x: (x[0],len(x[1])>cfg.EMAIL_CONTENT_TRIM_LENGTH and x[1][0:cfg.EMAIL_CONTENT_TRIM_LENGTH]+'\n .. TRIMMED' or x[1])
                   ,contents)
    if len(contents):
        (charset,content) = contents[0]
    
    rt = dict(filter(lambda x: (x[0] in item_keys ) , locals().items()))
    return rt

if __name__=='__main__':
    #arg parsing
    idargs = [a.split('=')[1] for a in sys.argv[1:] if a.startswith('--id=')]
    nmfilts = [a.split('=')[1] for a in sys.argv[1:] if a.startswith('--notmuch-filter=')]
    nmfiltstr=' and '.join(nmfilts)
    limits = [a.split('=')[1] for a in sys.argv[1:] if a.startswith('--limit=')]
    fetch = '--fetch' in sys.argv[1:]
    insert = '--insert' in sys.argv[1:]
    erase = '--erase' in sys.argv[1:]
    limit=len(limits) and int(limits[0]) or 10000
    cnt=0
    if erase:
        chs = get_children(ptid)
        for ch in chs:
            print 'erasing',ch._id,ch.summary
            ch.delete()
    elif fetch:
        # query for emails
        db = notmuch.Database(cfg.EMAIL_NOTMUCH_PATH,create=False)
        sstr = cfg.EMAIL_NOTMUCH_CRITERIA + (len(nmfiltstr) and ' and '+nmfiltstr or '')
        q = notmuch.Query(db,sstr)
        q.set_sort(notmuch.Query.SORT.OLDEST_FIRST)
        msgs = q.search_messages()
        for m in msgs:
            #print m.id
            if cnt>=limit: break
            cnt+=1            
            md = collect_data(m)
            if fetch:
                sys.stdout.write(" ".join([md['dt_cr'],
                                           md['unq_key'].encode('utf-8'),
                                           json.dumps(md)])+"\n")
    elif insert:
        # counters
        noop_cnt=0 ; nw_cnt=0 ; rw_cnt=0
        j_nw_cnt=0 ; j_rw_cnt=0 ; j_noop_cnt=0 ; threads=defaultdict(int)

        #dts = [msg.get_date() for msg in msgs] ; assert dts==sorted(dts),"messages are not sorted by date!"

        # iterate through query result
        for ln in sys.stdin:

            arr = ln.split(" ")
            try:
                md = json.loads(" ".join(arr[2:]))
            except ValueError,ve:
                print('could not decode',arr)
                raise


            if cnt>=limit: break ; cnt+=1

            thread_task_ids = [i['value'] for i in list(Task.view('task/threads',key=md['thread_id']))]
            external_ids_task_ids = [i['value'] for i in list(Task.view('task/external_ids',key=md['unq_key']))]
            #external_ids_msg_ids = [i['value'] for i in list(Task.view('task/external_msg_ids',key=md['mid']))]

            # we are a reply if the thread exists in the db and our id is not that of the top level task (already created)
            # here we are ABSOLUTELY RELYING ON THE FACT that tasks are fed to us in per thread, chronological order!
            
            is_reply = len(thread_task_ids) and not len(external_ids_task_ids)

            force_id=None
            tres = tre.search(md['orig_subj'])
            if tres:
                force_id = tres.group(1)
                is_reply = True
                print 'DETERMINED TID FROM SUBJECT',force_id

            if len(external_ids_task_ids):ext = get_task(external_ids_task_ids[0])
            else:ext = None
                
            if not is_reply:
                print 'NOT A REPLY, commencing, unq key %s'%md['unq_key']


                # do we have an existing task with that unique key?
                if not force_id:
                    if len(external_ids_task_ids):
                        force_id = external_ids_task_ids[0]
                        print 'FORCING UPDATE ON ID %s'%force_id
                    else:
                        force_id = None
                        print 'CREATING NEW'
                uns = "** Email contents\n"
                if ext:
                    if md['content'] in ext.unstructured:
                        unsc = ext.unstructured
                    else:
                        unsc = ext.unstructured.split(uns.strip())[0]+uns+md['content']
                else:
                    unsc = md['content']

                if force_id:
                    tr = Task.get(force_id)
                    asgn = tr.assignee and tr.assignee or md['assignee']
                else:
                    asgn = md['assignee']

                pars = {'creator':md['team_sender'] and md['team_sender'] or md['sndr'],
                        'assignee':asgn,
                        'created_at':datetime.datetime.strptime(md['dt_cr'],"%Y-%m-%dT%H:%M:%S"),
                        'summary':md['clean_subj'],
                        'orig_subj':md['orig_subj'],
                        'external_id':md['unq_key'],
                        'external_msg_id':md['mid'],
                        'external_thread_id':md['thread_id'],
                        'links':ext and list(ext.links) or [],
                        'branches':(ext and hasattr(ext,'branches')) and list(ext.branches) or [],
                        'cross_links':(ext and hasattr(ext,'cross_links')) and list(ext.cross_links) or [],
                        'cross_links_raw':'',
                        'informed':sorted(ext and list(set(list(ext.informed)+md['recipients'])) or md['recipients']),
                        'tags':ext and list(set(ext.tags + ['email'])) or [],
                        'unstructured':unsc
                }

                print 'resolved id is %s ; overwrite=%s'%(force_id,overwrite)
                if len(idargs)>1 and force_id not in idargs: continue

                try:
                    if force_id and overwrite:
                        print 'OVERWRITE IS ON'
                        with P as p:
                            C = p.cursor()
                            rewrite(P,C,force_id,o_params=pars,user=md['team_sender'])
                        rw_cnt+=1
                    elif force_id:
                        print '***** NOT REWRITING EXISTING %s'%force_id
                        noop_cnt+=1
                    else:
                        with P as p:
                            C = p.cursor()
                            task = add_task(P,C,parent=ptid,
                                            params=pars,
                                            tags=['email'],
                                            force_id=force_id)
                        nw_cnt+=1
                except UnicodeDecodeError,e:
                    print type(content),charset,content.decode('utf-8')
                    raise
            else:
                # if in a thread reply, add it as a journal entry
                if force_id:
                    master = [force_id]
                else:
                    master = [l['value'] for l in list(Task.view('task/threads',key=md['thread_id']))]
                # let's see if we already have a journal entry with this id
                exjournals = list(Task.view('task/external_journal_ids',key=md['mid']))
                assert len(exjournals)==0
                if len(master)<1:
                    print 'CANNOT FIND MASTER ENTRY %s ; skipping'%(md['thread_id'])
                else:
                    assert len(master)==1,"masters %s for %s"%(master,md['thread_id']) ;  mid = master[0] #FIXME: will need better heuristic
                    print 'JOURNAL INSERT/UPDATE on %s'%md['mid']
                    t = get_task(master[0])
                    jattrs = [je['attrs'].get('unq_key') for je in t.journal]
                    j_cr_dt = datetime.datetime.strptime(md['dt_cr'],"%Y-%m-%dT%H:%M:%S")
                    j_creator = (md['team_sender'] and md['team_sender'] or md['sndr'])
                    j_unq_key = '-'.join([md['unq_key'],md['dt_cr'],j_creator])
                    
                    if j_unq_key in jattrs:
                        print 'journal entry %s exists; updating'%j_unq_key
                        jentry = filter(lambda x: x['attrs'].get('unq_key')==j_unq_key ,t.journal)[0]
                        myei = t.journal.index(jentry)

                    jentry = {'content':md['content'],
                              'created_at':j_cr_dt,
                              'creator':j_creator,
                              'attrs':{'unq_key':j_unq_key}}

                    if j_unq_key in jattrs:
                        if jentry!=t.journal[myei]:
                            t.journal[myei]=jentry
                            t.save(sys.argv[0])
                            j_rw_cnt+=1
                        else:
                            j_noop_cnt+=1
                    else:
                        with P as p:
                            C = p.cursor()
                            append_journal_entry(P,C,t,
                                                 jentry['creator'],
                                                 jentry['content'],
                                                 jentry['attrs'],
                                                 jentry['created_at'])
                            j_nw_cnt+=1

        #print threads
        print '='*20
        print nw_cnt,' added ;',rw_cnt,'rewritten ;',noop_cnt,'tasks unchanged' 
        print j_nw_cnt,' journal entries added ;',j_rw_cnt,'journals rewritten ;',j_noop_cnt,'journals unchanged'

