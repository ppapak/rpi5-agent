import time
import logging
import smbus2

_REG_CONFIG                 = 0x00
_REG_SHUNTVOLTAGE           = 0x01
_REG_BUSVOLTAGE             = 0x02
_REG_POWER                  = 0x03
_REG_CURRENT                = 0x04
_REG_CALIBRATION            = 0x05

class BusVoltageRange:
    RANGE_16V               = 0x00
    RANGE_32V               = 0x01

class Gain:
    DIV_1_40MV              = 0x00
    DIV_2_80MV              = 0x01
    DIV_4_160MV             = 0x02
    DIV_8_320MV             = 0x03

class ADCResolution:
    ADCRES_9BIT_1S          = 0x00
    ADCRES_10BIT_1S         = 0x01
    ADCRES_11BIT_1S         = 0x02
    ADCRES_12BIT_1S         = 0x03
    ADCRES_12BIT_2S         = 0x09
    ADCRES_12BIT_4S         = 0x0A
    ADCRES_12BIT_8S         = 0x0B
    ADCRES_12BIT_16S        = 0x0C
    ADCRES_12BIT_32S        = 0x0D
    ADCRES_12BIT_64S        = 0x0E
    ADCRES_12BIT_128S       = 0x0F

class Mode:
    POWERDOWN               = 0x00
    SVOLT_TRIGGERED         = 0x01
    BVOLT_TRIGGERED         = 0x02
    SANDBVOLT_TRIGGERED     = 0x03
    ADCOFF                  = 0x04
    SVOLT_CONTINUOUS        = 0x05
    BVOLT_CONTINUOUS        = 0x06
    SANDBVOLT_CONTINUOUS    = 0x07

class INA219:
    def __init__(self, i2c_bus: int = 1, addr: int = 0x40):
        self.bus = smbus2.SMBus(i2c_bus)
        self.addr = addr
        self._cal_value = 0
        self._current_lsb = 0.0
        self._power_lsb = 0.0
        self.set_calibration_16V_5A()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        self.bus.close()

    def read(self, address: int) -> int:
        try:
            data = self.bus.read_i2c_block_data(self.addr, address, 2)
            return (data[0] << 8) | data[1]
        except Exception as e:
            logging.error(f"I2C Read Error: {e}")
            return 0

    def write(self, address: int, data: int) -> None:
        try:
            temp = [(data >> 8) & 0xFF, data & 0xFF]
            self.bus.write_i2c_block_data(self.addr, address, temp)
        except Exception as e:
            logging.error(f"I2C Write Error: {e}")

    def set_calibration_32V_2A(self) -> None:
        self._current_lsb = 0.1
        self._cal_value = 4096
        self._power_lsb = 0.002

        self.write(_REG_CALIBRATION, self._cal_value)

        self.bus_voltage_range = BusVoltageRange.RANGE_32V
        self.gain = Gain.DIV_8_320MV
        self.bus_adc_resolution = ADCResolution.ADCRES_12BIT_32S
        self.shunt_adc_resolution = ADCResolution.ADCRES_12BIT_32S
        self.mode = Mode.SANDBVOLT_CONTINUOUS
        self.config = (self.bus_voltage_range << 13 |
                       self.gain << 11 |
                       self.bus_adc_resolution << 7 |
                       self.shunt_adc_resolution << 3 |
                       self.mode)
        self.write(_REG_CONFIG, self.config)

    def set_calibration_16V_5A(self) -> None:
        self._current_lsb = 0.1524
        self._cal_value = 26868
        self._power_lsb = 0.003048

        self.write(_REG_CALIBRATION, self._cal_value)

        self.bus_voltage_range = BusVoltageRange.RANGE_16V
        self.gain = Gain.DIV_2_80MV
        self.bus_adc_resolution = ADCResolution.ADCRES_12BIT_32S
        self.shunt_adc_resolution = ADCResolution.ADCRES_12BIT_32S
        self.mode = Mode.SANDBVOLT_CONTINUOUS
        self.config = (self.bus_voltage_range << 13 |
                       self.gain << 11 |
                       self.bus_adc_resolution << 7 |
                       self.shunt_adc_resolution << 3 |
                       self.mode)
        self.write(_REG_CONFIG, self.config)

    def getShuntVoltage_mV(self) -> float:
        self.write(_REG_CALIBRATION, self._cal_value)
        value = self.read(_REG_SHUNTVOLTAGE)
        if value > 32767:
            value -= 65536
        return value * 0.01

    def getBusVoltage_V(self) -> float:
        self.write(_REG_CALIBRATION, self._cal_value)
        return (self.read(_REG_BUSVOLTAGE) >> 3) * 0.004

    def getCurrent_mA(self) -> float:
        value = self.read(_REG_CURRENT)
        if value > 32767:
            value -= 65536
        return value * self._current_lsb

    def getPower_W(self) -> float:
        self.write(_REG_CALIBRATION, self._cal_value)
        value = self.read(_REG_POWER)
        if value > 32767:
            value -= 65536
        return value * self._power_lsb

def get_telemetry() -> tuple:
    with INA219(addr=0x42) as ina219:
        bus_voltage = ina219.getBusVoltage_V()
        current = ina219.getCurrent_mA()
        power = ina219.getPower_W()
        raw_percent = (bus_voltage - 6.0) / 2.4 * 100.0
        percentage = max(0, min(100, raw_percent))
        return bus_voltage, current, power, percentage

if __name__ == '__main__':
    while True:
        bus_voltage, current, power, p = get_telemetry()
        # print(f"Load Voltage:  {bus_voltage:6.3f} V")
        # print(f"Current:       {current / 1000.0:9.6f} A")
        # print(f"Power:         {power:6.3f} W")
        print(f"Percentage: {int(p)}%")
        time.sleep(2)