#!/bin/bash

set -eu

IMAGE=interactive_coreutils_container
podman build . -t $IMAGE --build-arg uid=$UID
