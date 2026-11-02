#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
    echo 'Usage: sudo scripts/update.sh /path/to/reviewed/source' >&2
    exit 2
fi
source_dir=$(CDPATH= cd -- "$1" && pwd)
candidate=$(python3 "$source_dir/scripts/deploy.py" stage "$source_dir")
exec python3 "$source_dir/scripts/deploy.py" apply "$candidate"
