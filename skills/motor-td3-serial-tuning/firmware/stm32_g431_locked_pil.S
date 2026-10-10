.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
    .word 0x20005000
    .word locked_pil_entry
    .rept 13
    .word locked_pil_trap
    .endr
    .word locked_pil_systick
    .rept 112
    .word locked_pil_trap
    .endr
.section .text.locked_pil_entry, "ax", %progbits
.global locked_pil_entry
.type locked_pil_entry, %function
.thumb_func
locked_pil_entry:
    cpsid i
    bl locked_pil_main
    bkpt #0
1:  b 1b
.global locked_pil_trap
.type locked_pil_trap, %function
.thumb_func
locked_pil_trap:
    cpsid i
    bkpt #1
2:  b 2b
