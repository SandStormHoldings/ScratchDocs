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
print 'ai'
if __name__=='__main__':
    s,d = init_conn()
    doc = Task.get('_design/task')
    print doc
    #push_views(d)
