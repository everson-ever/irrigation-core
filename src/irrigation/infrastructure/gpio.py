"""Real and mock GPIO adapters."""

from __future__ import annotations

from collections.abc import Sequence

from irrigation.domain.exceptions import HardwareError


class GPIORaspberryPi:
    """Controls valves and pump using physical board numbering."""

    def __init__(self, pump_pin: int) -> None:
        try:
            import RPi.GPIO as gpio
        except (ImportError, RuntimeError) as exc:
            raise HardwareError(
                "RPi.GPIO is unavailable; run on Raspberry Pi or set "
                "IRRIGATION_GPIO_DRIVER=mock for development"
            ) from exc
        self._gpio = gpio
        self._pump_pin = pump_pin
        self._configured = False

    def configure(self, valve_pins: Sequence[int]) -> None:
        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BOARD)
        for pin in {*map(int, valve_pins), self._pump_pin}:
            self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)
        self._configured = True

    def turn_on(self, pin: int) -> None:
        self._ensure_configured()
        self._gpio.output(int(pin), self._gpio.HIGH)
        self._gpio.output(self._pump_pin, self._gpio.HIGH)

    def turn_off(self, pin: int, keep_pump_on: bool = False) -> None:
        self._ensure_configured()
        self._gpio.output(int(pin), self._gpio.LOW)
        if not keep_pump_on:
            self._gpio.output(self._pump_pin, self._gpio.LOW)

    def close(self) -> None:
        if self._configured:
            self._gpio.cleanup()
            self._configured = False

    def _ensure_configured(self) -> None:
        if not self._configured:
            raise HardwareError("GPIO has not been configured yet")


class MockGPIO:
    """Hardware-free driver for development and tests."""

    def __init__(self, pump_pin: int) -> None:
        self.pump_pin = pump_pin
        self.states: dict[int, bool] = {}
        self.configured = False

    def configure(self, valve_pins: Sequence[int]) -> None:
        self.states = {int(pin): False for pin in valve_pins}
        self.states[self.pump_pin] = False
        self.configured = True

    def turn_on(self, pin: int) -> None:
        self.states[int(pin)] = True
        self.states[self.pump_pin] = True

    def turn_off(self, pin: int, keep_pump_on: bool = False) -> None:
        self.states[int(pin)] = False
        if not keep_pump_on:
            self.states[self.pump_pin] = False

    def close(self) -> None:
        self.states = {pin: False for pin in self.states}
        self.configured = False


def create_gpio(driver: str, pump_pin: int) -> GPIORaspberryPi | MockGPIO:
    if driver == "rpi":
        return GPIORaspberryPi(pump_pin)
    if driver == "mock":
        return MockGPIO(pump_pin)
    raise HardwareError(f"unknown GPIO driver: {driver}")
