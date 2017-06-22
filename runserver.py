#!/usr/bin/env python
'''
filedesc: helper script to launch GameServer
'''

from config import NO_GEVENT_MONKEYPATCH

if not NO_GEVENT_MONKEYPATCH:
    import psycogreen.gevent
    psycogreen.gevent.patch_psycopg()
    import gevent.monkey
    gevent.monkey.patch_all()

from noodles.app import startapp
import sys

if __name__ == '__main__':
    bindhost = len(sys.argv)>1 and sys.argv[1] or '0.0.0.0'
    print('binding on %s'%str(bindhost))
    startapp(host=bindhost)
