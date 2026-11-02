#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$source_dir/scripts/deploy.py" "$@" install "$source_dir"
