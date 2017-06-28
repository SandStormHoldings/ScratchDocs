#!/bin/bash

sudo -u postgres psql tasks -c "CREATE EXTENSION temporal_tables"
sudo -u postgres psql tasks -c "grant execute on function versioning() to tasks;"
