FROM sameersbn/postgresql
RUN apt-get update && apt-get install -y pgxnclient postgresql-server-dev-9.6 make gcc build-essential
RUN pgxn install temporal_tables
COPY extensions.sh /extensions.sh
