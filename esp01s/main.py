"""
esptool.py erase_flash
esptool.py --chip esp32c3 write_flash 0x0 esp32c3-20210902-v1.17.bin
esptool.py verify_flash --diff yes 0x0 esp32c3-20210902-v1.17.bin
screen /dev/tty.usbserial-14440 115200
ampy --port /dev/tty.usbserial-14440 put main.py
Ctrl + A , Ctrl + \ - Exit screen

import upip
upip.install("urequests")
upip.install("uasyncio")
https://docs.micropython.org/en/latest/library/uasyncio.html?highlight=async#module-uasyncio
"""

from BMP280 import *  # 这个必须放最前面import，否则会爆内存，玄学
from DHT20 import DHT20

print("sensor module imported")

import gc
import json
import os
import socket

import machine
import network
from machine import Pin, I2C

# ========== 参数 ==========
DEBUG = False
ENABLE_UPLOAD_INFLUX = True
INFLUX_SERVER = "10.0.0.5:8086"
INFLUX_TOKEN = "NodRFPqAe9YxA8Owf0PaW5EyKhqcUcFFy7K7CYA8L85kjhm_gm_v4g3Vd4TXGxudhg6tcb3uwCW1wRANHJf_Og=="
ENABLE_UPLOAD_HOME_ASSISTANT = True
HOME_ASSISTANT_SERVER = "10.0.0.5:8123"
HOME_ASSISTANT_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI3OWI0YjdkOWU3OGU0YzVjYjkxMmUxODQzNmNmNTdjNiIsImlhdCI6MTY0MzUzMTIxMywiZXhwIjoxOTU4ODkxMjEzfQ.SO3yP-f7INx7tB2SpYFUIsOT3hWNo5zmqs9CkQjMyZY"
AP_SSID = "AirSensor2"
AP_PASSWORD = ".1234567"
REPL_PASSWORD = ".12345"
CONFIG = {}
WIFI_SSID = ""
WIFI_PASSWORD = ""

# ========== 传感器数据 ==========
Temperature = 0
Humidity = 0
AIR_INFO = {}
SYS_STAT = {}
i2c = I2C(scl=Pin(0), sda=Pin(2), freq=100000)
dht20 = DHT20(i2c)
bmp280 = BMP280(i2c, addr=0x77)  # https://www.bilibili.com/read/cv15350720/


def init_sensor():
    global bmp280
    bmp280.oversample(BMP280_OS_STANDARD)  # BMP280_OS_ULTRAHIGH BMP280_OS_STANDARD https://blog.csdn.net/m0_37964621/article/details/111407489
    bmp280.standby = BMP280_STANDBY_250
    bmp280.iir = BMP280_IIR_FILTER_2
    # bmp280.power_mode = BMP280_POWER_FORCED


def load_config():
    """读取配置"""
    global CONFIG, WIFI_SSID, WIFI_PASSWORD
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        WIFI_SSID = CONFIG["WIFI_SSID"]
        WIFI_PASSWORD = CONFIG["WIFI_PASSWORD"]


def connect_wifi():
    """连接wifi"""
    wlan = network.WLAN(network.STA_IF)  # create station interface
    wlan.active(True)  # activate the interface
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            await asyncio.sleep(2)
    print('network config:', wlan.ifconfig())


async def reconnect_wifi():
    """连接wifi"""
    wlan = network.WLAN(network.STA_IF)  # create station interface
    wlan.active(True)  # activate the interface
    while True:
        if not wlan.isconnected():
            print('connecting to network...')
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            while not wlan.isconnected():
                await asyncio.sleep(2)
            print('network config:', wlan.ifconfig())
        await asyncio.sleep(10)


def configure_ap():
    """设置ap"""
    # https://docs.micropython.org/en/latest/library/network.WLAN.html
    ap = network.WLAN(network.AP_IF)  # create access-point interface
    ap.config(essid=AP_SSID, authmode=network.AUTH_WPA_WPA2_PSK, password=AP_PASSWORD)
    ap.active(True)  # activate the interface


import webrepl

# 初始化工作
print("starting")
configure_ap()  # 设置AP
webrepl.start(port=8266, password=REPL_PASSWORD)  # 启动webrepl
connect_wifi()  # 连接Wi-Fi
init_sensor()  # 初始化传感器
print("start finished")


# async def async_http_post(url, headers=None, data=b""):
#     # TODO: bug...
#     if not headers:
#         headers = {}
#     if type(data) is str:
#         data = bytes(data, 'utf8')
#     _, _, host, path = url.split('/', 3)
#     if host.find(":") != -1:
#         host, port = host.split(":", 2)
#     else:
#         port = 80
#     # addr = socket.getaddrinfo(host, port)[0][-1]
#     # s = socket.socket()
#     # s.connect(addr)
#     rs, ws = await asyncio.open_connection(host, int(port))
#     # s.send(bytes('POST /%s HTTP/1.0\r\nHost: %s\r\n' % (path, host), 'utf8'))
#     ws.write(bytes('POST /%s HTTP/1.0\r\nHost: %s\r\n' % (path, host), 'utf8'))
#     headers["Content-Length"] = len(data)
#     for head in headers:
#         # s.send(bytes('%s: %s\r\n' % (head, headers[head]), 'utf8'))
#         ws.write(bytes('%s: %s\r\n' % (head, headers[head]), 'utf8'))
#     # s.send(b'\r\n')
#     ws.write(b'\r\n')
#     if data:
#         # s.send(data)
#         ws.write(data)
#     while True:
#         # data = s.recv(100)
#         data = await rs.read(100)
#         if data:
#             print(data, end='')
#         else:
#             break
#     # s.close()
#     ws.close()


def http_post(url, headers=None, data=b""):
    if not headers:
        headers = {}
    if type(data) is str:
        data = bytes(data, 'utf8')
    _, _, host, path = url.split('/', 3)
    if host.find(":") != -1:
        host, port = host.split(":", 2)
        port = int(port)
    else:
        port = 80
    addr = socket.getaddrinfo(host, port)[0][-1]
    s = socket.socket()
    s.connect(addr)
    s.send(bytes('POST /%s HTTP/1.0\r\nHost: %s\r\n' % (path, host), 'utf8'))
    headers["Content-Length"] = len(data)
    for head in headers:
        s.send(bytes('%s: %s\r\n' % (head, headers[head]), 'utf8'))
    s.send(b'\r\n')
    if data:
        s.send(data)
    while True:
        data = s.recv(512)
        if data:
            print(data)
        else:
            break
    s.close()


async def get_air_info():
    """获取空气质量信息"""
    global Temperature, Humidity, AIR_INFO
    while True:
        AIR_INFO = {
            "Temperature_DHT20": dht20.get_temperature(),
            "Temperature_BMP280": bmp280.temperature,
            "Temperature": round((dht20.get_temperature() + bmp280.temperature) / 2, 1),
            "Humidity": dht20.get_humidity(),
            "Pressure": bmp280.pressure
        }
        print(AIR_INFO)
        await asyncio.sleep(1)


async def get_sys_stat():
    """获取系统信息"""
    global SYS_STAT
    while True:
        disk_stat = os.statvfs('/')
        total_disk = disk_stat[0] * disk_stat[2]
        free_disk = disk_stat[0] * disk_stat[3]
        used_disk = total_disk - free_disk
        SYS_STAT = {
            "disk_used": used_disk / 1024,  # 单位KB
            "disk_total": total_disk / 1024,
            "os_version": "%s" % os.uname().version,
            "os_time": machine.RTC().datetime(),
            "cpu_freq": machine.freq(),  # 单位Hz
            "mem_used": gc.mem_alloc(),  # 单位Byte。注意，py代码会占内存，大小和py文件大小差不多
            "mem_free": gc.mem_free(),
            "mem_total": gc.mem_free() + gc.mem_alloc()  # micropython.mem_info()也能看到
        }
        print(SYS_STAT)
        await asyncio.sleep(60)


async def upload_data_influxdb():
    global AIR_INFO, SYS_STAT
    headers_influx = {"Authorization": "Token " + INFLUX_TOKEN}
    await asyncio.sleep(5)
    while True:
        data = "airSensors,sensor_id=2 " \
               "temperature={Temperature:.1f},humidity={Humidity:.1f}," \
               "temperature_dht20={Temperature_DHT20:.1f},temperature_bmp280={Temperature_BMP280:.1f}," \
               "pressure={Pressure:.1f}".format(**AIR_INFO).encode("uft8")
        try:
            http_post("http://%s/api/v2/write?org=yumi&bucket=air&precision=s" % INFLUX_SERVER, data=data, headers=headers_influx)
        except Exception as e:
            print("Exception in upload_data_influxdb:", e)
        await asyncio.sleep(2)


async def upload_data_ha():
    global AIR_INFO, SYS_STAT
    headers_ha = {
        "Authorization": "Bearer " + HOME_ASSISTANT_TOKEN,
        "Content-Type": "application/json"
    }
    await asyncio.sleep(5)
    while True:
        try:
            data = json.dumps({"attributes": {"friendly_name": "气压", "unit_of_measurement": "Pa"}, "state": AIR_INFO["Pressure"]}).encode("uft8")
            http_post("http://%s/api/states/sensor.air2_Pressure" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            data = json.dumps({"attributes": {"friendly_name": "温度", "unit_of_measurement": "°C"}, "state": AIR_INFO["Temperature"]}).encode("uft8")
            http_post("http://%s/api/states/sensor.air2_Temperature" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            data = json.dumps({"attributes": {"friendly_name": "湿度", "unit_of_measurement": "%"}, "state": AIR_INFO["Humidity"]}).encode("uft8")
            http_post("http://%s/api/states/sensor.air2_Humidity" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
        except Exception as e:
            print("Exception in upload_data_ha:", e)
        await asyncio.sleep(60)


load_config()

import uasyncio as asyncio

asyncio.create_task(reconnect_wifi())  # 连接Wi-Fi
asyncio.create_task(get_air_info())  # 获取传感器信息
asyncio.create_task(get_sys_stat())  # 获取系统信息
asyncio.create_task(upload_data_influxdb())  # 上传数据到 influxdb
asyncio.create_task(upload_data_ha())  # 上传数据到 home assistant
loop = asyncio.get_event_loop()
loop.run_forever()
