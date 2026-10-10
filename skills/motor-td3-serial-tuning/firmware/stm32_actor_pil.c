/* Computation-only RAM guest for STM32G431/G441 Cortex-M4F PIL.
 * No HAL, GPIO, UART, timer, motor command, or Flash programming calls.
 * The host must disconnect motor power, reset-and-halt, then verify TIM1 off.
 * A simulated Actor is permitted here only to test arithmetic, never motion. */
#include <stdint.h>
#include <math.h>
#include "motor_actor.h"
#include "pil_vectors.h"

#define REG32(address) (*(volatile uint32_t *)(address))
#define MAILBOX_ADDRESS 0x20004400u
#define MAILBOX_MAGIC 0x50494c31u

typedef struct {
    uint32_t ok;
    uint32_t cycles;
    float action[2];
    float gains[2];
} pil_record;

typedef struct {
    uint32_t magic;
    uint32_t schema;
    uint32_t state;
    uint32_t vectors;
    uint32_t invalid_rejected_mask;
    uint32_t reserved[3];
    pil_record records[PIL_VECTORS];
} pil_mailbox;

void pil_main(void)
{
    volatile pil_mailbox *box = (volatile pil_mailbox *)MAILBOX_ADDRESS;
    float action[2], gains[2], invalid[10];
    uint32_t index, start, elapsed, bad = 0u;

    /* Enable CP10/CP11 and the core cycle counter; no motor peripherals. */
    REG32(0xe000ed88u) |= 0x00f00000u;
    __asm volatile("dsb\nisb" ::: "memory");
    REG32(0xe000edfcu) |= 1u << 24;
    REG32(0xe0001004u) = 0u;
    REG32(0xe0001000u) |= 1u;

    box->magic = MAILBOX_MAGIC;
    box->schema = 1u;
    box->state = 1u;
    box->vectors = PIL_VECTORS;
    box->invalid_rejected_mask = 0u;
    for (index = 0; index < PIL_VECTORS; ++index) {
        action[0] = action[1] = gains[0] = gains[1] = 0.0f;
        start = REG32(0xe0001004u);
        box->records[index].ok = (uint32_t)motor_actor_predict(
            pil_inputs[index], action, gains);
        elapsed = REG32(0xe0001004u) - start;
        box->records[index].cycles = elapsed;
        box->records[index].action[0] = action[0];
        box->records[index].action[1] = action[1];
        box->records[index].gains[0] = gains[0];
        box->records[index].gains[1] = gains[1];
    }

    for (index = 0; index < 10; ++index) invalid[index] = pil_inputs[0][index];
    invalid[0] = NAN;
    if (!motor_actor_predict(invalid, action, gains)) bad |= 1u;
    invalid[0] = INFINITY;
    if (!motor_actor_predict(invalid, action, gains)) bad |= 2u;
    invalid[0] = pil_inputs[0][0];
    invalid[7] = -1.0f;
    if (!motor_actor_predict(invalid, action, gains)) bad |= 4u;
    box->invalid_rejected_mask = bad;
    box->state = 2u;
    __asm volatile("dsb\nisb" ::: "memory");
}
