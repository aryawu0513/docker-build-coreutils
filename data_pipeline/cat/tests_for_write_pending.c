#include "../../unity/unity.h"
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <stdint.h>

static int saved_stdout_fd = -1;
static int pipe_read_fd = -1;

static void redirect_stdout_to_pipe(void)
{
    int fds[2];
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, pipe(fds), "pipe() failed");
    saved_stdout_fd = dup(STDOUT_FILENO);
    TEST_ASSERT_MESSAGE(saved_stdout_fd >= 0, "dup(STDOUT_FILENO) failed");
    TEST_ASSERT_EQUAL_INT_MESSAGE(STDOUT_FILENO, dup2(fds[1], STDOUT_FILENO),
                                  "dup2 to STDOUT failed");
    /* Close the extra write-end; STDOUT now refers to it */
    close(fds[1]);
    pipe_read_fd = fds[0];
}

static void restore_stdout(void)
{
    if (saved_stdout_fd >= 0) {
        (void)dup2(saved_stdout_fd, STDOUT_FILENO);
        close(saved_stdout_fd);
        saved_stdout_fd = -1;
    }
    if (pipe_read_fd >= 0) {
        close(pipe_read_fd);
        pipe_read_fd = -1;
    }
}

/* Read exactly n bytes from fd into buf, blocking until all are read. */
static ssize_t read_exact(int fd, void *buf, size_t n)
{
    size_t total = 0;
    while (total < n) {
        ssize_t r = read(fd, (char *)buf + total, n - total);
        if (r < 0) {
            /* Reading should not fail in these tests */
            return r;
        }
        total += (size_t)r;
    }
    return (ssize_t)total;
}

void setUp(void)
{
    redirect_stdout_to_pipe();
}

void tearDown(void)
{
    restore_stdout();
}

/* Test: when there are no pending bytes, nothing is written and bpout remains unchanged. */
void test_write_pending_no_pending_bytes(void)
{
    char buf[8] = {0};
    char *bpout = buf; /* No pending bytes: bpout == outbuf */

    write_pending(buf, &bpout);

    /* Pointer must remain unchanged */
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    /* Ensure nothing was written: set nonblocking and attempt a read */
    int flags = fcntl(pipe_read_fd, F_GETFL);
    TEST_ASSERT_MESSAGE(flags >= 0, "F_GETFL failed");
    TEST_ASSERT_MESSAGE(fcntl(pipe_read_fd, F_SETFL, flags | O_NONBLOCK) == 0, "F_SETFL O_NONBLOCK failed");

    char tmp[4];
    errno = 0;
    ssize_t r = read(pipe_read_fd, tmp, sizeof tmp);

    /* Expect no data available */
    TEST_ASSERT_EQUAL_INT(-1, r);
    TEST_ASSERT_TRUE(errno == EAGAIN || errno == EWOULDBLOCK);

    /* Restore flags */
    (void)fcntl(pipe_read_fd, F_SETFL, flags);
}

/* Test: when bytes are pending, they are written and bpout resets to outbuf. */
void test_write_pending_writes_and_resets_pointer(void)
{
    char buf[16];
    memcpy(buf, "hello", 5);
    char *bpout = buf + 5;

    write_pending(buf, &bpout);

    /* After write, bpout must be reset to outbuf */
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    char out[16] = {0};
    ssize_t n = read_exact(pipe_read_fd, out, 5);
    TEST_ASSERT_EQUAL_INT(5, n);
    TEST_ASSERT_EQUAL_MEMORY("hello", out, 5);
}

/* Test: multiple sequential calls append data correctly and pointers reset. */
void test_write_pending_multiple_calls_appends(void)
{
    char buf[16];
    char *bpout;

    memcpy(buf, "abc", 3);
    bpout = buf + 3;
    write_pending(buf, &bpout);
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    memcpy(buf, "XYZ", 3);
    bpout = buf + 3;
    write_pending(buf, &bpout);
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    char out[8] = {0};
    ssize_t n = read_exact(pipe_read_fd, out, 6);
    TEST_ASSERT_EQUAL_INT(6, n);
    TEST_ASSERT_EQUAL_MEMORY("abcXYZ", out, 6);
}

/* Test: binary data including NUL and high-byte values are passed through unchanged. */
void test_write_pending_handles_binary_data(void)
{
    unsigned char data[] = {0x00, 'A', 0x00, 0x7F, 0x80, 0xFF};
    char buf[sizeof data];
    memcpy(buf, data, sizeof data);
    char *bpout = buf + sizeof data;

    write_pending(buf, &bpout);
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    unsigned char out[sizeof data] = {0};
    ssize_t n = read_exact(pipe_read_fd, out, sizeof data);
    TEST_ASSERT_EQUAL_INT((int)sizeof data, n);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(data, out, sizeof data);

    /* Ensure no extra bytes were written */
    int flags = fcntl(pipe_read_fd, F_GETFL);
    TEST_ASSERT_MESSAGE(flags >= 0, "F_GETFL failed");
    TEST_ASSERT_MESSAGE(fcntl(pipe_read_fd, F_SETFL, flags | O_NONBLOCK) == 0, "F_SETFL O_NONBLOCK failed");
    unsigned char extra[4];
    errno = 0;
    ssize_t r = read(pipe_read_fd, extra, sizeof extra);
    TEST_ASSERT_EQUAL_INT(-1, r);
    TEST_ASSERT_TRUE(errno == EAGAIN || errno == EWOULDBLOCK);
    (void)fcntl(pipe_read_fd, F_SETFL, flags);
}

/* Test: only pending region [outbuf, bpout) is written, not beyond. */
void test_write_pending_writes_only_pending_region(void)
{
    char buf[16];
    memcpy(buf, "pendXXXXX", 10); /* extra bytes after pending marker */
    char *bpout = buf + 4;        /* only "pend" should be written */

    write_pending(buf, &bpout);
    TEST_ASSERT_EQUAL_PTR(buf, bpout);

    char out[16] = {0};
    ssize_t n = read_exact(pipe_read_fd, out, 4);
    TEST_ASSERT_EQUAL_INT(4, n);
    TEST_ASSERT_EQUAL_MEMORY("pend", out, 4);

    /* Verify that extra bytes were NOT written */
    int flags = fcntl(pipe_read_fd, F_GETFL);
    TEST_ASSERT_MESSAGE(flags >= 0, "F_GETFL failed");
    TEST_ASSERT_MESSAGE(fcntl(pipe_read_fd, F_SETFL, flags | O_NONBLOCK) == 0, "F_SETFL O_NONBLOCK failed");
    char extra[8];
    errno = 0;
    ssize_t r = read(pipe_read_fd, extra, sizeof extra);
    TEST_ASSERT_EQUAL_INT(-1, r);
    TEST_ASSERT_TRUE(errno == EAGAIN || errno == EWOULDBLOCK);
    (void)fcntl(pipe_read_fd, F_SETFL, flags);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_write_pending_no_pending_bytes);
    RUN_TEST(test_write_pending_writes_and_resets_pointer);
    RUN_TEST(test_write_pending_multiple_calls_appends);
    RUN_TEST(test_write_pending_handles_binary_data);
    RUN_TEST(test_write_pending_writes_only_pending_region);
    return UNITY_END();
}