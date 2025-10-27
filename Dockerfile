FROM ubuntu:22.04
MAINTAINER kunst1080 kontrapunkt1080@gmail.com

RUN apt update -y \
    && apt install --no-install-recommends -y \
        autoconf \
        automake \
        autopoint \
        bison \
        gettext \
        git \
        gperf \
        texinfo \
        patch \
        rsync \
        xz-utils \
        gcc \
        g++ \
        make \
        wget \
        ca-certificates \
        python3 \
	&& rm -rf /var/lib/apt/lists/*

ARG uid
RUN useradd user -u ${uid:-1000}
USER user
WORKDIR /coreutils
