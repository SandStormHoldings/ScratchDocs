#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PWD=$(pwd)
IDU=$(id -u)
IDG=$(id -g)

PGCONNSTR=""
function pgconnstr() {
    PGCONNSTR="postgres://tasks:$PW@$PGHOST/tasks"
}

function wait_for() {
    HOST="$1"
    PORT="$2"
    NAME="$3"
    echo "about to wait on $HOST : $PORT"
    CNT=0
    while ! nc -w 1 -z $HOST $PORT; do
	echo 'waiting for '$NAME' to be available on '$HOST':'$PORT' ('$CNT')'
	sleep 1
	CNT=$[$CNT+1]
	if (( $CNT > 10 )) ; then
	    return 1
	    fi
    done
    echo "# $HOST:$PORT ($NAME) is replying"
    return 0
}

function storage_clean() {
    docker rm -f pg ||: &&
    docker rm -f couch ||: &&
    docker rm -f redis ||: &&
    rm -rf docker/{pg,couchdb}/data/* 
}
function app_clean() {
    docker rm -f tasks_py tasks_celery ||: &&
    find ./ -type f -iname '*pyc' -exec rm -rf {} \; &&
    rm -rf tmp/modules/*py    

    }
function clean_all() {
    storage_clean &&
    app_clean
    }

function install_prerequisites() {
    sudo apt install jq postgresql-client-common postgresql-client dos2unix &&
    git submodule update --init --recursive
    }

function build_app() {
    echo "# BUILDING TASKS/PY"
    docker build -t tasks/py .    
    }

function envs_obtain() {
    REDISHOST=$(docker inspect redis | jq '.[0].NetworkSettings.Networks.bridge.IPAddress' | sed 's/"//g')
    
    pgconnstr
    echo "REDISHOST=$REDISHOST"

    PW="passw0rd"
    PGHOST=$(docker inspect pg | jq '.[0].NetworkSettings.Networks.bridge.IPAddress' | sed 's/"//g')
    echo "PGHOST=$PGHOST  # $PGCONNSTR"
    
    COUCHHOST=$(docker inspect couch | jq '.[0].NetworkSettings.Networks.bridge.IPAddress' | sed 's/"//g')
    echo "COUCHHOST=$COUCHHOST"

    CELERYHOST=$(docker inspect tasks_celery | jq '.[0].NetworkSettings.Networks.bridge.IPAddress' | sed 's/"//g')
    echo "CELERYHOST=$CELERYHOST"
    
    PYHOST=$(docker inspect tasks_py | jq '.[0].NetworkSettings.Networks.bridge.IPAddress' | sed 's/"//g')
    echo "PYHOST=$PYHOST"
    }
function storage_launch() {
    echo '# RUNNING REDIS' &&
    docker run -d --name=redis redis &&
    echo '# RUNNING POSTGRESQL' &&     PW="passw0rd" #$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 6 | head -n 1)
    docker run -d --env 'USERMAP_UID='$IDU --env 'DB_NAME=tasks' --env 'DB_USER=tasks' --env 'DB_PASS='$PW --name=pg -v $PWD"/docker/pg/data:/var/lib/postgresql" sameersbn/postgresql &&
    echo '# RUNNING COUCHDB' &&
    docker run -d --name=couch -v $PWD"/docker/couchdb/data:/usr/local/var/lib/couchdb" couchdb &&     # not pushing anything to couch - push_views runs in the py Dockerfile
    envs_obtain &&
    wait_for $REDISHOST 6379 "redis"
    
}
function storage_restore_dump() {
    if [ -z "$1" ]
    then
	echo 'storage_restore_dump: ERROR: $1 must be name of couchdb json file'
	return 1
    fi
    if [ -z "$2" ]
    then
	echo 'storage_restore_dump: ERROR: $2 must be name of sql dump file'
	return 2
    fi

    envs_obtain &&
	wait_for $COUCHHOST 5984 "couch" &&
	couchdb-dump/couchdb-backup.sh -c -r -H $COUCHHOST -d tasks -f "$1" &&
	wait_for $PGHOST 5432 "pg" &&
	psql "postgresql://tasks:$PW@$PGHOST/tasks" < "$2" &&
	storage_details_print
}

function pgconn() {
    envs_obtain
    pgconnstr && psql "$PGCONNSTR"
}

function couchconn() {
    envs_obtain
    curl 'http://'$COUCHHOST":5984"
}

function storage_details_print() {
    s="$(pgconnstr)"
    echo "PGHOST=$PGHOST ; PGPASSWORD=$PW # psql postgres://tasks:$PW@$PGHOST/tasks" &&
    echo "COUCHHOST=$COUCHHOST # http://$COUCHHOST:5984/_utils/"
}

function schema_save() {
    docker exec -t pg pg_dump -U postgres -N pg_catalog -x --no-owner --schema-only tasks | grep -v 'plpgsql' > $DIR"/schema.sql" && dos2unix $DIR"/schema.sql"
}

function storage_populate() {
    envs_obtain &&
    echo '# LOADING POSTGRESQL DUMP' &&
    wait_for $PGHOST 5432 "pg" &&
    pgconn < schema.sql &&
    echo '# PUSHING VIEWS INTO COUCHDB' &&
    wait_for $COUCHHOST 5984 "couch" &&
    docker run -u $IDU -ti --link redis --link couch --link pg -v $PWD":/home/tasks" --entrypoint=/home/tasks/docker/py/write_config.sh tasks/py &&
    docker run -u $IDU -ti --link redis --link couch --link pg -v $PWD":/home/tasks" --entrypoint=./couchdb_query.py tasks/py &&
    storage_details_print
}
function celery_cmd() {
    if [[ "$1" == "" ]] ; then
	FL="-d"
    else
	FL=""
    fi
    docker run -u $IDU $FL --name=tasks_celery --link redis  --link couch --link pg -v $PWD":/home/tasks" --entrypoint /home/tasks/docker/py/celery.sh tasks/py
    }
runserver_cmd() {
    if [[ "$1" == "" ]] ; then
	FL="-d"
    else
	FL=""
    fi
    docker run -u $IDU $FL --name=tasks_py --link redis  --link couch --link pg -v $PWD":/home/tasks" --entrypoint /home/tasks/docker/py/runserver.sh  tasks/py
    }
function launch_app() {
    
    echo '# RUNNING tasks/celery' &&
	celery_cmd &&
	echo '# RUNNING tasks/py' &&
	runserver_cmd $1 &&
	envs_obtain &&
	wait_for $PYHOST 8090 "py" &&
	echo '# ALL IS READY' &&
	echo "PYHOST=$PYHOST ; http://$PYHOST:8090/"
    
}

function pull_and_build() {
    echo "# PULLING REDIS" &&
    docker pull redis &&
    echo "# PULLING POSTGRESQL" &&
    docker pull sameersbn/postgresql &&
    echo "# PULLING COUCHDB" &&
    docker pull couchdb &&
    build_app 
}

function init_and_run() {
    storage_launch &&
    storage_populate && # if you have dumps/backups you can use use storage_restore_dump instead
    launch_app
}

function run_all() {
    storage_launch &&
    launch_app
}

function start() {
    docker start pg couch redis tasks_py tasks_celery
}

function stop() {
    docker stop pg couch redis tasks_py tasks_celery
    }
function restart_all() {
    docker restart pg couch redis tasks_py tasks_celery
}

function attach() {
    docker attach tasks_py
}

function shell() {
    docker exec -ti tasks_py /bin/sh
}

function restart() { # app only
    docker restart tasks_py
}
function restart_hard_and_log() {
    app_clean &&
	launch_app &&
	docker attach tasks_py 2>&1 | tee tasks_py.log &
}
function restart_hard_and_attach() {
    app_clean &&
	launch_app "1"

    }
function all() {
    clean_all &&
	install_prerequisites &&
	pull_and_build &&
	init_and_run
}

if [[ "$0" != "bash" && "$0" != "-bash" ]] ; then
    all
    #echo "ERROR ($0): you must source this script first. $ source setup.sh"
else
echo "#####################################################"    
echo "the following top level commands are available (view source for all):"
echo ""
echo "install_prerequisites # install packages on the host OS that we depend on."
echo "clean_all              # remove any existing docker containers, .pyc files, mako template caches."
echo "build                 # build our application image from the Dockerfile."
echo "pull_and_build        # download images and build our application image from the Dockerfile."
echo "init_and_run          # initialize with basic data and launch the containers."
echo ""
echo "in general, if you'd like to install from scratch, you need to run 'all', which consists of the following:"
echo ""
echo '0. clean_all # if you have any left overs lying about.'
echo "1. install_prerequisites"
echo "2. pull_and_build"
echo "3. init_and_run"
echo ""
echo "if, instead of initializing a fresh database, you'd like to restore from backups, you need to do something like this in place of step 3:"
echo ""
echo "3.a. storage_launch"
echo "3.b. storage_restore_dump couchdb.json pg.sql"
echo "3.c. launch_app"
echo "#####################################################"
fi
