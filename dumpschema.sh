#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
pg_dump tasks -N pg_catalog -x --no-owner --schema-only | grep -v 'plpgsql' > $DIR"/schema.sql"
