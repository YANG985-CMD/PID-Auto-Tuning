/* CAN-only SRAM guest: 16 fixed diagnostic requests/replies, no motor API.
 * Board HSE frequency must match the confirmed example's 24 MHz source.
 * Only PA11/PA12 are configured. TIM1 clock and phase pin modes stay off.
 */
#include "stm32g4xx.h"
#include <stdint.h>
#define MAGIC 0x434E4531U
#define CASES 16U
#define RX_START (SRAMCAN_BASE + 176U)
#define TX_START (SRAMCAN_BASE + 632U)
#define SLOT 72U
#define REQUEST_ID 0x6E0U
#define RESPONSE_ID 0x6E1U
typedef struct {
    uint32_t magic, schema, state, error, expected, received, sent;
    uint32_t cccr, test, nbtp, psr, ecr, cycles, rcc_cr, rcc_cfgr;
    uint32_t tim1_cr1, tim1_ccer, tim1_bdtr, phase_modes, gpio_clocks, last0, last1;
} Report;
static volatile Report *const report = (volatile Report *)0x20004400U;
static int wait_bits(volatile uint32_t *reg, uint32_t mask, uint32_t expected)
{
    uint32_t start = DWT->CYCCNT;
    for (uint32_t n = 0; n < 500000U; ++n) {
        if ((*reg & mask) == expected) return 1;
        if ((uint32_t)(DWT->CYCCNT - start) >= 1600000U) break;
    }
    return 0;
}
static int motor_off(void)
{
    return !(RCC->APB2ENR & RCC_APB2ENR_TIM1EN) && !TIM1->CR1 && !TIM1->CCER
           && !TIM1->BDTR && (GPIOA->MODER & 0x003F0000U) == 0x003F0000U
           && RCC->AHB2ENR == RCC_AHB2ENR_GPIOAEN;
}
void can_echo_main(void)
{
    uint32_t start, original_mode, original_af;
    report->magic = MAGIC;
    report->schema = 1;
    report->expected = CASES;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    start = DWT->CYCCNT;
    if ((RCC->CFGR & (RCC_CFGR_SWS | RCC_CFGR_HPRE | RCC_CFGR_PPRE1)) != RCC_CFGR_SWS_HSI
        || RCC->AHB2ENR || (RCC->APB2ENR & RCC_APB2ENR_TIM1EN)
        || TIM1->CR1 || TIM1->CCER || TIM1->BDTR) {
        report->error = 1; report->state = 3; return;
    }
    RCC->CR |= RCC_CR_HSEON; /* 24 MHz, confirmed from the kit's CAN example. */
    if (!wait_bits(&RCC->CR, RCC_CR_HSERDY, RCC_CR_HSERDY)) {
        report->error = 2; report->state = 3; return;
    }
    RCC->CCIPR &= ~RCC_CCIPR_FDCANSEL; /* HSE kernel clock, core stays HSI16. */
    RCC->APB1ENR1 |= RCC_APB1ENR1_FDCANEN;
    (void)RCC->APB1ENR1;
    RCC->APB1RSTR1 |= RCC_APB1RSTR1_FDCANRST;
    RCC->APB1RSTR1 &= ~RCC_APB1RSTR1_FDCANRST;
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    (void)RCC->AHB2ENR;
    original_mode = GPIOA->MODER;
    original_af = GPIOA->AFR[1];
    GPIOA->AFR[1] = (original_af & ~0x000FF000U) | 0x00099000U;
    GPIOA->MODER = (original_mode & ~0x03C00000U) | 0x02800000U; /* PA11/12 AF only. */
    FDCAN1->CCCR &= ~FDCAN_CCCR_CSR;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_CSA, 0)) { report->error = 3; goto done; }
    FDCAN1->CCCR |= FDCAN_CCCR_INIT;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_INIT, FDCAN_CCCR_INIT)) {
        report->error = 4; goto done;
    }
    FDCAN1->CCCR = FDCAN_CCCR_INIT | FDCAN_CCCR_CCE | FDCAN_CCCR_DAR;
    FDCAN_CONFIG->CKDIV = 0;
    /* 24 MHz / 3 / (1+10+5) = 500 kbit/s, classic CAN, normal mode. */
    FDCAN1->NBTP = (2U << FDCAN_NBTP_NBRP_Pos) | (9U << FDCAN_NBTP_NTSEG1_Pos)
                  | (4U << FDCAN_NBTP_NTSEG2_Pos);
    FDCAN1->RXGFC = FDCAN_RXGFC_RRFS | FDCAN_RXGFC_RRFE;
    FDCAN1->TXBC = 0;
    FDCAN1->IE = FDCAN1->ILE = 0;
    for (uint32_t offset = 0; offset < 848U; offset += 4U)
        *(volatile uint32_t *)(SRAMCAN_BASE + offset) = 0;
    FDCAN1->CCCR &= ~FDCAN_CCCR_INIT;
    if (!wait_bits(&FDCAN1->CCCR, FDCAN_CCCR_INIT, 0)) { report->error = 5; goto done; }
    if (!motor_off() || (FDCAN1->CCCR & (FDCAN_CCCR_TEST | FDCAN_CCCR_MON))
        || (FDCAN1->TEST & FDCAN_TEST_LBCK)) { report->error = 6; goto done; }
    __DMB();
    report->state = 1; /* Host must read this readiness before sending any request. */
    while (report->received < CASES) {
        if (!motor_off()) { report->error = 7; goto done; }
        if ((uint32_t)(DWT->CYCCNT - start) > 128000000U) { report->error = 8; goto done; }
        if (!(FDCAN1->RXF0S & FDCAN_RXF0S_F0FL)) continue;
        uint32_t get = (FDCAN1->RXF0S & FDCAN_RXF0S_F0GI) >> FDCAN_RXF0S_F0GI_Pos;
        if (get >= 3) { report->error = 9; goto done; }
        volatile uint32_t *rx = (volatile uint32_t *)(RX_START + get * SLOT);
        uint32_t h0 = rx[0], h1 = rx[1], data0 = rx[2], data1 = rx[3];
        FDCAN1->RXF0A = get;
        if ((h0 & 0x7FFC0000U) != (REQUEST_ID << 18)) continue;
        uint32_t n = report->received;
        uint32_t expected = n | ((n ^ 0xFFU) << 8) | ((n ^ 0xA5U) << 16) | 0x5A000000U;
        if ((h1 & 0x003F0000U) != (8U << 16) || data0 != 0x314E4143U || data1 != expected) {
            report->error = 10; goto done;
        }
        report->last0 = data0;
        report->last1 = data1;
        report->received++;
        uint32_t put = (FDCAN1->TXFQS & FDCAN_TXFQS_TFQPI) >> FDCAN_TXFQS_TFQPI_Pos;
        if (put >= 3 || !(FDCAN1->TXFQS & FDCAN_TXFQS_TFFL)) { report->error = 11; goto done; }
        volatile uint32_t *tx = (volatile uint32_t *)(TX_START + put * SLOT);
        tx[0] = RESPONSE_ID << 18;
        tx[1] = 8U << 16;
        tx[2] = data0; tx[3] = data1;
        __DMB();
        FDCAN1->TXBAR = 1UL << put;
        if (!wait_bits(&FDCAN1->TXBRP, 1UL << put, 0)
            || !(FDCAN1->TXBTO & (1UL << put))) { report->error = 12; goto done; }
        report->sent++;
    }
done:
    report->cccr = FDCAN1->CCCR; report->test = FDCAN1->TEST; report->nbtp = FDCAN1->NBTP;
    report->psr = FDCAN1->PSR; report->ecr = FDCAN1->ECR;
    report->cycles = DWT->CYCCNT - start;
    report->rcc_cr = RCC->CR; report->rcc_cfgr = RCC->CFGR;
    report->tim1_cr1 = TIM1->CR1; report->tim1_ccer = TIM1->CCER; report->tim1_bdtr = TIM1->BDTR;
    report->phase_modes = GPIOA->MODER & 0x003F0000U; report->gpio_clocks = RCC->AHB2ENR;
    RCC->APB1RSTR1 |= RCC_APB1RSTR1_FDCANRST;
    RCC->APB1RSTR1 &= ~RCC_APB1RSTR1_FDCANRST;
    RCC->APB1ENR1 &= ~RCC_APB1ENR1_FDCANEN;
    GPIOA->MODER = original_mode; GPIOA->AFR[1] = original_af;
    RCC->AHB2ENR &= ~RCC_AHB2ENR_GPIOAEN;
    report->state = report->error ? 3U : 2U;
    __DSB();
}
