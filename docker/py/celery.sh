#!/bin/sh
cd /home/tasks && celery worker -A tasks --config celeryconfig
