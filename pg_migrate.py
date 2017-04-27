#!/usr/bin/env python
import json
import pg
from docs import Task,get_participants,get_table_contents
import sys
import config as cfg
import os

if __name__=='__main__':
    P,C = pg.connect()
    print('querying couch')

    if 'tasks' in sys.argv:
        #tds = [Task.get('1003/1')]
        tds = Task.view('task/all')
        print('walking tasks')
        for t in tds:
            pg.migrate_one(t,C)
        print('committing')
        P.commit()
        print('done')

    if 'participants' in sys.argv:
        # -- create table participants (username varchar primary key, name varchar unique,email varchar unique,active boolean default true, skype varchar unique, informed varchar[]);
        ps = get_participants(cfg.DATADIR,disabled=True,force=True)
        for p,vs in ps.items():
            keys = [k for k in vs.keys() if k.lower() not in ['ops','server','client','qa','art','']]
            fnames = [k.replace('-','_').lower().replace('e_mail','email') for k in keys]
            values = [vs[k] and vs[k] or None for k in keys]
            values[keys.index('Informed')]=values[keys.index('Informed')] and '{%s}'%",".join(values[keys.index('Informed')].split(',')) or None
            qry = "insert into participants (%s) values (%s)"%(",".join([k for k in fnames]),",".join([k=='informed' and '%s' or '%s' for k in fnames]))
            print(qry,values)            
            C.execute(qry,values)

        P.commit()
    if 'repos' in sys.argv:
        repos = [r['Name'] for r in get_table_contents(os.path.join(cfg.DATADIR,'repos.org'),force=True) if r.get('Name')]
        for r in repos:
            C.execute("insert into repos (name) values(%s)",(r,))
            print('insert',r)
        P.commit()
