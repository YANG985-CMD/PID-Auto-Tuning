.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
    .word 0x20005000
    .word can_echo_entry
    .rept 126
    .word can_echo_trap
    .endr
.section .text.can_echo_entry, "ax", %progbits
.global can_echo_entry
.type can_echo_entry, %function
.thumb_func
can_echo_entry:
    cpsid i
    bl can_echo_main
    bkpt #0
1:  b 1b
.global can_echo_trap
.type can_echo_trap, %function
.thumb_func
can_echo_trap:
    bkpt #1
2:  b 2b
