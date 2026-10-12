"""Direct hardware phase inhibition, including peripheral clock prerequisites."""
from speedloop_motion_handshake import REGS, PHASE_MASK


def inhibit(target):
    # When running, cut MOE first. A gated register read cannot prove its state.
    if target.read32(0x40021060) & (1 << 11):  # RCC APB2ENR / TIM1EN
        target.write32(REGS['tim1_bdtr'], target.read32(REGS['tim1_bdtr']) & ~0x8000)
        target.write32(REGS['tim1_ccer'], target.read32(REGS['tim1_ccer']) & ~PHASE_MASK)
        target.flush()
    target.write32(0x4002104c, target.read32(0x4002104c) | 3)
    target.flush()
    if target.read32(0x4002104c) & 3 != 3:
        raise RuntimeError('GPIOA/B clocks could not be enabled')
    for base, pins, mask, mode in ((0x48000000, 0x700, 0x3f0000, 0x150000),
                                   (0x48000400, 0xe000, 0xfc000000, 0x54000000)):
        target.write32(base + 0x18, pins << 16)
        target.write32(base, (target.read32(base) & ~mask) | mode)
    target.flush()
    # Only after all gates are physically GPIO low may a gated TIM1 clock turn on.
    if (target.read32(REGS['gpioa_moder']) & 0x3f0000 != 0x150000 or
        target.read32(REGS['gpiob_moder']) & 0xfc000000 != 0x54000000 or
        target.read32(REGS['gpioa_odr']) & 0x700 or target.read32(REGS['gpiob_odr']) & 0xe000):
        raise RuntimeError('Six phase GPIOs did not read back low')
    target.write32(0x40021060, target.read32(0x40021060) | (1 << 11))
    target.flush()
    target.write32(REGS['tim1_bdtr'], target.read32(REGS['tim1_bdtr']) & ~0x8000)
    target.write32(REGS['tim1_ccer'], target.read32(REGS['tim1_ccer']) & ~PHASE_MASK)
    target.flush()
    values = {name: target.read32(addr) for name, addr in REGS.items()}
    if values['tim1_bdtr'] & 0x8000 or values['tim1_ccer'] & PHASE_MASK:
        raise RuntimeError('TIM1 output disable readback failed')
    return values
