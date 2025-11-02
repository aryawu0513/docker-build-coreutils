#include "../../unity/unity.h"
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <stdio.h>
#include <errno.h>

/* Use the same support as the program does for program name. */
#include "progname.h"

/* Forward declare the target to silence any warnings, though it is visible. */
void usage (int status);

/* Helpers to capture output from a forked child invoking usage(). */

static char *read_all_from_fd(int fd)
{
    size_t cap = 1024;
    size_t len = 0;
    char *buf = (char *)malloc(cap);
    if (!buf) return NULL;

    while (1) {
        if (len + 512 >= cap) {
            cap *= 2;
            char *nb = (char *)realloc(buf, cap);
            if (!nb) {
                free(buf);
                return NULL;
            }
            buf = nb;
        }
        ssize_t n = read(fd, buf + len, cap - len - 1);
        if (n < 0) {
            if (errno == EINTR) continue;
            free(buf);
            return NULL;
        }
        if (n == 0) break;
        len += (size_t)n;
    }
    buf[len] = '\0';
    return buf;
}

static void run_usage_and_capture(int status, char **out_str, char **err_str, int *exit_code)
{
    int out_pipe[2];
    int err_pipe[2];
    TEST_ASSERT_EQUAL_INT(0, pipe(out_pipe));
    TEST_ASSERT_EQUAL_INT(0, pipe(err_pipe));

    pid_t pid = fork();
    TEST_ASSERT_TRUE_MESSAGE(pid >= 0, "fork failed");

    if (pid == 0) {
        /* Child */
        /* Route stdout/stderr to pipes */
        (void)dup2(out_pipe[1], STDOUT_FILENO);
        (void)dup2(err_pipe[1], STDERR_FILENO);
        close(out_pipe[0]); close(out_pipe[1]);
        close(err_pipe[0]); close(err_pipe[1]);

        /* Ensure predictable language for messages */
        setenv("LC_ALL", "C", 1);
        setenv("LANG", "C", 1);
        setenv("LC_MESSAGES", "C", 1);

        /* Ensure program_name used in messages is known */
        set_program_name("cat");

        usage(status);
        /* If usage ever returns (should not), make it obvious */
        _exit(200);
    } else {
        /* Parent */
        close(out_pipe[1]);
        close(err_pipe[1]);

        char *out_buf = read_all_from_fd(out_pipe[0]);
        char *err_buf = read_all_from_fd(err_pipe[0]);
        close(out_pipe[0]);
        close(err_pipe[0]);

        int wstatus = 0;
        TEST_ASSERT_EQUAL_INT_MESSAGE(pid, waitpid(pid, &wstatus, 0), "waitpid failed");

        int code = -1;
        if (WIFEXITED(wstatus)) {
            code = WEXITSTATUS(wstatus);
        } else if (WIFSIGNALED(wstatus)) {
            /* Encode signal distinctly */
            code = 128 + WTERMSIG(wstatus);
        }

        *out_str = out_buf ? out_buf : strdup("");
        *err_str = err_buf ? err_buf : strdup("");
        *exit_code = code;
    }
}

static int contains(const char *haystack, const char *needle)
{
    return haystack && needle && strstr(haystack, needle) != NULL;
}

void setUp(void) {
    /* empty */
}
void tearDown(void) {
    /* empty */
}

/* Tests */

void test_usage_failure_writes_try_help_to_stderr_and_exits_failure(void)
{
    char *outp = NULL, *errp = NULL;
    int code = -1;
    run_usage_and_capture(EXIT_FAILURE, &outp, &errp, &code);

    /* Exit code must be EXIT_FAILURE */
    TEST_ASSERT_EQUAL_INT(EXIT_FAILURE, code);

    /* No stdout on failure-path usage() */
    TEST_ASSERT_TRUE_MESSAGE(outp != NULL, "stdout capture null");
    TEST_ASSERT_EQUAL_UINT_MESSAGE(0, strlen(outp), "stdout not empty on failure");

    /* Stderr should contain a try-help hint with program name and --help */
    TEST_ASSERT_TRUE_MESSAGE(errp != NULL, "stderr capture null");
    TEST_ASSERT_TRUE_MESSAGE(strlen(errp) > 0, "stderr empty on failure");

    TEST_ASSERT_TRUE_MESSAGE(contains(errp, "Try '"), "stderr missing \"Try '\" hint");
    TEST_ASSERT_TRUE_MESSAGE(contains(errp, "cat --help"), "stderr missing program + --help");
    TEST_ASSERT_TRUE_MESSAGE(contains(errp, "more information"), "stderr missing \"more information\"");

    free(outp);
    free(errp);
}

void test_usage_success_writes_full_help_to_stdout_and_exits_zero(void)
{
    char *outp = NULL, *errp = NULL;
    int code = -1;
    run_usage_and_capture(EXIT_SUCCESS, &outp, &errp, &code);

    /* Exit code must be 0 */
    TEST_ASSERT_EQUAL_INT(0, code);

    /* Stderr should be empty */
    TEST_ASSERT_TRUE_MESSAGE(errp != NULL, "stderr capture null");
    TEST_ASSERT_EQUAL_UINT_MESSAGE(0, strlen(errp), "stderr not empty on success");

    /* Stdout should contain usage header and key option lines */
    TEST_ASSERT_TRUE_MESSAGE(outp != NULL, "stdout capture null");
    TEST_ASSERT_TRUE_MESSAGE(strlen(outp) > 0, "stdout empty on success");

    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "Usage: cat "), "missing \"Usage: cat\" header");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "Concatenate FILE(s) to standard output."), "missing primary description");

    /* Check for a good spread of options to ensure most of the help printed */
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-A, --show-all"), "missing -A, --show-all");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-b, --number-nonblank"), "missing -b, --number-nonblank");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-E, --show-ends"), "missing -E, --show-ends");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-n, --number"), "missing -n, --number");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-s, --squeeze-blank"), "missing -s, --squeeze-blank");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-T, --show-tabs"), "missing -T, --show-tabs");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "-v, --show-nonprinting"), "missing -v, --show-nonprinting");
    TEST_ASSERT_TRUE_MESSAGE(contains(outp, "Examples:"), "missing Examples section");

    free(outp);
    free(errp);
}

void test_usage_propagates_nonstandard_failure_code_and_uses_stderr(void)
{
    char *outp = NULL, *errp = NULL;
    int code = -1;
    int custom_status = 7;
    run_usage_and_capture(custom_status, &outp, &errp, &code);

    TEST_ASSERT_EQUAL_INT(custom_status, code);

    /* Ensure no stdout and stderr has the try-help hint */
    TEST_ASSERT_TRUE(outp != NULL);
    TEST_ASSERT_EQUAL_UINT(0, strlen(outp));

    TEST_ASSERT_TRUE(errp != NULL);
    TEST_ASSERT_TRUE(strlen(errp) > 0);
    TEST_ASSERT_TRUE_MESSAGE(contains(errp, " --help"), "stderr missing --help hint");

    free(outp);
    free(errp);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_usage_failure_writes_try_help_to_stderr_and_exits_failure);
    RUN_TEST(test_usage_success_writes_full_help_to_stdout_and_exits_zero);
    RUN_TEST(test_usage_propagates_nonstandard_failure_code_and_uses_stderr);
    return UNITY_END();
}