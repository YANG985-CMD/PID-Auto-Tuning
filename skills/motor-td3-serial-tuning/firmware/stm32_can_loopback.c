/* Bounded STM32G431/G441 CAN controller test, executed from SRAM.
 * Internal loopback only: no GPIO initialization, external frames or PWM.
 * Register names/layout come from the user's STM32G4 CMSIS device headers.
 * G4 message RAM uses fixed 72-byte RX/TX element slots (RM0440).
 */
#include "stm32g4xx.h"
#include <stdint.h>

#define CASES 64U
#define MAGIC 0x43414E31U
#define WAIT_CYCLES 1600000U
#define XTD (1UL << 30)
#define RTR (1UL << 29)
#define FDF (1UL << 21)
#define BRS (1UL << 20)
#define RX_START (SRAMCAN_BASE + 176U)
#define TX_START (SRAMCAN_BASE + 632U)
#define ELEMENT_BYTES 72U

typedef struct {
    uint32_t magic, schema, state, error, expected, received;
    uint32_t standard, extended, dlc_mask, cccr, test, nbtp;
    uint32_t psr, ecr, ir, cycles, rcc_cfgr, rcc_ccipr;
    uint32_t tim1_cr1, tim1_ccer, tim1_bdtr, gpio_clock, f0s, txbrp;
    uint32_t tx0, tx1, rx0, rx1;
} Report;
static volatile Report *const report = (volatile Report *)0x20004400U;

static int wait_bits(volatile uint32_t *reg, uint32_t mask, uint32_t expected)
{
    uint32_t start = DWT->CYCCNT;
    /* The iteration bound remains effective if the cycle counter stalls. */
    for (uint32_t n = 0; n < 500000U; ++n) {
        if ((*reg & mask) == expected) return 1;
        if ((uint32_t)(DWT->CYCCNT - start) >= WAIT_CYCLES) break;
    }
    return 0;
}

static void snapshot(uint32_t start)
{
    report->cccr = FDCAN1->CCCR;
    report->test = FDCAN1->TEST;
    report->nbtp = FDCAN1->NBTP;
    report->psr = FDCAN1->PSR;
    report->ecr = FDCAN1->ECR;
    report->ir = FDCAN1->IR;
    report->cycles = DWT->CYCCNT - start;
    report->rcc_cfgr = RCC->CFGR;
    report->rcc_ccipr = RCC->CCIPR;
    report->tim1_cr1 = TIM1->CR1;
    report->tim1_ccer = TIM1->CCER;
    report->tim1_bdtr = TIM1->BDTR;
    report->gpio_clock = RCC->AHB2ENR;
    report->f0s = FDCAN1->RXF0S;
    report->txbrp = FDCAN1->TXBRP;
}

void can_diag_main(void)
{
    uint32_t start;
    report->magic = MAGIC;
    report->schema = 1;
    report->state = 1;
    report->expected = CASES;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    start = DWT->CYCCNT;
    if ((RCC->CFGR & (RCC_CFGR_SWS | RCC_CFGR_HPRE | RCC_CFGR_PPRE1)) != RCC_CFGR_SWS_HSI
        || (RCC->APB2ENR & RCC_APB2ENR_TIM1EN) || TIM1->CCER || (TIM1->BDTR & 0x8000U)
        || RCC->AHB2ENR) {
        report->error = 1;
        report->state = 3;
        return;
    }

    RCC->CCIPR = (RCC->CCIPR & ~RCC_CCIPR_FDCANSEL) | RCC_CCIPR_FDCANSEL_1;
    RCC->APB1ENR1 |= RCC_APB1ENR1_FDCANEN;
    (void)RCC->APB1ENR1;
    RCC->APB1RSTR1 |= RCC_APB1RSTR1_FDCANRST;
    RCC->APB1RSTR1 &= ~RCC_APB1RSTR1_FDCANRST;
    FDCAN1->CCCR &= ~FDCAN_CCCR_CSR;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_CSA, 0)) { report->error = 2; goto done; }
    FDCAN1->CCCR |= FDCAN_CCCR_INIT;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_INIT, FDCAN_CCCR_INIT)) {
        report->error = 3; goto done;
    }
    FDCAN1->CCCR |= FDCAN_CCCR_CCE;
    FDCAN_CONFIG->CKDIV = 0;
    /* Classic CAN, no automatic retransmit, internal loopback, 500 kbit/s:
       reset PCLK1 16 MHz / prescaler 2 / (1 + 10 + 5). */
    FDCAN1->CCCR = FDCAN_CCCR_INIT | FDCAN_CCCR_CCE | FDCAN_CCCR_DAR
                 | FDCAN_CCCR_TEST | FDCAN_CCCR_MON;
    FDCAN1->TEST = FDCAN_TEST_LBCK;
    FDCAN1->NBTP = (1U << FDCAN_NBTP_NBRP_Pos) | (9U << FDCAN_NBTP_NTSEG1_Pos)
                  | (4U << FDCAN_NBTP_NTSEG2_Pos);
    FDCAN1->RXGFC = FDCAN_RXGFC_RRFE | FDCAN_RXGFC_RRFS; /* Nonmatching data -> FIFO0. */
    FDCAN1->TXBC = 0; /* FIFO, fixed three slots. */
    FDCAN1->IE = 0;
    FDCAN1->ILE = 0;
    for (uint32_t offset = 0; offset < 848U; offset += 4U)
        *(volatile uint32_t *)(SRAMCAN_BASE + offset) = 0;
    if ((FDCAN1->CCCR & (FDCAN_CCCR_TEST | FDCAN_CCCR_MON)) !=
        (FDCAN_CCCR_TEST | FDCAN_CCCR_MON) || !(FDCAN1->TEST & FDCAN_TEST_LBCK)) {
        report->error = 4; goto done;
    }
    FDCAN1->CCCR &= ~FDCAN_CCCR_INIT;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_INIT, 0)) { report->error = 5; goto done; }

    for (uint32_t n = 0; n < CASES; ++n) {
        uint32_t extended = n >= CASES / 2U;
        uint32_t id = extended ? (0x001ABCDEU + n) | XTD : (0x321U + n) << 18;
        uint32_t length = n % 9U;
        uint32_t index = (FDCAN1->TXFQS & FDCAN_TXFQS_TFQPI) >> FDCAN_TXFQS_TFQPI_Pos;
        volatile uint32_t *tx;
        volatile uint32_t *rx;
        uint8_t expected[8];
        if (index >= 3 || !(FDCAN1->TXFQS & FDCAN_TXFQS_TFFL)) {
            report->error = 6; goto done;
        }
        tx = (volatile uint32_t *)(TX_START + index * ELEMENT_BYTES);
        tx[0] = id;
        tx[1] = length << 16; /* No FDF, BRS, RTR or event request. */
        tx[2] = tx[3] = 0;
        for (uint32_t j = 0; j < 8; ++j) {
            expected[j] = (uint8_t)(0xA5U ^ (n * 37U) ^ (j * 13U));
            tx[2U + j / 4U] |= (uint32_t)expected[j] << ((j % 4U) * 8U);
        }
        __DMB();
        FDCAN1->TXBAR = 1UL << index;
        if (!wait_bits(&FDCAN1->TXBRP, 1UL << index, 0)
            || !(FDCAN1->TXBTO & (1UL << index))) { report->error = 7; goto done; }
        if (!wait_bits(&FDCAN1->RXF0S, FDCAN_RXF0S_F0FL, 1U)) {
            report->error = 8; goto done;
        }
        uint32_t get = (FDCAN1->RXF0S & FDCAN_RXF0S_F0GI) >> FDCAN_RXF0S_F0GI_Pos;
        if (get >= 3) { report->error = 9; goto done; }
        rx = (volatile uint32_t *)(RX_START + get * ELEMENT_BYTES);
        report->tx0 = tx[0];
        report->tx1 = tx[1];
        report->rx0 = rx[0];
        report->rx1 = rx[1];
        /* Standard ID occupies only bits 28:18; lower bits are not the ID. */
        uint32_t id_mask = extended ? 0x1FFFFFFFU : 0x1FFC0000U;
        if ((rx[0] & (id_mask | XTD | RTR)) != id
            || ((rx[1] >> 16) & 0xFU) != length || (rx[1] & (FDF | BRS))) {
            report->error = 10; goto done;
        }
        for (uint32_t j = 0; j < length; ++j) {
            if ((uint8_t)(rx[2U + j / 4U] >> ((j % 4U) * 8U)) != expected[j]) {
                report->error = 11; goto done;
            }
        }
        FDCAN1->RXF0A = get;
        report->received++;
        if (extended) report->extended++; else report->standard++;
        report->dlc_mask |= 1UL << length;
    }
done:
    snapshot(start);
    /* Stop/reset the peripheral before returning to the BKPT entry wrapper. */
    RCC->APB1RSTR1 |= RCC_APB1RSTR1_FDCANRST;
    RCC->APB1RSTR1 &= ~RCC_APB1RSTR1_FDCANRST;
    RCC->APB1ENR1 &= ~RCC_APB1ENR1_FDCANEN;
    report->state = report->error ? 3U : 2U;
    __DSB();
}
