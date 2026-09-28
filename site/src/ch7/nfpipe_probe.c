#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static unsigned char fd_storage[8192] __attribute__((aligned(4096)));
static unsigned char write_storage[8192] __attribute__((aligned(4096)));
static unsigned char read_storage[8192] __attribute__((aligned(4096)));

static unsigned char pattern(int offset)
{
    return (unsigned char)(offset * 37 + 11);
}

int main(void)
{
    uint64 *fds = (uint64 *)(fd_storage + 4096 - sizeof(uint64));
    unsigned char *data = write_storage + 4090;
    unsigned char *received = read_storage + 4080;
    assert_eq(pipe(fds), 0);
    assert_eq((uint64)fds % 4096, 4088);
    for (int i = 0; i < 3000; i++)
        data[i] = pattern(i);

    int pid = fork();
    assert(pid >= 0);
    if (pid == 0) {
        assert_eq(close(fds[1]), 0);
        int total = 0;
        int reads = 0;
        int short_reads = 0;
        while (total < 3000) {
            int n = read(fds[0], received, 137);
            assert(n > 0 && n <= 137 && total + n <= 3000);
            for (int i = 0; i < n; i++)
                assert_eq(received[i], pattern(total + i));
            total += n;
            reads++;
            if (n < 137)
                short_reads++;
        }
        assert_eq(read(fds[0], received, 1), -1);
        assert_eq(close(fds[0]), 0);
        printf("NFPIPE read bytes=%d calls=%d short=%d eof=-1\n", total, reads, short_reads);
        return 0;
    }

    assert_eq(close(fds[0]), 0);
    assert_eq(write(fds[1], data, 3000), 3000);
    assert_eq(close(fds[1]), 0);
    int status = -1;
    assert_eq(wait(&status), pid);
    assert_eq(status, 0);
    puts("NFPIPE write bytes=3000 pattern=37*i+11");

    uint64 ends[2];
    assert_eq(pipe(ends), 0);
    assert_eq(close(ends[0]), 0);
    assert_eq(write(ends[1], data, 1), -1);
    assert_eq(close(ends[1]), 0);
    puts("NFPIPE closed-reader write=-1");

    uint64 held[8][2];
    int count = 0;
    while (count < 8 && pipe(held[count]) == 0)
        count++;
    assert_eq(count, 6);
    assert_eq(pipe(ends), -1);
    for (int i = 0; i < count; i++) {
        assert_eq(close(held[i][0]), 0);
        assert_eq(close(held[i][1]), 0);
    }
    assert_eq(pipe(ends), 0);
    assert_eq(close(ends[0]), 0);
    assert_eq(close(ends[1]), 0);
    printf("NFPIPE descriptor pairs=%d rollback=ok\n", count);
    puts("NFPIPE ALL PASSED");
    return 0;
}
