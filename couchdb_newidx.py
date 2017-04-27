from couchdb import *
import sys

if len(sys.argv)>1:
    par = int(sys.argv[1])
else:
    par = ''
s,d = init_conn()
push_views(d)

print get_new_idx(par)
