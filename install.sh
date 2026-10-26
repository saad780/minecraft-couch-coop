#!/bin/sh
set -eu
task_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 -c 'import sys; sys.path.insert(0,sys.argv[1]); from mc_couch.installer import install; install(sys.argv[1])' "$task_source"
