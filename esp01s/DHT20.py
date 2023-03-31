import time


class DHT20:
    # https://github.com/TinkerGen/Pico-micropython/blob/master/dht20.py
    # https://gitee.com/liliang9693/mpy-dht20/blob/master/DFRobot_DHT20.py
    __addr = 0x38

    def __init__(self, i2c):
        self.i2c = i2c
        self.begin()

    def begin(self):
        time.sleep(0.5)
        self.i2c.writeto(self.__addr, bytes(0x71))
        data = self.i2c.readfrom(self.__addr, 1)
        # print(data)
        if (data[0] | 0x08) == 0:
            return False
        else:
            return True

    def get_temperature(self):
        self.__write_reg(0xac, [0x33, 0x00])
        time.sleep(0.1)
        data = self.__read_reg(0x71, 7)
        rawData = ((data[3] & 0xf) << 16) + (data[4] << 8) + data[5]
        # print(rawData)
        temperature = float(rawData) / 5242 - 50
        return temperature

    def get_humidity(self):
        self.__write_reg(0xac, [0x33, 0x00])
        time.sleep(0.1)
        data = self.__read_reg(0x71, 7)
        rawData = ((data[3] & 0xf0) >> 4) + (data[1] << 12) + (data[2] << 4)
        humidity = float(rawData) / 0x100000
        return humidity * 100

    def __write_reg(self, reg, data):
        time.sleep(0.01)
        self.i2c.writeto_mem(self.__addr, reg, bytes(data))

    def __read_reg(self, reg, len):
        time.sleep(0.01)
        rslt = self.i2c.readfrom_mem(self.__addr, reg, len)
        # print(rslt)
        return rslt
