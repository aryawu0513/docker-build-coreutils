"""
Interactive Coreutils Test Harness

Reads JSON payloads from stdin, writes/updates source files inside
the container, builds and runs specified programs, and returns results
as JSON to stdout.

Payload format:
{
    "program": "pwd",
    "injectables": [
        {"function_name": "foo", "include_line": "#include <foo.h>"},
        {"function_name": "bar", "include_line": "#include <bar.h>"}
    ],
    "extra_files": {
        "src/foo.c": "int foo() { return 0; }"
    }
}
"""

import json
import subprocess
import re
from pathlib import Path
from container_protocol import *
import os
import sys
cwd = Path.cwd()


COREUTILS_SRC = Path("/workdir/coreutils")

def compile_and_run_tests(data: dict) -> dict:
    """Compile program with test file and run"""
    #to be implemented
    pass


def handle_payload(data: dict) -> dict:
    """
    Write files from payload, compile, run tests, and return results.
    """
    print("in handle_payload with data keys:", data.keys(), file=sys.stderr)

    #.we need to design what the payload lloks like

    # Compile & run
    return compile_and_run_tests(data)


def main():
    while True:
        try:
            data = json.loads(input())
            print("data received:", data, file=sys.stderr)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {str(e)}"}), flush=True)
            continue

        result = handle_payload(data)
        print(json.dumps(result), flush=True)

if __name__ == '__main__':
    main()