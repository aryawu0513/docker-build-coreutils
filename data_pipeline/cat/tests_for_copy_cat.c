#include "../../unity/unity.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

/* The following globals are defined in the program source and are visible here
   because this file is included into the same translation unit. */
extern int input_desc;
extern char const *infile;

/* Helpers */

static void redirect_stdout_to_fd(int new_fd, int *saved_stdout)
{
    *saved_stdout = dup(STDOUT_FILENO);
    TEST_ASSERT_TRUE_MESSAGE(*saved_stdout >= 0, "dup(STDOUT) failed");
    
    /* CRITICAL: Don't use TEST_ASSERT after dup2 redirects stdout! */
    int r = dup2(new_fd, STDOUT_FILENO);
    if (r < 0) {
        fprintf(stderr, "ERROR: dup2 to STDOUT failed\n");
        TEST_FAIL_MESSAGE("dup2 failed");  // This might still crash, but better than silent failure
    }
}

static void restore_stdout(int saved_stdout)
{
    if (saved_stdout >= 0) {
        int r = dup2(saved_stdout, STDOUT_FILENO);
        (void)r; /* Avoid unused warning; in tests, assertions already done */
        close(saved_stdout);
    }
}

static char* create_temp_file(const char *prefix, int *fd_out)
{
    char tmpl[256];
    snprintf(tmpl, sizeof(tmpl), "/tmp/%s_XXXXXX", prefix);
    char *path = strdup(tmpl);
    TEST_ASSERT_NOT_NULL_MESSAGE(path, "strdup failed");

    int fd = mkstemp(path);
    TEST_ASSERT_TRUE_MESSAGE(fd >= 0, "mkstemp failed");
    if (fd_out) *fd_out = fd;
    return path;
}

static void write_all(int fd, const void *buf, size_t len)
{
    const char *p = (const char*)buf;
    while (len > 0) {
        ssize_t w = write(fd, p, len);
        TEST_ASSERT_TRUE_MESSAGE(w >= 0, "write failed");
        p += w;
        len -= (size_t)w;
    }
}

static char* read_file_to_buf(const char *path, size_t *size_out)
{
    int fd = open(path, O_RDONLY);
    TEST_ASSERT_TRUE_MESSAGE(fd >= 0, "open for read failed");
    struct stat st;
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, fstat(fd, &st), "fstat failed");
    size_t sz = (size_t)st.st_size;
    char *buf = (char*)malloc(sz + 1);
    TEST_ASSERT_NOT_NULL_MESSAGE(buf, "malloc failed");
    size_t off = 0;
    while (off < sz) {
        ssize_t r = read(fd, buf + off, sz - off);
        TEST_ASSERT_TRUE_MESSAGE(r >= 0, "read failed");
        if (r == 0) break;
        off += (size_t)r;
    }
    close(fd);
    buf[sz] = '\0';
    if (size_out) *size_out = sz;
    return buf;
}

static off_t file_size(const char *path)
{
    struct stat st;
    if (stat(path, &st) != 0) return -1;
    return st.st_size;
}

/* Unity fixtures */

void setUp(void) {
    /* nothing */
}

void tearDown(void) {
    /* nothing */
}

/* Tests */

/* 1) Successful copy from regular file -> regular file.
   Expect: return 1, exact content copied.
   If copy_file_range is unsupported and returns 0, mark test ignored
   to avoid false negatives in such environments. */
void test_copy_cat_success_regular_file_to_regular_file(void)
{
    /* Prepare input content */
    const char *content =
        "Line 1\n"
        "Line 2: tabs\tand\tspecials\n"
        "Line 3: binary \x01\x02\x7f\x80 end\n";

    /* Create and fill input temp file */
    int in_fd_tmp;
    char *in_path = create_temp_file("copy_cat_in", &in_fd_tmp);
    write_all(in_fd_tmp, content, strlen(content));
    close(in_fd_tmp);

    /* Open input for reading and set globals */
    int in_fd = open(in_path, O_RDONLY);
    TEST_ASSERT_TRUE_MESSAGE(in_fd >= 0, "open input failed");
    input_desc = in_fd;
    infile = in_path;

    /* Create output temp file and redirect STDOUT to it */
    int out_fd_tmp;
    char *out_path = create_temp_file("copy_cat_out", &out_fd_tmp);
    /* ensure empty & truncated */
    ftruncate(out_fd_tmp, 0);

    int saved_stdout = -1;
    redirect_stdout_to_fd(out_fd_tmp, &saved_stdout);

    /* Call the function under test */
    int rc = copy_cat();

    /* Restore STDOUT and cleanup descriptors used for redirection */
    restore_stdout(saved_stdout);
    close(out_fd_tmp);
    close(in_fd);

    if (rc == 0) {
        /* Environment likely doesn't support copy_file_range for file->file.
           Ignore this test in that case. */
        unlink(in_path);
        unlink(out_path);
        free(in_path);
        free(out_path);
        TEST_IGNORE_MESSAGE("copy_file_range unsupported in environment; skipping success-path assertions");
        return;
    }

    TEST_ASSERT_EQUAL_INT_MESSAGE(1, rc, "copy_cat should return 1 on successful copy");

    /* Verify content */
    size_t out_sz = 0;
    char *out_buf = read_file_to_buf(out_path, &out_sz);
    TEST_ASSERT_EQUAL_size_t(strlen(content), out_sz);
    TEST_ASSERT_EQUAL_MEMORY(content, out_buf, out_sz);

    /* Cleanup */
    free(out_buf);
    unlink(in_path);
    unlink(out_path);
    free(in_path);
    free(out_path);
}

/* 2) Empty input file -> output file.
   Expect: return 0 (no data copied), and destination remains empty. */
void test_copy_cat_empty_input_returns_0(void)
{
    int in_fd_tmp;
    char *in_path = create_temp_file("copy_cat_empty_in", &in_fd_tmp);
    /* Leave empty */
    close(in_fd_tmp);

    int in_fd = open(in_path, O_RDONLY);
    TEST_ASSERT_TRUE_MESSAGE(in_fd >= 0, "open empty input failed");
    input_desc = in_fd;
    infile = in_path;

    int out_fd_tmp;
    char *out_path = create_temp_file("copy_cat_empty_out", &out_fd_tmp);
    ftruncate(out_fd_tmp, 0);

    int saved_stdout = -1;
    redirect_stdout_to_fd(out_fd_tmp, &saved_stdout);

    int rc = copy_cat();

    restore_stdout(saved_stdout);
    close(out_fd_tmp);
    close(in_fd);

    TEST_ASSERT_EQUAL_INT_MESSAGE(0, rc, "copy_cat should return 0 for empty input");

    off_t sz = file_size(out_path);
    TEST_ASSERT_EQUAL_INT64((int64_t)0, (int64_t)sz);

    unlink(in_path);
    unlink(out_path);
    free(in_path);
    free(out_path);
}

/* 3) Invalid input descriptor (EBADF path).
   Expect: copy_file_range fails with EBADF, copy_cat returns 0.
   Also verify nothing written to the destination. */
void test_copy_cat_invalid_input_fd_returns_0(void)
{
    /* Set invalid input descriptor */
    input_desc = -1;
    infile = "invalid-fd";

    int out_fd_tmp;
    char *out_path = create_temp_file("copy_cat_badfd_out", &out_fd_tmp);
    ftruncate(out_fd_tmp, 0);

    int saved_stdout = -1;
    redirect_stdout_to_fd(out_fd_tmp, &saved_stdout);

    int rc = copy_cat();

    restore_stdout(saved_stdout);
    close(out_fd_tmp);

    TEST_ASSERT_EQUAL_INT_MESSAGE(0, rc, "copy_cat should return 0 on EBADF (invalid input fd)");

    off_t sz = file_size(out_path);
    TEST_ASSERT_EQUAL_INT64((int64_t)0, (int64_t)sz);

    unlink(out_path);
    free(out_path);
}

/* Unity main */
int main(void)
{
    UNITY_BEGIN();

    RUN_TEST(test_copy_cat_success_regular_file_to_regular_file);
    RUN_TEST(test_copy_cat_empty_input_returns_0);
    RUN_TEST(test_copy_cat_invalid_input_fd_returns_0);

    return UNITY_END();
}