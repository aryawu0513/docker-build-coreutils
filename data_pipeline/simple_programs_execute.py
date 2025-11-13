
from test_container_one_mull import run_build_execute_mutate_for_one_coreutils_program

default_progs = [
    "src/basenc", "src/basename", "src/cat", "src/chmod", "src/chown", "src/comm", 
    "src/cp", "src/csplit", "src/cut", "src/date", "src/dd",
    "src/dircolors", "src/dirname", "src/du", "src/echo", "src/env", "src/expand",
    "src/expr", "src/factor", "src/fmt", "src/fold", 
    "src/groups", "src/head", "src/id", "src/join", "src/kill", "src/link", "src/ln",
    "src/logname", "src/ls", "src/mkdir", "src/mkfifo", "src/mknod",
    "src/mktemp", "src/mv", "src/nl", "src/nproc", "src/nohup", "src/numfmt", "src/od",
    "src/paste", "src/pathchk", "src/pr", "src/printenv", "src/printf", "src/ptx",
    "src/pwd", "src/readlink", "src/realpath", "src/rm", "src/rmdir", "src/seq",
    "src/shred", "src/shuf", "src/sleep", "src/sort", "src/split",
    "src/stat", "src/sync", "src/tac", "src/tail", "src/tee", "src/test",
    "src/touch", "src/tr", "src/true", "src/truncate", "src/tsort", "src/tty",
    "src/uname", "src/unexpand", "src/uniq", "src/unlink", "src/uptime", 
    "src/wc", "src/whoami", "src/yes"
]


if __name__ == "__main__":
    success = 0
    failed = 0
    print(len(default_progs), " programs to execute tests for.")
    for i, program_name in enumerate(default_progs, 1):
        program_name = program_name.split("/")[-1] #eg. "pwd"
        print(f"\n{'='*70}")
        print(f"Executing tests for coreutils program: {program_name}")
        print(f"[{i}/{len(default_progs)}] {program_name}")
        print('='*70)
        try:
            run_build_execute_mutate_for_one_coreutils_program(program_name, enable_mutation_testing=True)
            success += 1
            print(f"✓ {program_name} DONE")
        except Exception as e:
            failed += 1
            print(f"✗ {program_name} FAILED: {e}")
            continue  # Keep going to next program
    print(f"\n{'='*70}")
    print(f"SUMMARY: {success} success, {failed} failed")
    print('='*70)