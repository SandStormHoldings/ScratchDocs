FROM bravissimolabs/alpine-git
FROM frolvlad/alpine-python2
MAINTAINER Guy Romm <guy@sandstormholdings.com>

RUN apk update && apk add python-dev musl-dev gcc py-mysqldb postgresql-dev
COPY docker/py/supervisord.conf /etc/supervisord.conf

WORKDIR /home/tasks
ADD . /home/tasks
RUN chown -R `stat -c "%u:%g" .` /home/tasks

RUN pip install -r requirements.txt
RUN touch config_local.py local_config.py

EXPOSE 8090
# this is supevisor. it has a problem with stdout
#CMD /home/tasks/docker/py/entrypoint.sh
CMD /home/tasks/runserver.py

