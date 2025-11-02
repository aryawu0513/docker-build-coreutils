#include "../../unity/unity.h"
#include <string.h>
#include <stdio.h>

/* We are included into the same translation unit as the program,
   so we can access the static globals and next_line_num directly. */

static int last_digit_index(void) {
    return LINE_COUNTER_BUF_LEN - 3; /* index of last digit (before '\t' and '\0') */
}

static int tab_index(void) {
    return LINE_COUNTER_BUF_LEN - 2;
}

static int nul_index(void) {
    return LINE_COUNTER_BUF_LEN - 1;
}

static int idx_of(char *p) {
    return (int)(p - line_buf);
}

static void init_buffer_all_spaces(void) {
    /* Initialize the entire line_buf to spaces, then set trailing "\t\0". */
    for (int i = 0; i < LINE_COUNTER_BUF_LEN; i++) {
        line_buf[i] = ' ';
    }
    line_buf[tab_index()] = '\t';
    line_buf[nul_index()] = '\0';
}

/* Helper to set up the state before each test. */
static void setup_state(int print_idx, int start_idx, const char *digits) {
    size_t n = strlen(digits);
    TEST_ASSERT_TRUE_MESSAGE(n >= 1, "digits must be non-empty");
    TEST_ASSERT_TRUE_MESSAGE(start_idx >= 0, "start_idx must be >= 0");
    TEST_ASSERT_TRUE_MESSAGE((int)(start_idx + n - 1) <= last_digit_index(),
                             "digits extend beyond last digit position");
    TEST_ASSERT_TRUE_MESSAGE(print_idx >= 0 && print_idx < LINE_COUNTER_BUF_LEN,
                             "print_idx out of range");

    init_buffer_all_spaces();

    /* Place the digits starting at start_idx. */
    for (size_t i = 0; i < n; i++) {
        line_buf[start_idx + (int)i] = digits[i];
    }

    /* Set the global pointers accordingly. */
    line_num_print = line_buf + print_idx;
    line_num_start = line_buf + start_idx;
    line_num_end   = line_buf + start_idx + (int)n - 1;

    /* Sanity: trailing layout intact. */
    TEST_ASSERT_EQUAL_CHAR('\t', line_buf[tab_index()]);
    TEST_ASSERT_EQUAL_CHAR('\0', line_buf[nul_index()]);
}

/* Unity fixtures */
void setUp(void) {
    /* Nothing persistent between tests. */
}

void tearDown(void) {
    /* No-op */
}

/* Tests */

void test_next_line_num_simple_increment_no_carry(void) {
    int print_idx = LINE_COUNTER_BUF_LEN - 8;     /* default initial print position */
    int start_idx = last_digit_index();           /* single digit at default end */
    setup_state(print_idx, start_idx, "0");

    char *old_start = line_num_start;
    char *old_end   = line_num_end;
    char *old_print = line_num_print;

    next_line_num();

    /* Expect 0 -> 1, pointers unchanged */
    TEST_ASSERT_EQUAL_PTR(old_start, line_num_start);
    TEST_ASSERT_EQUAL_PTR(old_end, line_num_end);
    TEST_ASSERT_EQUAL_PTR(old_print, line_num_print);

    TEST_ASSERT_EQUAL_CHAR('1', line_buf[start_idx]);
    TEST_ASSERT_EQUAL_CHAR('\t', line_buf[tab_index()]);
    TEST_ASSERT_EQUAL_CHAR('\0', line_buf[nul_index()]);
}

void test_next_line_num_single_digit_overflow_grows(void) {
    int print_idx = LINE_COUNTER_BUF_LEN - 8;
    int end_idx   = last_digit_index();
    int start_idx = end_idx; /* single digit */
    setup_state(print_idx, start_idx, "9");

    char *old_end   = line_num_end;
    char *old_print = line_num_print;

    next_line_num();

    /* Expect 9 -> 10; start moves left by 1, end unchanged, print unchanged */
    TEST_ASSERT_EQUAL_INT(end_idx - 1, idx_of(line_num_start));
    TEST_ASSERT_EQUAL_PTR(old_end, line_num_end);
    TEST_ASSERT_EQUAL_PTR(old_print, line_num_print);

    TEST_ASSERT_EQUAL_CHAR('1', line_buf[end_idx - 1]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[end_idx]);
}

void test_next_line_num_carry_within_multi_digit(void) {
    int print_idx = LINE_COUNTER_BUF_LEN - 8;
    int end_idx   = last_digit_index();
    int start_idx = end_idx - 1;
    setup_state(print_idx, start_idx, "19");

    char *old_start = line_num_start;
    char *old_end   = line_num_end;

    next_line_num();

    /* 19 -> 20; width unchanged, pointers unchanged */
    TEST_ASSERT_EQUAL_PTR(old_start, line_num_start);
    TEST_ASSERT_EQUAL_PTR(old_end, line_num_end);

    TEST_ASSERT_EQUAL_CHAR('2', line_buf[start_idx + 0]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[start_idx + 1]);
}

void test_next_line_num_multi_digit_overflow_grows(void) {
    int print_idx = LINE_COUNTER_BUF_LEN - 8;
    int end_idx   = last_digit_index();
    int start_idx = end_idx - 1;
    setup_state(print_idx, start_idx, "99");

    char *old_end   = line_num_end;
    char *old_print = line_num_print;

    next_line_num();

    /* 99 -> 100; start moves left by 1, end unchanged, print unchanged */
    TEST_ASSERT_EQUAL_INT(start_idx - 1, idx_of(line_num_start));
    TEST_ASSERT_EQUAL_PTR(old_end, line_num_end);
    TEST_ASSERT_EQUAL_PTR(old_print, line_num_print);

    TEST_ASSERT_EQUAL_CHAR('1', line_buf[start_idx - 1]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[start_idx + 0]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[start_idx + 1]);
}

void test_next_line_num_adjusts_line_num_print_when_crossed(void) {
    /* Make line_num_start == line_num_print and overflow to grow width by one.
       This should decrement line_num_print by 1 as well. */
    int p = LINE_COUNTER_BUF_LEN - 6; /* pick a safe index with room on the left */
    int start_idx = p;
    setup_state(p, start_idx, "9");

    int old_start_idx = idx_of(line_num_start);
    int old_print_idx = idx_of(line_num_print);
    int old_end_idx   = idx_of(line_num_end);

    next_line_num();

    /* After 9 -> 10: start moved left by 1; print should also move left by 1. */
    TEST_ASSERT_EQUAL_INT(old_start_idx - 1, idx_of(line_num_start));
    TEST_ASSERT_EQUAL_INT(old_print_idx - 1, idx_of(line_num_print));
    TEST_ASSERT_EQUAL_INT(old_end_idx,       idx_of(line_num_end));

    TEST_ASSERT_EQUAL_CHAR('1', line_buf[old_start_idx - 1]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[old_start_idx]); /* old start becomes '0' */
}

void test_next_line_num_overflow_at_leftmost_sets_gt(void) {
    /* Put the digits at the very start of the buffer with no room to grow. */
    int start_idx = 0;
    int print_idx = 0; /* realistic: print already followed width expansion over time */
    setup_state(print_idx, start_idx, "9");

    next_line_num();

    /* Expect '>' at position 0, pointers unchanged, print unchanged */
    TEST_ASSERT_EQUAL_INT(0, idx_of(line_num_start));
    TEST_ASSERT_EQUAL_INT(0, idx_of(line_num_end));
    TEST_ASSERT_EQUAL_INT(0, idx_of(line_num_print));

    TEST_ASSERT_EQUAL_CHAR('>', line_buf[0]);
    TEST_ASSERT_EQUAL_CHAR('\t', line_buf[tab_index()]);
    TEST_ASSERT_EQUAL_CHAR('\0', line_buf[nul_index()]);
}

void test_next_line_num_carry_through_trailing_nines(void) {
    int print_idx = LINE_COUNTER_BUF_LEN - 8;
    int end_idx   = last_digit_index();
    int start_idx = end_idx - 3; /* 4 digits total */
    setup_state(print_idx, start_idx, "1299");

    next_line_num();

    /* 1299 -> 1300; width unchanged; start/end unchanged. */
    TEST_ASSERT_EQUAL_INT(start_idx, idx_of(line_num_start));
    TEST_ASSERT_EQUAL_INT(end_idx,   idx_of(line_num_end));
    TEST_ASSERT_EQUAL_INT(print_idx, idx_of(line_num_print));

    TEST_ASSERT_EQUAL_CHAR('1', line_buf[start_idx + 0]);
    TEST_ASSERT_EQUAL_CHAR('3', line_buf[start_idx + 1]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[start_idx + 2]);
    TEST_ASSERT_EQUAL_CHAR('0', line_buf[start_idx + 3]);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_next_line_num_simple_increment_no_carry);
    RUN_TEST(test_next_line_num_single_digit_overflow_grows);
    RUN_TEST(test_next_line_num_carry_within_multi_digit);
    RUN_TEST(test_next_line_num_multi_digit_overflow_grows);
    RUN_TEST(test_next_line_num_adjusts_line_num_print_when_crossed);
    RUN_TEST(test_next_line_num_overflow_at_leftmost_sets_gt);
    RUN_TEST(test_next_line_num_carry_through_trailing_nines);
    return UNITY_END();
}