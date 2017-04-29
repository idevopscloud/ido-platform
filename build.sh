#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
workdir=${DIR}/target/workdir/

rm -rf target 2>/dev/null
mkdir -p $workdir/platform

cp -r ${DIR}/src/* $workdir/platform
cd $workdir
python -mcompileall platform/bin/platformctl.py && rm platform/bin/platformctl.py
tar czvf platform.tar.gz platform
mv platform.tar.gz ../

