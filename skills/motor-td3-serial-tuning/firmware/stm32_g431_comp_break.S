.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
    .word 0x20005000
    .word comp_break_entry
    .rept 126
    .word comp_break_trap
    .endr
.section .text.comp_break_entry, "ax", %progbits
.global comp_break_entry
.type comp_break_entry, %function
.thumb_func
comp_break_entry:
    cpsid i
    bl comp_break_main
    bkpt #0
1:  b 1b
.global comp_break_trap
.type comp_break_trap, %function
.thumb_func
comp_break_trap:
    cpsid i
    bkpt #1
2:  b 2b
