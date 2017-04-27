#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
filedesc: helper script to launch GameServer
'''

from config import NO_GEVENT_MONKEYPATCH

if not NO_GEVENT_MONKEYPATCH:
    import psycogreen
    psycogreen.gevent.patch_psycopg()

from noodles.app import startapp
import sys

if __name__ == '__main__':
    bindhost = len(sys.argv)>1 and sys.argv[1] or '0.0.0.0'
    print 'binding on %s'%bindhost
    startapp(host=bindhost)
