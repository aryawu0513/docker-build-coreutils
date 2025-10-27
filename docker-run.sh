#!/bin/bash
exec podman run -it --rm \
    -v $PWD/coreutils:/coreutils \
    build-coreutils $*
