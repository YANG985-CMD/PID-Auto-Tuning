/* RAM vector table and entry point. Interrupts stay masked throughout PIL. */
.syntax unified
.cpu cortex-m4
.thumb
.eabi_attribute 24, 1
.eabi_attribute 25, 1
.section RESET, "a", %progbits
.balign 512
.global pil_vectors
pil_vectors:
    .word 0x20005000
    .word pil_entry
    .rept 126
    .word pil_trap
    .endr

.section .text.pil_entry, "ax", %progbits
.global pil_entry
.type pil_entry, %function
.thumb_func
pil_entry:
    cpsid i
    bl pil_main
    bkpt #0
1:  b 1b
.size pil_entry, .-pil_entry

.global pil_trap
.type pil_trap, %function
.thumb_func
pil_trap:
    bkpt #1
2:  b 2b
.size pil_trap, .-pil_trap
