from future import standard_library
standard_library.install_aliases()
from celery import Celery
from time import sleep
import logging

import config as cfg
from docs import initvars
import config as cfg
import subprocess
initvars(cfg)
from subprocess import getstatusoutput as gso
celery = Celery('tasks',broker=cfg.REDIS_BROKER)

@celery.task
def notifications(adm,tid):
    from couchdb import Task
    t = Task.get(tid)
    t._notify(user=adm)
    

@celery.task
def changes_to_feed():
    get_changes(show=False,feed=True)



