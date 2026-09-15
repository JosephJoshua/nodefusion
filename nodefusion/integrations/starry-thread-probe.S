/*
 * Minimal RISC-V Linux-ABI probe for StarryOS's CLONE_THREAD path.
 *
 * Build without a C library:
 *   riscv64-linux-musl-gcc -nostdlib -static -s -Wl,--build-id=none \
 *     -o starry-thread-probe starry-thread-probe.S
 *
 * The child uses only register operands after clone, so changing its stack is
 * safe.  A successful clone is enough for the NodeFusion in-kernel producer
 * to emit NFTRACE_THREAD_CREATE before the syscall returns.
 */

    .section .bss
    .balign 16
child_stack:
    .space 4096
child_stack_end:

    .section .text
    .globl _start
    .type _start, @function
_start:
    /* CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND |
       CLONE_THREAD | CLONE_SYSVSEM */
    li      a0, 0x50f00
    la      a1, child_stack_end
    li      a2, 0
    li      a3, 0
    li      a4, 0
    li      a7, 220              /* __NR_clone */
    ecall
    beqz    a0, child

    /* exit_group(0); the semantic record is committed before clone returns. */
    li      a0, 0
    li      a7, 94               /* __NR_exit_group */
    ecall

child:
    li      a0, 0
    li      a7, 93               /* __NR_exit */
    ecall

    .size _start, .-_start
