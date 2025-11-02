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

# 7. Make Unity testing work:
mkdir unity in coreutils. copy over unity.h and unity.c
In /src/local.mk, add unity/unity.o to the line:
```bash
LDADD = src/libver.a lib/libcoreutils.a unity/unity.o $(LIBINTL) $(MBRTOWC_LIB) \
  $(INTL_MACOSX_LIBS) lib/libcoreutils.a
```
This will break other programs.

To fix it: modify unity.c
```c
// Weak symbols for setUp/tearDown - programs without tests can link safely
__attribute__((weak)) void setUp(void) {}
__attribute__((weak)) void tearDown(void) {}
```
and rebuild it
```bash
gcc -c -o unity/unity.o unity/unity.c -I. -I./lib
```

Then regenerate Makefile
```bash
FORCE_UNSAFE_CONFIGURE=1 ./configure
```
and run make
```bash
make
```

# 8. Generating tests.c:
Take the example of cat.c:
- in cat.c: 
```
remove main() function. 
add #include "../tests/cat/cat_tests.c"  // Go up 1 level, then into tests/cat/
```
- create the file cat_tests.c in tests/cat, using the .sh test files already in the folder as inspiration
```
The tests.c file should start with #include "../../unity/unity.h"
It should have the Unity required setUp and tearDown functions
It should have the main function:
int main(void) {
    UNITY_BEGIN();
    RUN_TEST(..);
    ...
    return UNITY_END();
}
```

Now, rerun make. Then running cat will show test results.
```bash
make src/cat
./src/cat
```


Problems: it needs multiple tries before it can get a valid one.
eg.
/* 
 * Since chcon.c will have main() removed, we need to test it differently.
 * We'll create a wrapper that simulates calling main with argc/argv
 */
