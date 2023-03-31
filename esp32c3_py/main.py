"""
esptool.py erase_flash
esptool.py --chip esp32c3 write_flash 0x0 esp32c3-20210902-v1.17.bin
esptool.py verify_flash --diff yes 0x0 esp32c3-20210902-v1.17.bin
screen /dev/tty.usbserial-14440 115200
ampy --port /dev/tty.usbserial-14440 put main.py
Ctrl + A , Ctrl + \ - Exit screen

import upip
upip.install("urequests")
"""
import _thread
import gc
import json
import os
import random
import socket
import time

import machine
import network
import ntptime
import urequests  # urequests调用后必须close，否则会报OSError:23
import webrepl
from neopixel import NeoPixel

# ========== 参数 ==========
DEBUG = False
ENABLE_UPLOAD_INFLUX = True
INFLUX_SERVER = "10.0.0.5:8086"
INFLUX_TOKEN = "NodRFPqAe9YxA8Owf0PaW5EyKhqcUcFFy7K7CYA8L85kjhm_gm_v4g3Vd4TXGxudhg6tcb3uwCW1wRANHJf_Og=="
ENABLE_UPLOAD_HOME_ASSISTANT = True
HOME_ASSISTANT_SERVER = "10.0.0.5:8123"
HOME_ASSISTANT_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI3OWI0YjdkOWU3OGU0YzVjYjkxMmUxODQzNmNmNTdjNiIsImlhdCI6MTY0MzUzMTIxMywiZXhwIjoxOTU4ODkxMjEzfQ.SO3yP-f7INx7tB2SpYFUIsOT3hWNo5zmqs9CkQjMyZY"
AP_SSID = "AirSensor"
AP_PASSWORD = ".1234567"
REPL_PASSWORD = ".12345"
LED_LIGHTNESS = 40  # LED最大亮度 0~255
CONFIG = {}
WIFI_SSID = ""
WIFI_PASSWORD = ""

# ========== 传感器数据 ==========
UART_DATA = b'<\x02\x01\xa5\x00\x01\x00\x0c\x00$\x00,\x16\x011\x08\x91'  # 串口数据
eCO2 = 0
eCH2O = 0
TVOC = 0  # TVOC传感器数据10min后稳定
PM2_5 = 0
PM10 = 0
Temperature = 0
Humidity = 0
# ========== 数据滑动平均 ==========
AVG_LIMIT = 30
eCO2_avg = []
eCH2O_avg = []
TVOC_avg = []
PM2_5_avg = []
PM10_avg = []
Temperature_avg = []
Humidity_avg = []

uptime = machine.RTC().datetime()  # (year, month, day, weekday, hours, minutes, seconds, subseconds)


def load_config():
    """读取配置"""
    global CONFIG, WIFI_SSID, WIFI_PASSWORD
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
        WIFI_SSID = CONFIG["WIFI_SSID"]
        WIFI_PASSWORD = CONFIG["WIFI_PASSWORD"]


def set_led_color(r, g, b):
    """设置LED颜色"""
    led[0] = (int(r), int(g), int(b))
    led.write()


def avg(array, round_num=0):
    return round(sum(array) / len(array), round_num)


def dynamic_led():
    """LED彩色渐变灯"""
    while True:
        target_color = (random.randint(0, LED_LIGHTNESS), random.randint(0, LED_LIGHTNESS), random.randint(0, LED_LIGHTNESS))
        start_color = led[0]
        # print(start_color, "->", target_color)
        # 平滑变化颜色
        current_color = list(start_color)
        for t in range(LED_LIGHTNESS + 1):
            for i in range(len(target_color)):
                current_color[i] = start_color[i] + (target_color[i] - start_color[i]) / LED_LIGHTNESS * t
            set_led_color(*current_color)
            time.sleep(2 / LED_LIGHTNESS)
        time.sleep(0.5)


def connect_wifi():
    """连接wifi"""
    global uptime
    # http://docs.micropython.org/en/latest/esp32/quickref.html#networking
    set_led_color(0, 0, 1)
    wlan = network.WLAN(network.STA_IF)  # create station interface
    wlan.active(True)  # activate the interface
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            pass
    print('network config:', wlan.ifconfig())
    ntptime.settime()
    uptime = machine.RTC().datetime()
    set_led_color(0, 1, 0)


def configure_ap():
    """设置ap"""
    # https://docs.micropython.org/en/latest/library/network.WLAN.html
    ap = network.WLAN(network.AP_IF)  # create access-point interface
    ap.config(essid=AP_SSID, authmode=network.AUTH_WPA_WPA2_PSK, password=AP_PASSWORD)
    ap.active(True)  # activate the interface


def read_uart():
    """不断读取串口数据"""
    global UART_DATA
    uart1 = machine.UART(1, baudrate=9600, tx=21, rx=20)
    while True:
        count = uart1.any()
        if count == 17:
            UART_DATA = uart1.read(17)
            update_air_info()
        elif count > 17:
            uart1.read(count)
        else:
            time.sleep(0.5)


def update_air_info():
    """更新空气质量信息"""
    global UART_DATA, eCO2, eCH2O, TVOC, PM2_5, PM10, Temperature, Humidity
    data = UART_DATA
    if len(data) != 17:
        return "data length error: %r" % data
    if data[0] != 0x3C and data[1] != 0x02:
        return "frame error"
    checksum = sum(data[:16]) & 0xff
    if data[16] != checksum:
        return "checksum error"
    if int(data[12]) > 100:  # 实测有时候会出现131度的情况，因此过滤
        return "temperature too large: %d" % data[12]
    eCO2 = (data[2] << 8) + data[3]
    eCH2O = (data[4] << 8) + data[5]
    TVOC = (data[6] << 8) + data[7]
    PM2_5 = (data[8] << 8) + data[9]
    PM10 = (data[10] << 8) + data[11]
    Temperature = float("%d.%d" % (data[12], data[13]))
    Humidity = float("%d.%d" % (data[14], data[15]))
    eCO2_avg.append(eCO2)
    eCH2O_avg.append(eCH2O)
    TVOC_avg.append(TVOC)
    PM2_5_avg.append(PM2_5)
    PM10_avg.append(PM10)
    Temperature_avg.append(Temperature)
    Humidity_avg.append(Humidity)
    if len(eCO2_avg) > AVG_LIMIT:
        eCO2_avg.pop(0)
        eCH2O_avg.pop(0)
        TVOC_avg.pop(0)
        PM2_5_avg.pop(0)
        PM10_avg.pop(0)
        Temperature_avg.pop(0)
        Humidity_avg.pop(0)


def get_air_info():
    """获取空气质量信息"""
    global UART_DATA, eCO2, eCH2O, TVOC, PM2_5, PM10, Temperature, Humidity
    info = {
        "eCO2": eCO2,
        "eCH2O": eCH2O,
        "TVOC": TVOC,
        "PM2.5": PM2_5,
        "PM10": PM10,
        "Temperature": Temperature,
        "Humidity": Humidity
    }
    return info


def get_sys_stat():
    """获取系统信息"""
    global uptime
    disk_stat = os.statvfs('/')
    total_disk = disk_stat[0] * disk_stat[2]
    free_disk = disk_stat[0] * disk_stat[3]
    used_disk = total_disk - free_disk
    stat = {
        "disk_used": used_disk / 1024,  # 单位KB
        "disk_total": total_disk / 1024,
        "os_version": "%s" % os.uname().version,
        "os_time": machine.RTC().datetime(),
        "up_time": uptime,
        "cpu_freq": machine.freq(),  # 单位Hz
        "mem_used": gc.mem_alloc(),  # 单位Byte。注意，py代码会占内存，大小和py文件大小差不多
        "mem_free": gc.mem_free(),
        "mem_total": gc.mem_free() + gc.mem_alloc()  # micropython.mem_info()也能看到
    }
    return stat


def upload_data():
    """定时上传数据"""
    global UART_DATA, eCO2, eCH2O, TVOC, PM2_5, PM10, Temperature, Humidity
    headers_influx = {"Authorization": "Token " + INFLUX_TOKEN}
    headers_ha = {
        "Authorization": "Bearer " + HOME_ASSISTANT_TOKEN,
        "Content-Type": "application/json"
    }
    time.sleep(5)
    next_time = time.time() // 60 * 60 + 60
    while True:
        delta_time = next_time - time.time()
        if delta_time > 0:
            time.sleep(delta_time)
        next_time += 60
        try:
            # for i in range(30):
            #     data = "airSensors,sensor_id=1 " \
            #            "eCO2={eCO2:d},eCH2O={eCH2O:d},TVOC={TVOC:d}," \
            #            "PM2_5={PM2_5:d},PM10={PM10:d},temperature={Temperature:.1f},humidity={Humidity:.1f}," \
            #            "MemoryFree={MemoryFree:d}".format(eCO2=eCO2, eCH2O=eCH2O, TVOC=TVOC,
            #                                               PM2_5=PM2_5, PM10=PM10, Temperature=Temperature, Humidity=Humidity,
            #                                               MemoryFree=gc.mem_free())
            #     res = urequests.post("http://%s/api/v2/write?org=yumi&bucket=air&precision=s" % INFLUX_SERVER, data=data, headers=headers_influx)
            #     res.close()
            #     time.sleep(2)
            # data = json.dumps({"attributes": {"friendly_name": "PM2.5", "unit_of_measurement": "µg/m³"}, "state": PM2_5}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_PM2_5" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "PM10", "unit_of_measurement": "µg/m³"}, "state": PM10}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_PM10" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "(等效)二氧化碳浓度", "unit_of_measurement": "ppm"}, "state": eCO2}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_eCO2" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "(等效)甲醛浓度", "unit_of_measurement": "µg/m³"}, "state": eCH2O}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_eCH2O" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "总挥发性有机物", "unit_of_measurement": "µg/m³"}, "state": TVOC}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_TVOC" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "温度", "unit_of_measurement": "°C"}, "state": Temperature}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_Temperature" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            # data = json.dumps({"attributes": {"friendly_name": "湿度", "unit_of_measurement": "%"}, "state": Humidity}).encode("uft8")
            # res = urequests.post("http://%s/api/states/sensor.air1_Humidity" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            # res.close()
            data = "airSensors,sensor_id=1 " \
                   "eCO2={eCO2:.0f},eCH2O={eCH2O:.0f},TVOC={TVOC:.0f}," \
                   "PM2_5={PM2_5:.0f},PM10={PM10:.0f},temperature={Temperature:.1f},humidity={Humidity:.1f}," \
                   "MemoryFree={MemoryFree:d}".format(eCO2=avg(eCO2_avg), eCH2O=avg(eCH2O_avg), TVOC=avg(TVOC_avg),
                                                      PM2_5=avg(PM2_5_avg), PM10=avg(PM10_avg),
                                                      Temperature=avg(Temperature_avg, 1), Humidity=avg(Humidity_avg, 1),
                                                      MemoryFree=gc.mem_free())
            res = urequests.post("http://%s/api/v2/write?org=yumi&bucket=air&precision=s" % INFLUX_SERVER, data=data, headers=headers_influx)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "PM2.5", "unit_of_measurement": "µg/m³"}, "state": avg(PM2_5_avg)}).encode("uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_PM2_5" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "PM10", "unit_of_measurement": "µg/m³"}, "state": avg(PM10_avg)}).encode("uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_PM10" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "(等效)二氧化碳浓度", "unit_of_measurement": "ppm"}, "state": avg(eCO2_avg)}).encode(
                "uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_eCO2" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "(等效)甲醛浓度", "unit_of_measurement": "µg/m³"}, "state": avg(eCH2O_avg)}).encode(
                "uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_eCH2O" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "总挥发性有机物", "unit_of_measurement": "µg/m³"}, "state": avg(TVOC_avg)}).encode(
                "uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_TVOC" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "温度", "unit_of_measurement": "°C"}, "state": avg(Temperature_avg, 1)}).encode("uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_Temperature" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
            data = json.dumps({"attributes": {"friendly_name": "湿度", "unit_of_measurement": "%"}, "state": avg(Humidity_avg, 1)}).encode("uft8")
            res = urequests.post("http://%s/api/states/sensor.air1_Humidity" % HOME_ASSISTANT_SERVER, data=data, headers=headers_ha)
            res.close()
        except Exception as e:
            print("Exception in upload_data:")
            print(e)


def http_server():
    """启动http服务器"""
    app.run(host="0.0.0.0", port=80)


def telnet_server():
    """实现一个telnet的REPL"""
    address = socket.getaddrinfo("0.0.0.0", 23)[0][-1]
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    sock.listen(1)
    while True:
        conn, address = sock.accept()
        print("new telnet connection from ", address)
        conn.setblocking(False)
        conn.read()  # 读取多余字符
        conn.setblocking(True)
        try:
            file = conn.makefile('rwb', 0)
            is_login = False
            while not is_login:
                file.write(b"Password: ")
                input_password = file.readline().rstrip(b"\r\n")
                if input_password == REPL_PASSWORD.encode("utf8"):
                    is_login = True
                    file.write(b"TelnetREPL connected\r\n>>> ")
            conn.setblocking(False)
            conn.setsockopt(socket.SOL_SOCKET, 20, os.dupterm_notify)
            os.dupterm(file)
        except Exception as e:
            print("Exception in telnet_server: ", e)
            os.dupterm(None)
            conn.close()


# 程序启动倒计时
for i in range(3, 0, -1):
    print("program will start at %d second(s)..." % i)
    time.sleep(1)
print("start")

# 初始化工作
gc.threshold(4096)  # 设置垃圾回收阈值，每分配多少Byte就触发一次 https://docs.micropython.org/en/latest/library/gc.html
led = NeoPixel(machine.Pin(8, machine.Pin.OUT), 1)
set_led_color(1, 0, 0)
load_config()  # 加载配置
update_air_info()  # 更新空气质量信息
configure_ap()  # 设置AP
print("sleep 2")
time.sleep(2)

# 启动线程
print("starting threads")
_thread.start_new_thread(connect_wifi, ())  # 连接Wi-Fi
webrepl.start(port=8266, password=REPL_PASSWORD)  # 启动webrepl
_thread.start_new_thread(telnet_server, ())  # 启动telnet终端
if not DEBUG:  # 用串口读取传感器数据就没法用串口调试
    _thread.start_new_thread(read_uart, ())  # 开一条线程来读串口数据
_thread.start_new_thread(upload_data, ())  # 开一条线程来上传

print("starting miniWebServer")

##########################################
########### miniWebServer ################
##########################################

from miniWebServer import WebServer, jsonify, redirect

app = WebServer(__name__)


@app.route("/")
def index(request):
    host = request.headers["Host"]
    return redirect("http://{host}/webrepl.html?#{host}:8266/".format(host=host))


@app.route("/api/status")
def api_status(request):
    status = {
        "name": "空气质量传感器",
        "serial_data": "%r" % UART_DATA
    }
    status.update(get_sys_stat())
    status.update(get_air_info())
    return jsonify(status)


@app.route("/api/config", method=["GET", "POST"])
def api_config(request):
    if request.method == "GET":
        return jsonify(CONFIG)
    else:
        CONFIG.update(request.json)
        with open("config.json", "w") as f:
            json.dump(CONFIG, f)
        return jsonify(CONFIG)


_thread.start_new_thread(http_server, ())  # 开一条线程来处理HTTP请求
##########################################
########## end miniWebServer #############
##########################################

print("start finished")
