#include "../../unity/unity.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

/* Access program internals (these are defined in the same translation unit) */
extern bool simple_cat (char *buf, idx_t bufsize);

/* Globals from the program under test (file-scope static there, but visible here) */
extern int input_desc;
extern char const *infile;

/* Helper: create a temporary file, optionally write data, rewind, unlink, return fd */
static int create_temp_file_with_data (const unsigned char *data, size_t len)
{
  char tmpl[] = "/tmp/simple_cat_test_XXXXXX";
  int fd = mkstemp(tmpl);
  TEST_ASSERT_MESSAGE(fd >= 0, "mkstemp failed");

  /* Unlink so it is removed automatically after close */
  unlink(tmpl);

  if (len > 0)
    {
      size_t off = 0;
      while (off < len)
        {
          ssize_t w = write(fd, data + off, len - off);
          TEST_ASSERT_MESSAGE(w >= 0, "write to temp file failed");
          off += (size_t) w;
        }
    }
  /* Rewind for reading */
  off_t r = lseek(fd, 0, SEEK_SET);
  TEST_ASSERT_MESSAGE(r == 0, "lseek failed");
  return fd;
}

/* Helper: create empty temp file for output capture */
static int create_temp_output_file (void)
{
  return create_temp_file_with_data(NULL, 0);
}

/* Helper: save and redirect stdout to given fd */
static int redirect_stdout_to_fd (int out_fd)
{
  int saved = dup(STDOUT_FILENO);
  TEST_ASSERT_MESSAGE(saved >= 0, "dup(STDOUT_FILENO) failed");
  int rc = dup2(out_fd, STDOUT_FILENO);
  TEST_ASSERT_MESSAGE(rc >= 0, "dup2 to STDOUT failed");
  return saved;
}

/* Helper: restore stdout from saved fd */
static void restore_stdout_from_fd (int saved_fd)
{
  int rc = dup2(saved_fd, STDOUT_FILENO);
  TEST_ASSERT_MESSAGE(rc >= 0, "restore dup2 failed");
  close(saved_fd);
}

/* Helper: get file size via fstat */
static off_t get_fd_size (int fd)
{
  struct stat st;
  int rc = fstat(fd, &st);
  TEST_ASSERT_MESSAGE(rc == 0, "fstat failed");
  return st.st_size;
}

/* Helper: read all bytes from fd into buffer of given length, and ensure EOF thereafter */
static void read_exact_from_fd (int fd, unsigned char *buf, size_t len)
{
  off_t r0 = lseek(fd, 0, SEEK_SET);
  TEST_ASSERT_MESSAGE(r0 == 0, "lseek start failed");

  size_t off = 0;
  while (off < len)
    {
      ssize_t nr = read(fd, buf + off, len - off);
      TEST_ASSERT_MESSAGE(nr >= 0, "read from fd failed");
      TEST_ASSERT_MESSAGE(nr > 0, "unexpected EOF in output");
      off += (size_t) nr;
    }
  unsigned char extra;
  ssize_t nr = read(fd, &extra, 1);
  TEST_ASSERT_MESSAGE(nr == 0, "output has unexpected extra bytes");
}

/* Helper: generate a pattern buffer of given length */
static unsigned char *make_pattern (size_t len)
{
  unsigned char *p = (unsigned char *)malloc(len ? len : 1);
  TEST_ASSERT_NOT_NULL(p);
  for (size_t i = 0; i < len; i++)
    p[i] = (unsigned char)('A' + (int)(i % 26));
  return p;
}

void setUp(void) {
  /* no-op */
}

void tearDown(void) {
  /* no-op */
}

void test_simple_cat_empty_input(void)
{
  /* Prepare empty input */
  int in_fd = create_temp_file_with_data(NULL, 0);
  input_desc = in_fd;
  infile = "empty-input";

  /* Capture stdout */
  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char buf[16];
  bool ok = simple_cat(buf, sizeof buf);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_TRUE_MESSAGE(ok, "simple_cat should return true on EOF (empty input)");
  TEST_ASSERT_EQUAL_INT64(0, (long long)get_fd_size(out_fd));

  close(in_fd);
  close(out_fd);
}

void test_simple_cat_small_input_less_than_buffer(void)
{
  const char *msg = "Hello, world!";
  size_t len = strlen(msg);

  int in_fd = create_temp_file_with_data((const unsigned char *)msg, len);
  input_desc = in_fd;
  infile = "small-input";

  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char buf[64]; /* larger than input */
  bool ok = simple_cat(buf, sizeof buf);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_INT64((long long)len, (long long)get_fd_size(out_fd));

  unsigned char *out = (unsigned char *)malloc(len ? len : 1);
  TEST_ASSERT_NOT_NULL(out);
  read_exact_from_fd(out_fd, out, len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY((const unsigned char *)msg, out, len);

  free(out);
  close(in_fd);
  close(out_fd);
}

void test_simple_cat_exact_buffer_size(void)
{
  size_t bufsize = 1024;
  unsigned char *data = make_pattern(bufsize);

  int in_fd = create_temp_file_with_data(data, bufsize);
  input_desc = in_fd;
  infile = "exact-bufsize";

  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char *buf = (char *)malloc(bufsize);
  TEST_ASSERT_NOT_NULL(buf);
  bool ok = simple_cat(buf, (idx_t)bufsize);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_INT64((long long)bufsize, (long long)get_fd_size(out_fd));

  unsigned char *out = (unsigned char *)malloc(bufsize);
  TEST_ASSERT_NOT_NULL(out);
  read_exact_from_fd(out_fd, out, bufsize);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(data, out, bufsize);

  free(out);
  free(buf);
  free(data);
  close(in_fd);
  close(out_fd);
}

void test_simple_cat_multiple_blocks_non_aligned(void)
{
  size_t bufsize = 1024;
  size_t len = 2 * bufsize + 453; /* not aligned to bufsize */
  unsigned char *data = make_pattern(len);

  int in_fd = create_temp_file_with_data(data, len);
  input_desc = in_fd;
  infile = "multi-nonaligned";

  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char *buf = (char *)malloc(bufsize);
  TEST_ASSERT_NOT_NULL(buf);
  bool ok = simple_cat(buf, (idx_t)bufsize);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_INT64((long long)len, (long long)get_fd_size(out_fd));

  unsigned char *out = (unsigned char *)malloc(len);
  TEST_ASSERT_NOT_NULL(out);
  read_exact_from_fd(out_fd, out, len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(data, out, len);

  free(out);
  free(buf);
  free(data);
  close(in_fd);
  close(out_fd);
}

void test_simple_cat_one_byte_buffer(void)
{
  size_t len = 2000; /* small enough */
  unsigned char *data = make_pattern(len);

  int in_fd = create_temp_file_with_data(data, len);
  input_desc = in_fd;
  infile = "one-byte-buf";

  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char buf[1]; /* bufsize = 1 exercises tight loop path */
  bool ok = simple_cat(buf, (idx_t)sizeof buf);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_INT64((long long)len, (long long)get_fd_size(out_fd));

  unsigned char *out = (unsigned char *)malloc(len);
  TEST_ASSERT_NOT_NULL(out);
  read_exact_from_fd(out_fd, out, len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(data, out, len);

  free(out);
  free(data);
  close(in_fd);
  close(out_fd);
}

void test_simple_cat_read_error_bad_fd(void)
{
  /* Intentionally set an invalid descriptor */
  input_desc = -1;
  infile = "bad-fd";

  int out_fd = create_temp_output_file();
  int saved = redirect_stdout_to_fd(out_fd);

  char buf[32];
  bool ok = simple_cat(buf, sizeof buf);

  restore_stdout_from_fd(saved);

  TEST_ASSERT_FALSE_MESSAGE(ok, "simple_cat should return false on read error");
  TEST_ASSERT_EQUAL_INT64(0, (long long)get_fd_size(out_fd));

  close(out_fd);
}

void test_unity(void)
{
  TEST_ASSERT_EQUAL_INT64(0, 0);
}


int main(void)
{
  UNITY_BEGIN();

  RUN_TEST(test_simple_cat_empty_input);
  RUN_TEST(test_simple_cat_small_input_less_than_buffer);
  RUN_TEST(test_simple_cat_exact_buffer_size);
  RUN_TEST(test_simple_cat_multiple_blocks_non_aligned);
  RUN_TEST(test_simple_cat_one_byte_buffer);
  RUN_TEST(test_simple_cat_read_error_bad_fd);
  RUN_TEST(test_unity);
  return UNITY_END();
}