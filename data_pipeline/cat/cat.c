/* cat -- concatenate files and print on the standard output.
   Copyright (C) 1988-2025 Free Software Foundation, Inc.

   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <https://www.gnu.org/licenses/>.  */

/* Differences from the Unix cat:
   * Always unbuffered, -u is ignored.
   * Usually much faster than other versions of cat, the difference
   is especially apparent when using the -v option.

   By tege@sics.se, Torbjörn Granlund, advised by rms, Richard Stallman.  */

#include <config.h>

#include <stdio.h>
#include <getopt.h>
#include <sys/types.h>

#if HAVE_STROPTS_H
# include <stropts.h>
#endif
#include <sys/ioctl.h>

#include "system.h"
#include "alignalloc.h"
#include "ioblksize.h"
#include "fadvise.h"
#include "full-write.h"
#include "xbinary-io.h"

/* The official name of this program (e.g., no 'g' prefix).  */
#define PROGRAM_NAME "cat"

#define AUTHORS \
  proper_name_lite ("Torbjorn Granlund", "Torbj\303\266rn Granlund"), \
  proper_name ("Richard M. Stallman")

/* Name of input file.  May be "-".  */
static char const *infile;

/* Descriptor on which input file is open.  */
static int input_desc;

/* Buffer for line numbers.
   An 11 digit counter may overflow within an hour on a P2/466,
   an 18 digit counter needs about 1000y */
#define LINE_COUNTER_BUF_LEN 20
static char line_buf[LINE_COUNTER_BUF_LEN] =
  {
    ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
    ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', '0',
    '\t', '\0'
  };

/* Position in 'line_buf' where printing starts.  This will not change
   unless the number of lines is larger than 999999.  */
static char *line_num_print = line_buf + LINE_COUNTER_BUF_LEN - 8;

/* Position of the first digit in 'line_buf'.  */
static char *line_num_start = line_buf + LINE_COUNTER_BUF_LEN - 3;

/* Position of the last digit in 'line_buf'.  */
static char *line_num_end = line_buf + LINE_COUNTER_BUF_LEN - 3;

/* Preserves the 'cat' function's local 'newlines' between invocations.  */
static int newlines2 = 0;

/* Whether there is a pending CR to process.  */
static bool pending_cr = false;

void
usage (int status)
{
  if (status != EXIT_SUCCESS)
    emit_try_help ();
  else
    {
      printf (_("\
Usage: %s [OPTION]... [FILE]...\n\
"),
              program_name);
      fputs (_("\
Concatenate FILE(s) to standard output.\n\
"), stdout);

      emit_stdin_note ();

      fputs (_("\
\n\
  -A, --show-all           equivalent to -vET\n\
  -b, --number-nonblank    number nonempty output lines, overrides -n\n\
  -e                       equivalent to -vE\n\
  -E, --show-ends          display $ at end of each line\n\
  -n, --number             number all output lines\n\
  -s, --squeeze-blank      suppress repeated empty output lines\n\
"), stdout);
      fputs (_("\
  -t                       equivalent to -vT\n\
  -T, --show-tabs          display TAB characters as ^I\n\
  -u                       (ignored)\n\
  -v, --show-nonprinting   use ^ and M- notation, except for LFD and TAB\n\
"), stdout);
      fputs (HELP_OPTION_DESCRIPTION, stdout);
      fputs (VERSION_OPTION_DESCRIPTION, stdout);
      printf (_("\
\n\
Examples:\n\
  %s f - g  Output f's contents, then standard input, then g's contents.\n\
  %s        Copy standard input to standard output.\n\
"),
              program_name, program_name);
      emit_ancillary_info (PROGRAM_NAME);
    }
  exit (status);
}

/* Compute the next line number.  */

static void
next_line_num (void)
{
  char *endp = line_num_end;
  do
    {
      if ((*endp)++ < '9')
        return;
      *endp-- = '0';
    }
  while (endp >= line_num_start);

  if (line_num_start > line_buf)
    *--line_num_start = '1';
  else
    *line_buf = '>';
  if (line_num_start < line_num_print)
    line_num_print--;
}

/* Plain cat.  Copy the file behind 'input_desc' to STDOUT_FILENO.
   BUF (of size BUFSIZE) is the I/O buffer, used by reads and writes.
   Return true if successful.  */

static bool
simple_cat (char *buf, idx_t bufsize)
{
  /* Loop until the end of the file.  */

  while (true)
    {
      /* Read a block of input.  */

      ssize_t n_read = read (input_desc, buf, bufsize);
      if (n_read < 0)
        {
          error (0, errno, "%s", quotef (infile));
          return false;
        }

      /* End of this file?  */

      if (n_read == 0)
        return true;

      /* Write this block out.  */

      if (full_write (STDOUT_FILENO, buf, n_read) != n_read)
        write_error ();
    }
}

/* Write any pending output to STDOUT_FILENO.
   Pending is defined to be the *BPOUT - OUTBUF bytes starting at OUTBUF.
   Then set *BPOUT to OUTPUT if it's not already that value.  */

static inline void
write_pending (char *outbuf, char **bpout)
{
  idx_t n_write = *bpout - outbuf;
  if (0 < n_write)
    {
      if (full_write (STDOUT_FILENO, outbuf, n_write) != n_write)
        write_error ();
      *bpout = outbuf;
    }
}

/* Copy the file behind 'input_desc' to STDOUT_FILENO.
   Use INBUF and read INSIZE with each call,
   and OUTBUF and write OUTSIZE with each call.
   (The buffers are a bit larger than the I/O sizes.)
   The remaining boolean args say what 'cat' options to use.

   Return true if successful.
   Called if any option more than -u was specified.

   A newline character is always put at the end of the buffer, to make
   an explicit test for buffer end unnecessary.  */

static bool
cat (char *inbuf, idx_t insize, char *outbuf, idx_t outsize,
     bool show_nonprinting, bool show_tabs, bool number, bool number_nonblank,
     bool show_ends, bool squeeze_blank)
{
  /* Last character read from the input buffer.  */
  unsigned char ch;

  /* Determines how many consecutive newlines there have been in the
     input.  0 newlines makes NEWLINES -1, 1 newline makes NEWLINES 1,
     etc.  Initially 0 to indicate that we are at the beginning of a
     new line.  The "state" of the procedure is determined by
     NEWLINES.  */
  int newlines = newlines2;

#ifdef FIONREAD
  /* If nonzero, use the FIONREAD ioctl, as an optimization.
     (On Ultrix, it is not supported on NFS file systems.)  */
  bool use_fionread = true;
#endif

  /* The inbuf pointers are initialized so that BPIN > EOB, and thereby input
     is read immediately.  */

  /* Pointer to the first non-valid byte in the input buffer, i.e., the
     current end of the buffer.  */
  char *eob = inbuf;

  /* Pointer to the next character in the input buffer.  */
  char *bpin = eob + 1;

  /* Pointer to the position where the next character shall be written.  */
  char *bpout = outbuf;

  while (true)
    {
      do
        {
          /* Write if there are at least OUTSIZE bytes in OUTBUF.  */

          if (outbuf + outsize <= bpout)
            {
              char *wp = outbuf;
              idx_t remaining_bytes;
              do
                {
                  if (full_write (STDOUT_FILENO, wp, outsize) != outsize)
                    write_error ();
                  wp += outsize;
                  remaining_bytes = bpout - wp;
                }
              while (outsize <= remaining_bytes);

              /* Move the remaining bytes to the beginning of the
                 buffer.  */

              memmove (outbuf, wp, remaining_bytes);
              bpout = outbuf + remaining_bytes;
            }

          /* Is INBUF empty?  */

          if (bpin > eob)
            {
              bool input_pending = false;
#ifdef FIONREAD
              int n_to_read = 0;

              /* Is there any input to read immediately?
                 If not, we are about to wait,
                 so write all buffered output before waiting.  */

              if (use_fionread
                  && ioctl (input_desc, FIONREAD, &n_to_read) < 0)
                {
                  /* Ultrix returns EOPNOTSUPP on NFS;
                     HP-UX returns ENOTTY on pipes.
                     SunOS returns EINVAL and
                     More/BSD returns ENODEV on special files
                     like /dev/null.
                     Irix-5 returns ENOSYS on pipes.  */
                  if (errno == EOPNOTSUPP || errno == ENOTTY
                      || errno == EINVAL || errno == ENODEV
                      || errno == ENOSYS)
                    use_fionread = false;
                  else
                    {
                      error (0, errno, _("cannot do ioctl on %s"),
                             quoteaf (infile));
                      newlines2 = newlines;
                      return false;
                    }
                }
              if (n_to_read != 0)
                input_pending = true;
#endif

              if (!input_pending)
                write_pending (outbuf, &bpout);

              /* Read more input into INBUF.  */

              ssize_t n_read = read (input_desc, inbuf, insize);
              if (n_read < 0)
                {
                  error (0, errno, "%s", quotef (infile));
                  write_pending (outbuf, &bpout);
                  newlines2 = newlines;
                  return false;
                }
              if (n_read == 0)
                {
                  write_pending (outbuf, &bpout);
                  newlines2 = newlines;
                  return true;
                }

              /* Update the pointers and insert a sentinel at the buffer
                 end.  */

              bpin = inbuf;
              eob = bpin + n_read;
              *eob = '\n';
            }
          else
            {
              /* It was a real (not a sentinel) newline.  */

              /* Was the last line empty?
                 (i.e., have two or more consecutive newlines been read?)  */

              if (++newlines > 0)
                {
                  if (newlines >= 2)
                    {
                      /* Limit this to 2 here.  Otherwise, with lots of
                         consecutive newlines, the counter could wrap
                         around at INT_MAX.  */
                      newlines = 2;

                      /* Are multiple adjacent empty lines to be substituted
                         by single ditto (-s), and this was the second empty
                         line?  */
                      if (squeeze_blank)
                        {
                          ch = *bpin++;
                          continue;
                        }
                    }

                  /* Are line numbers to be written at empty lines (-n)?  */

                  if (number && !number_nonblank)
                    {
                      next_line_num ();
                      bpout = stpcpy (bpout, line_num_print);
                    }
                }

              /* Output a currency symbol if requested (-e).  */
              if (show_ends)
                {
                  if (pending_cr)
                    {
                      *bpout++ = '^';
                      *bpout++ = 'M';
                      pending_cr = false;
                    }
                  *bpout++ = '$';
                }

              /* Output the newline.  */

              *bpout++ = '\n';
            }
          ch = *bpin++;
        }
      while (ch == '\n');

      /* Here CH cannot contain a newline character.  */

      if (pending_cr)
        {
          *bpout++ = '\r';
          pending_cr = false;
        }

      /* Are we at the beginning of a line, and line numbers are requested?  */

      if (newlines >= 0 && number)
        {
          next_line_num ();
          bpout = stpcpy (bpout, line_num_print);
        }

      /* The loops below continue until a newline character is found,
         which means that the buffer is empty or that a proper newline
         has been found.  */

      /* If quoting, i.e., at least one of -v, -e, or -t specified,
         scan for chars that need conversion.  */
      if (show_nonprinting)
        {
          while (true)
            {
              if (ch >= 32)
                {
                  if (ch < 127)
                    *bpout++ = ch;
                  else if (ch == 127)
                    {
                      *bpout++ = '^';
                      *bpout++ = '?';
                    }
                  else
                    {
                      *bpout++ = 'M';
                      *bpout++ = '-';
                      if (ch >= 128 + 32)
                        {
                          if (ch < 128 + 127)
                            *bpout++ = ch - 128;
                          else
                            {
                              *bpout++ = '^';
                              *bpout++ = '?';
                            }
                        }
                      else
                        {
                          *bpout++ = '^';
                          *bpout++ = ch - 128 + 64;
                        }
                    }
                }
              else if (ch == '\t' && !show_tabs)
                *bpout++ = '\t';
              else if (ch == '\n')
                {
                  newlines = -1;
                  break;
                }
              else
                {
                  *bpout++ = '^';
                  *bpout++ = ch + 64;
                }

              ch = *bpin++;
            }
        }
      else
        {
          /* Not quoting, neither of -v, -e, or -t specified.  */
          while (true)
            {
              if (ch == '\t' && show_tabs)
                {
                  *bpout++ = '^';
                  *bpout++ = ch + 64;
                }
              else if (ch != '\n')
                {
                  if (ch == '\r' && *bpin == '\n' && show_ends)
                    {
                      if (bpin == eob)
                        pending_cr = true;
                      else
                        {
                          *bpout++ = '^';
                          *bpout++ = 'M';
                        }
                    }
                  else
                    *bpout++ = ch;
                }
              else
                {
                  newlines = -1;
                  break;
                }

              ch = *bpin++;
            }
        }
    }
}

/* Copy data from input to output using copy_file_range if possible.
   Return 1 if successful, 0 if ordinary read+write should be tried,
   -1 if a serious problem has been diagnosed.  */

static int
copy_cat (void)
{
  /* Copy at most COPY_MAX bytes at a time; this is min
     (SSIZE_MAX, SIZE_MAX) truncated to a value that is
     surely aligned well.  */
  ssize_t copy_max = MIN (SSIZE_MAX, SIZE_MAX) >> 30 << 30;

  /* copy_file_range does not support some cases, and it
     incorrectly returns 0 when reading from the proc file
     system on the Linux kernel through at least 5.6.19 (2020),
     so fall back on read+write if the copy_file_range is
     unsupported or the input file seems empty.  */

  for (bool some_copied = false; ; some_copied = true)
    switch (copy_file_range (input_desc, nullptr, STDOUT_FILENO, nullptr,
                             copy_max, 0))
      {
      case 0:
        return some_copied;

      case -1:
        if (errno == ENOSYS || is_ENOTSUP (errno) || errno == EINVAL
            || errno == EBADF || errno == EXDEV || errno == ETXTBSY
            || errno == EPERM)
          return 0;
        error (0, errno, "%s", quotef (infile));
        return -1;
      }
}