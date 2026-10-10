.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
    .word 0x20005000
    .word current_zero_entry
    .rept 126
    .word current_zero_trap
    .endr
.section .text.current_zero_entry, "ax", %progbits
.global current_zero_entry
.type current_zero_entry, %function
.thumb_func
current_zero_entry:
    cpsid i
    bl current_zero_main
    bkpt #0
1:  b 1b
.global current_zero_trap
.type current_zero_trap, %function
.thumb_func
current_zero_trap:
    cpsid i
    bkpt #1
2:  b 2b
