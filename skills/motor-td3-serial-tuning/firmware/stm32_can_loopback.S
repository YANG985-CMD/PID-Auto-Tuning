.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
    .word 0x20005000
    .word can_diag_entry
    .rept 126
    .word can_diag_trap
    .endr
.section .text.can_diag_entry, "ax", %progbits
.global can_diag_entry
.type can_diag_entry, %function
.thumb_func
can_diag_entry:
    cpsid i
    bl can_diag_main
    bkpt #0
1:  b 1b
.global can_diag_trap
.type can_diag_trap, %function
.thumb_func
can_diag_trap:
    bkpt #1
2:  b 2b
