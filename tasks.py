from future import standard_library
standard_library.install_aliases()
from celery import Celery
from time import sleep
import logging

import config as cfg
from docs import initvars,P
import subprocess
initvars(cfg)
from subprocess import getstatusoutput as gso
celery = Celery('tasks',broker=cfg.REDIS_BROKER)

def db(function):
    """ this decorator acquires a db connection from the pool as well as a cursor from the connection and passes both on to its client. """
    def wrap_function(*args, **kwargs):
        with P as p:
            kwargs['P']=p
            kwargs['C']=p.cursor()
            return function(*args, **kwargs)
    return wrap_function

@celery.task
@db
def notifications(adm,tid,P,C):
    from couchdb import Task
    t = Task.get(C,tid)
    t._notify(P=P,C=C,user=adm)
    

@celery.task
def changes_to_feed():
    get_changes(show=False,feed=True)



