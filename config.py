DATADIR='data'
SHORTCUT_PREFIX='s'
OUTDIR='render'
TASKFN='task.org'
BACKLOG='Backlog'
STORY_SEPARATOR='/'
STATUSES=['REVIEW','DOING','TODO','DONE','DUPE','POSTPONED','CANCELLED', 'PARENT', 'STORAGE'] 
DONESTATES=['DONE','DUPE','CANCELLED','POSTPONED']
DEFAULT_STATUS='TODO'
CONSOLE_FRIENDLY_FILES=True
RECENT_DAYS=14
MAKO_DIR='/tmp/mako_modules'
RENDER_URL=None
SENDER=None
GITWEB_URL=None
REPOSITORIES=[]
REPO_DIR='repos'
DOCS_REPONAME=None
TPLDIR='templates'
ALWAYS_INFORMED=[]
HOST='0.0.0.0'
USE_ALCHEMY_MW=False
NOCOMMIT=False
NOPUSH=False
NONOTIFY=False
import logging
LOG_LEVEL=logging.WARNING
def USERMAP(un):
    return un
def COMMITERMAP(em,nm):
    assert '@' not in em
    assert '.' not in em
    return em
METASTATES={

    'planning':{
        'specs':('needed','doing','done'),
        'test plan':('needed','doing','available'),
        'ui/flow':('needed','doing','done'),
        'art':('needed','doing','done'),
        'work estimate':'INPUT(number)',
        'finish date':'INPUT(date)',
        },

    'merge':{
        'functional review':('needed',
                             'doing',
                             'failed',
                             'passed',
                             'not availible',
                             'qa replied',
                             'question to qa',
        ),
        'art review':('needed','doing','failed','passed', 'not availible'),
        'code review':('needed','doing','failed','passed','client review', 'not availible'),
        'tests passage':('no','building','random fails','integrator','100%'),
        'pm review':('needing','doing','passed','failed','n/a'),
        'merge to staging':('pending','merged','pending to production','on production','pending to preprod','on preprod'),
        },

    'production':{
        'pre-prod':('pending','updated','tested','failed','passed'),
        'prod':('pending','updated','tested','failed','passed'),
        },

    }
METASTATES_FLAT={}
for ms,dt in METASTATES.items():
    for msk,mdt in dt.items():
        METASTATES_FLAT[msk]=mdt
METASTATES_FLAT['unq_key']='ID(*)'

METASTATES_COLORS={
    'needed':'rgb(255, 192, 77)',
    'doing':'rgb(255, 255, 68)',
    'failed':'rgb(253, 75, 75)',
    'passed':'#47FF47',
    'no':'lightgrey',
    'random fails':'rgb(255, 192, 77)',
    'building':'rgb(255, 192, 77)',
    '100%':'#47FF47',
    'pending':'rgb(253, 75, 75)',
    'pending to production':'orange',
    'merged':'#47FF47',
    'integrator':'rgb(163, 196, 255)',
    '':'white',
    'client review':'rgb(94, 217, 248)',
    'on production':'rgb(94, 217, 248)',
    'not availible':'lightgrey',

    'done':'#47FF47',

    }

METASTATE_URLS = {'q':'merge',
                  'pl':'planning',
                  'pr':'production',}

METASTATES_OVERRIDES={
    'merged':"""fullstates.get(k) and fullstates.get(k).get('updated').strftime('%Y-%m-%d %H:%M') or ''""",
    'passed':"""(fullstates.get(k) and 'by '+fullstates.get(k).get('updated by','')) or ''""",
}
DIFF_BRANCHES=['staging','preproduction','production','master'] #display diff links to gitweb for those baseline branches
COUCHDB_URI=None #'http://localhost:5984/'

KARMA_POINTS_PER_DAY=4
PG_DBNAME='tasks'
PG_DSN='host=localhost dbname=%s'%PG_DBNAME
REDIS_BROKER='redis://localhost'
from noodles_config import *
from config_local import *
import os
SDIR = os.path.join(DATADIR,SHORTCUT_PREFIX)



