#include "../../unity/unity.h"
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <stdbool.h>

/* The tests are included into the same translation unit as the program,
   so we can access the static globals and the target static function. */

/* Forward declaration */
static char* run_cat_capture2(const char *input, size_t in_len,
                              bool show_nonprinting, bool show_tabs,
                              bool number, bool number_nonblank,
                              bool show_ends, bool squeeze_blank,
                              idx_t insize, idx_t outsize,
                              size_t *out_len, bool *ok_ret);

/* Helper: reset global numbering and state to their initial values. */
static void reset_state(void) {
  /* Reset state globals if they exist */
  newlines2 = 0;
  pending_cr = false;
  
  /* Only reset line numbering if LINE_COUNTER_BUF_LEN is defined */
  #ifdef LINE_COUNTER_BUF_LEN
  for (int i = 0; i < LINE_COUNTER_BUF_LEN; i++) {
    line_buf[i] = ' ';
  }
  line_buf[LINE_COUNTER_BUF_LEN - 3] = '0';
  line_buf[LINE_COUNTER_BUF_LEN - 2] = '\t';
  line_buf[LINE_COUNTER_BUF_LEN - 1] = '\0';
  line_num_print = line_buf + LINE_COUNTER_BUF_LEN - 8;
  line_num_start = line_buf + LINE_COUNTER_BUF_LEN - 3;
  line_num_end   = line_buf + LINE_COUNTER_BUF_LEN - 3;
  #endif
}

/* Main capture function - handles I/O redirection and calls cat() */
static char* run_cat_capture2(const char *input, size_t in_len,
                              bool show_nonprinting, bool show_tabs,
                              bool number, bool number_nonblank,
                              bool show_ends, bool squeeze_blank,
                              idx_t insize, idx_t outsize,
                              size_t *out_len, bool *ok_ret)
{
  int inpipe[2];
  int outpipe[2];
  int saved_stdout = -1;
  char *captured = NULL;

  /* Create pipes - use TEST_ASSERT here, stdout not yet redirected */
  TEST_ASSERT_EQUAL_INT_MESSAGE(0, pipe(inpipe), "pipe() failed for input");
  TEST_ASSERT_EQUAL_INT_MESSAGE(0, pipe(outpipe), "pipe() failed for output");

  /* Fill input and close writer */
  if (in_len > 0) {
    ssize_t w = write(inpipe[1], input, in_len);
    TEST_ASSERT_EQUAL_INT64_MESSAGE((ssize_t)in_len, w, "input write failed");
  }
  close(inpipe[1]);

  /* Redirect stdout to outpipe[1] */
  saved_stdout = dup(STDOUT_FILENO);
  TEST_ASSERT_TRUE_MESSAGE(saved_stdout >= 0, "dup(STDOUT) failed");
  
  /* CRITICAL: After this point, don't use TEST_ASSERT until stdout is restored!
     Unity's TEST_ASSERT macros write to stdout, which is now redirected. */
  if (dup2(outpipe[1], STDOUT_FILENO) < 0) {
    fprintf(stderr, "ERROR: dup2 failed\n");
    return NULL;
  }
  close(outpipe[1]);

  /* Reset cat state and set globals */
  reset_state();
  infile = "test_input";
  input_desc = inpipe[0];

  /* Allocate buffers */
  char *inbuf = (char*)malloc((size_t)insize + 2);
  char *outbuf = (char*)malloc((size_t)outsize + 2);
  if (!inbuf || !outbuf) {
    fprintf(stderr, "ERROR: malloc failed\n");
    free(inbuf);
    free(outbuf);
    return NULL;
  }

  /* Call the cat() function being tested */
  bool ret = cat(inbuf, insize, outbuf, outsize,
                 show_nonprinting, show_tabs, number, number_nonblank,
                 show_ends, squeeze_blank);

  /* Restore stdout - now TEST_ASSERT is safe to use again */
  if (dup2(saved_stdout, STDOUT_FILENO) < 0) {
    fprintf(stderr, "ERROR: restore dup2 failed\n");
  }
  close(saved_stdout);

  /* Read all output from the pipe */
  close(inpipe[0]);
  
  size_t cap = 1024;
  size_t len = 0;
  captured = (char*)malloc(cap);
  TEST_ASSERT_NOT_NULL(captured);

  for (;;) {
    char buf[4096];
    ssize_t r = read(outpipe[0], buf, sizeof buf);
    if (r < 0) {
      TEST_FAIL_MESSAGE("read from output pipe failed");
      break;
    }
    if (r == 0) break;
    
    if (len + (size_t)r > cap) {
      cap = (len + (size_t)r) * 2;
      captured = (char*)realloc(captured, cap);
      TEST_ASSERT_NOT_NULL(captured);
    }
    memcpy(captured + len, buf, (size_t)r);
    len += (size_t)r;
  }
  close(outpipe[0]);

  free(inbuf);
  free(outbuf);

  if (out_len) *out_len = len;
  if (ok_ret) *ok_ret = ret;

  /* Null-terminate for convenience in string assertions */
  captured = (char*)realloc(captured, len + 1);
  TEST_ASSERT_NOT_NULL(captured);
  captured[len] = '\0';
  
  return captured;
}

/* Convenience wrapper using sane defaults for insize/outsize */
static char* run_cat(const char *input, size_t in_len,
                     bool v, bool T, bool n, bool b, bool E, bool s,
                     size_t *out_len, bool *ok_ret)
{
  /* Use small sizes to exercise buffer logic */
  return run_cat_capture2(input, in_len, v, T, n, b, E, s, 4, 3, out_len, ok_ret);
}

/* Helper to validate numbered lines */
static void assert_line_with_optional_label(const char *line_start,
                                            const char *expected_content,
                                            int expected_num,
                                            bool expect_label)
{
  const char *p = line_start;
  const char *nl = strchr(p, '\n');
  TEST_ASSERT_NOT_NULL_MESSAGE(nl, "Line not terminated by newline");
  const char *tab = memchr(p, '\t', (size_t)(nl - p));

  if (expect_label) {
    TEST_ASSERT_NOT_NULL_MESSAGE(tab, "Expected a label ending with tab");
    
    /* Parse digits before tab, skipping spaces and possible '>' overflow marker */
    const char *q = p;
    while (q < tab && (*q == ' ' || *q == '>')) q++;
    TEST_ASSERT_TRUE_MESSAGE(q < tab, "No digits before tab");
    
    /* Extract digits */
    char numbuf[64];
    size_t nd = 0;
    while (q < tab && nd + 1 < sizeof numbuf) {
      TEST_ASSERT_TRUE_MESSAGE(*q >= '0' && *q <= '9', "Non-digit in label");
      numbuf[nd++] = *q++;
    }
    numbuf[nd] = '\0';
    
    char expbuf[64];
    snprintf(expbuf, sizeof expbuf, "%d", expected_num);
    TEST_ASSERT_EQUAL_STRING(expbuf, numbuf);

    /* Content after tab up to newline should match expected_content */
    size_t content_len = (size_t)(nl - (tab + 1));
    TEST_ASSERT_EQUAL_size_t(strlen(expected_content), content_len);
    TEST_ASSERT_EQUAL_INT(0, memcmp(tab + 1, expected_content, content_len));
  } else {
    /* No label expected */
    if (tab && tab < nl) {
      /* If a tab exists, it must be part of content */
      TEST_ASSERT_TRUE_MESSAGE(expected_content[0] == '\t', "Unexpected label/tab found");
    }
    size_t content_len = (size_t)(nl - p);
    TEST_ASSERT_EQUAL_size_t(strlen(expected_content), content_len);
    TEST_ASSERT_EQUAL_INT(0, memcmp(p, expected_content, content_len));
  }
}

/* Unity hooks */
void setUp(void) {
  /* Don't call reset_state here - it might fail if globals don't exist */
}

void tearDown(void) {
  /* Nothing */
}

/* Tests */

static void test_cat_basic_copy(void) {
  const char *in = "Hello\nWorld\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, false, false, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_size_t(strlen(in), out_len);
  TEST_ASSERT_EQUAL_INT(0, memcmp(in, out, out_len));
  free(out);
}

static void test_cat_show_tabs_only(void) {
  const char *in = "a\tb\n\t\n";
  const char *exp = "a^Ib\n^I\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, true, false, false, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_show_nonprinting_no_tabs(void) {
  const char in_bytes[] = { 0x01, '\t', 0x7f, (char)0x80, (char)0x9b, (char)0xff, '\n', 0 };
  const char *exp = "^A\t^?M-^@M-^[M-^?\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in_bytes, 7, true, false, false, false, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_show_nonprinting_with_tabs(void) {
  const char in_bytes[] = { 0x01, '\t', 0x7f, (char)0x80, (char)0x9b, (char)0xff, '\n', 0 };
  const char *exp = "^A^I^?M-^@M-^[M-^?\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in_bytes, 7, true, true, false, false, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_show_ends_simple(void) {
  const char *in = "ab\n\n";
  const char *exp = "ab$\n$\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, false, false, true, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_show_ends_crlf_boundary(void) {
  /* Use insize=1 to force CR at end of input buffer to exercise pending_cr path */
  const char *in = "A\r\nB\r\n";
  const char *exp = "A^M$\nB^M$\n";
  size_t out_len = 0;
  bool ok = false;
  
  /* Custom capture with insize=1 */
  char *out = run_cat_capture2(in, strlen(in), false, false, false, false, true, false,
                               1, 3, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_number_all_lines(void) {
  const char *in = "a\n\nb\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, true, false, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);

  /* Parse three lines: expect labels 1,2,3 with contents "a", "", "b" */
  const char *p = out;
  const char *l1 = p;
  const char *nl1 = strchr(l1, '\n');
  TEST_ASSERT_NOT_NULL(nl1);
  assert_line_with_optional_label(l1, "a", 1, true);
  
  const char *l2 = nl1 + 1;
  const char *nl2 = strchr(l2, '\n');
  TEST_ASSERT_NOT_NULL(nl2);
  /* Blank line with -n: label then nothing before newline */
  assert_line_with_optional_label(l2, "", 2, true);
  
  const char *l3 = nl2 + 1;
  const char *nl3 = strchr(l3, '\n');
  TEST_ASSERT_NOT_NULL(nl3);
  assert_line_with_optional_label(l3, "b", 3, true);
  
  /* Ensure no more data */
  TEST_ASSERT_EQUAL_PTR(out + out_len, nl3 + 1);

  free(out);
}

static void test_cat_number_nonblank(void) {
  const char *in = "a\n\nb\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, true, true, false, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);

  /* Expect labels only on nonblank: line1 #1 "a", line2 no label empty, line3 #2 "b" */
  const char *p = out;
  const char *l1 = p;
  const char *nl1 = strchr(l1, '\n');
  TEST_ASSERT_NOT_NULL(nl1);
  assert_line_with_optional_label(l1, "a", 1, true);
  
  const char *l2 = nl1 + 1;
  const char *nl2 = strchr(l2, '\n');
  TEST_ASSERT_NOT_NULL(nl2);
  /* Blank line without numbering: content is empty string (just newline) */
  assert_line_with_optional_label(l2, "", 0, false);
  
  const char *l3 = nl2 + 1;
  const char *nl3 = strchr(l3, '\n');
  TEST_ASSERT_NOT_NULL(nl3);
  assert_line_with_optional_label(l3, "b", 2, true);
  
  TEST_ASSERT_EQUAL_PTR(out + out_len, nl3 + 1);

  free(out);
}

static void test_cat_squeeze_blank(void) {
  const char *in = "a\n\n\n\nb\n";
  const char *exp = "a\n\nb\n";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, false, false, false, true, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_squeeze_blank_with_number_nonblank(void) {
  const char *in = "\n\n\n";
  const char *exp = "\n"; /* squeezed to one blank line, and -b avoids numbering blank lines */
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, true, true, false, true, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

static void test_cat_show_ends_no_trailing_newline(void) {
  const char *in = "noendl";
  const char *exp = "noendl";
  size_t out_len = 0;
  bool ok = false;
  
  char *out = run_cat(in, strlen(in), false, false, false, false, true, false, &out_len, &ok);
  
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_STRING(exp, out);
  free(out);
}

/* Main */
int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_cat_basic_copy);
  RUN_TEST(test_cat_show_tabs_only);
  RUN_TEST(test_cat_show_nonprinting_no_tabs);
  RUN_TEST(test_cat_show_nonprinting_with_tabs);
  RUN_TEST(test_cat_show_ends_simple);
  RUN_TEST(test_cat_show_ends_crlf_boundary);
  RUN_TEST(test_cat_number_all_lines);
  RUN_TEST(test_cat_number_nonblank);
  RUN_TEST(test_cat_squeeze_blank);
  RUN_TEST(test_cat_squeeze_blank_with_number_nonblank);
  RUN_TEST(test_cat_show_ends_no_trailing_newline);
  return UNITY_END();
}