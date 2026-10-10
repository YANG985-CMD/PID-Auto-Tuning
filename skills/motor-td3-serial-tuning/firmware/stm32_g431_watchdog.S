.syntax unified
.cpu cortex-m4
.thumb
.section .vectors,"a",%progbits
.global watchdog_vectors
watchdog_vectors:
.word 0x20005000
.word watchdog_entry
.rept 13
.word watchdog_fault
.endr
.word SysTick_Handler
.rept 102
.word watchdog_fault
.endr
.section .text.watchdog_entry,"ax",%progbits
.global watchdog_entry
.type watchdog_entry,%function
.thumb_func
watchdog_entry:
  cpsid i
  bl watchdog_main
  bkpt #0
1: b 1b
.size watchdog_entry,.-watchdog_entry
