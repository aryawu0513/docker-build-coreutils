docker-build-coreutils
===

building GNU Coreutils using docker


# 1. Clone main repo without submodules
```
git clone https://github.com/kunst1080/docker-build-coreutils
cd docker-build-coreutils
```

# 2. Clone the coreutils submodule (without ITS submodules yet)
```bash
git submodule update --init
```

# 3. Now go into coreutils and manually clone gnulib from GitHub
```bash
cd coreutils
git clone --depth 1 https://github.com/coreutils/gnulib.git gnulib
```

# 4. Go back and build the container
```bash
cd ..
./docker-build.sh
```

# 5. Launch the container
```bash
podman run -it --rm --user root -v $PWD/coreutils:/coreutils build-coreutils bash
./bootstrap
FORCE_UNSAFE_CONFIGURE=1 ./configure
make -j1
```

output is in `coreutils/src` directory!

# 6. Test that it works
```bash
podman run -it --rm --user root -v $PWD/coreutils:/coreutils build-coreutils bash
```

Inside the container:
```bash
./src/ls --version
./src/cat README
./src/echo "Hello from my custom coreutils!”
```