#!/bin/sh
echo "PG_DSN='dbname=tasks password=passw0rd user=tasks host=$PG_PORT_5432_TCP_ADDR'" > /home/tasks/config_local.py
echo "COUCHDB_URI='http://"$COUCH_PORT_5984_TCP_ADDR":5984/'" >> /home/tasks/config_local.py
echo "REDIS_BROKER='redis://"$REDIS_PORT_6379_TCP_ADDR":6379/'" >> /home/tasks/config_local.py
echo "WEBAPP_FORCE_IDENTITY='default_user'" >> /home/tasks/config_local.py
