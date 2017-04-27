#!/usr/bin/env python

import datetime
from couchdbkit import *
from couchdbkit.designer import push
from docs import initvars
import config as cfg    
import sys
import json

# Wrap sys.stdout into a StreamWriter to allow writing unicode.
import codecs
import locale
sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout) 
# done

initvars(cfg)

from couchdb import *
from docs import metastates_agg ,metastates_qry

if __name__=='__main__':

    if len(sys.argv)>1:
        res,res2,nosuper = metastates_qry(sys.argv[1])
        for arg,tids in res.items():
            for tid in tids:
                print 'attr',arg,tid
        for tid in res2:
            print 'intersection',sys.argv[1],tid
        for tid in nosuper:
            print 'nosuper',sys.argv[1],tid
    else:
        unqkeys,unqtypes,unqtypes_nosuper = metastates_agg()
        #raise Exception(len(unqtypes['status=TODO']),len(unqtypes_nosuper['status=TODO']))
        for tid,kvs in unqkeys.items():
            for kv in kvs:
                print 'attr',tid,kv.replace('=',' ')
        for kvs,tids in unqtypes.items():
            for tid in tids:
                print 'conds',kvs,tid
        for kvs,tids in unqtypes_nosuper.items():
            for tid in tids:
                print 'conds_nosuper',kvs,tid


