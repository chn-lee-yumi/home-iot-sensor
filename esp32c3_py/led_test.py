import random
import time

import machine
from neopixel import NeoPixel

LED_LIGHTNESS = 40  # LED最大亮度 0~255


def set_led_color(r, g, b):
    led[0] = (int(r), int(g), int(b))
    led.write()


def dynamic_led():
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


led = NeoPixel(machine.Pin(8, machine.Pin.OUT), 1)
dynamic_led()
