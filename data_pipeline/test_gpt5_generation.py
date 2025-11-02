import dspy
import os

class ShellToUnityTests(dspy.Signature):
    """
    You will be given a coreutils program and its shell tests.
    Your task is to convert these shell tests into a test suite that tests the coreutils program, using the Unity Testing Framework.

    The coreutils program have its main() function removed, and your tests.c will be #include'd directly into the program at the end.
    This means ALL functions in the program are directly accessible - you do NOT need extern declarations and do NOT need to include prototypes for functions defined in `program.c`.
    
    Since main() is removed, you may need to simulate main logic in your tests:
    - Set up argc/argv as needed
    - Call parsing functions
    - Call processing functions with appropriate arguments
    - Verify the results
    
    REQUIRED FORMAT for `tests.c`:
    - A Unity test file that thoroughly tests the coreutils program's functionality.
    - At the top of the file, add 
        ```c
        #include "../../unity/unity.h"
        ```
        Also include any other standard headers needed for the test code itself(e.g., stdlib.h, string.h, math.h).
    - Implement setUp() and tearDown() functions for Unity:
        ```c
        void setUp(void) {
        /* Setup code here, or leave empty */
        }
        void tearDown(void) {
        /* Cleanup code here, or leave empty */
        }
        ```
    - Create test functions: void test_xxx(void) { ... } that exercise the coreutils program's functionality.
    - The test file must define a main() function that calls UNITY_BEGIN(), runs tests with RUN_TEST(test_xxx), and returns UNITY_END().
    """

    program_code: str = dspy.InputField(description="The coreutils program (e.g., 'cat.c', 'ls.c')")
    shell_tests: str = dspy.InputField(description="Content of all shell test files with their filenames, separated by --- markers")
    tests_c: str = dspy.OutputField(description="Complete Unity test file tests.c that tests the program's behavior")

def generate_unity_tests_with_llm(program_name, program_code, shell_tests):
    """
    Args:
        program_code: The coreutils program code (e.g., "cat.c")
        shell_tests: List of dicts with 'filename' and 'content'
    
    Returns:
        String containing the generated C code, or False on failure
    """
    try:
        lm = dspy.LM(
            "gpt-5",
            model_type="chat",
            temperature=1.0,
            max_tokens=16000,#these are required by gpt5
        )
        dspy.configure(lm=lm)

        print("model loaded")
        
        # Format shell tests for the prompt
        tests_text = "\n\n---\n\n".join([
            f"File: {t['filename']}\n{t['content']}" 
            for t in shell_tests
        ])
        
        # Use ChainOfThought for better reasoning
        converter = dspy.ChainOfThought(ShellToUnityTests)
        
        # Generate the Unity tests
        result = converter(
            program_code=program_code,
            shell_tests=tests_text
        )

        print("LLM generation completed:", result)
        
        # Extract the generated tests.c code
        tests_c = result.tests_c.strip()
        
        # Check if generation failed (empty string)
        if not tests_c:
            print(f"  ✗ LLM returned empty tests for {program_name}")
            return False
        
        # Remove markdown code blocks if present
        if "```c" in tests_c:
            tests_c = tests_c.split("```c")[1].split("```")[0]
        elif "```" in tests_c:
            tests_c = tests_c.split("```")[1].split("```")[0]
        
        return tests_c.strip()
        
    except Exception as e:
        print(f"  ✗ Error generating tests with LLM: {e}")
        return False

# Example usage
if __name__ == "__main__":
    print("Generating Unity tests for 'cat'...")
    #read in cat code from cat.c
    cat_code = open("cat.c").read()
    # Example shell tests
    shell_tests = [
        {
            'filename': 'cat-self.sh',
            'content': """. "${srcdir=.}/tests/init.sh"; path_prepend_ ./src
print_ver_ cat

echo x >out || framework_failure_
echo x >out1 || framework_failure_
returns_ 1 cat out >>out || fail=1
compare out out1 || fail=1

# This example is taken from the POSIX spec for 'cat'.
echo x >doc || framework_failure_
echo y >doc.end || framework_failure_
cat doc doc.end >doc || fail=1
compare doc doc.end || fail=1

# This terminates even though it copies a file to itself.
# Coreutils 9.5 and earlier rejected this.
echo x >fx || framework_failure_
echo y >fy || framework_failure_
cat fx fy >fxy || fail=1
for i in 1 2; do
  cat fx >fxy$i || fail=1
done
for i in 3 4 5 6; do
  cat fx >fx$i || fail=1
done
cat - fy <fxy1 1<>fxy1 || fail=1
compare fxy fxy1 || fail=1
cat fxy2 fy 1<>fxy2 || fail=1
compare fxy fxy2 || fail=1
returns_ 1 cat fx fx3 1<>fx3 || fail=1
returns_ 1 cat - fx4 <fx 1<>fx4 || fail=1
returns_ 1 cat fx5 >>fx5 || fail=1
returns_ 1 cat <fx6 >>fx6 || fail=1

# coreutils 9.6 would fail with a plain cat if the tty was in append mode
# Simulate with a regular file to simplify
echo foo > file || framework_failure_
# Set fd 3 at EOF
exec 3< file && cat <&3 > /dev/null || framework_failure_
# Set fd 4 in append mode
exec 4>> file || framework_failure_
cat <&3 >&4 || fail=1
exec 3<&- 4>&-

Exit $fail
            """
        }
    ]
    
    # Generate Unity tests
    result = generate_unity_tests_with_llm("cat",cat_code, shell_tests)

    if result:
        print("Generated tests:")
        print(result)
    else:
        print("Failed to generate tests")
