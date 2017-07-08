#!/bin/sh
# PREFIX="$1"
# PREFIX="$(echo $str | awk '{print toupper($0)}')"
PGHOST="$(eval echo "$"$PREFIX"_PG_PORT_5432_TCP_ADDR")"
RDHOST="$(eval echo "$"$PREFIX"_REDIS_PORT_6379_TCP_ADDR")"
echo "PG_DSN='dbname=tasks password=passw0rd user=tasks host="$PGHOST"'" > /home/tasks/config_local.py
echo "REDIS_BROKER='redis://"$RDHOST":6379/'" >> /home/tasks/config_local.py
echo "WEBAPP_FORCE_IDENTITY='default_user'" >> /home/tasks/config_local.py
