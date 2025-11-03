FROM ubuntu:22.04
MAINTAINER kunst1080 kontrapunkt1080@gmail.com

# Install base build tools and dependencies
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
        clang-14 \
        llvm-14 \
        llvm-14-dev \
        llvm-14-tools \
        bear \
        libclang-cpp14 \
        libllvm14 \
        build-essential \
        libc6-dev \
        binutils \
        make \
        wget \
        ca-certificates \
        python3 \
    && rm -rf /var/lib/apt/lists/*

# Install Mull 14 (for LLVM 14)
RUN wget https://github.com/mull-project/mull/releases/download/0.26.1/Mull-14-0.26.1-LLVM-14.0-ubuntu-x86_64-22.04.deb -O /tmp/mull.deb && \
    apt-get install -y /tmp/mull.deb && rm /tmp/mull.deb

# Create non-root user
ARG uid
RUN useradd user -u ${uid:-1000}
USER user
WORKDIR /coreutils
