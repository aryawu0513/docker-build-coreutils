#!/bin/bash

set -eu

IMAGE=build-coreutils
podman build . -t $IMAGE --build-arg uid=$UID
