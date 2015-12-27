#!/usr/bin/python
from __future__ import absolute_import, division, print_function, unicode_literals

import pi3d
import os
import datetime
import random
import threading
import time
import sys
import traceback
import math
from gl import monkeypatch

monkeypatch.patch()


class GuiState():
    def __init__(self, yScore=0, bScore=0, lastGoal=None):
        self.yScore = yScore
        self.bScore = bScore
        self.lastGoal = lastGoal


class Counter():
    textures = None

    def __init__(self, value, shader, **kwargs):
        if not Counter.textures:
            Counter.textures = [pi3d.Texture("numbers/%d.png" % i)
                                for i in range(0, 10)]
        self.value = value
        self.number = pi3d.ImageSprite(Counter.textures[value], shader, **kwargs)
        self.anim_start = None
        self.speed = 5
        self.maxAngle = 5
        self.time = 0.8

    def draw(self):
        now = time.time()
        s = self.number
        s.set_textures([Counter.textures[self.value % 10]])

        if self.anim_start and (now - self.anim_start) <= self.time:
            angle = self.animValue(now) * self.maxAngle
            s.rotateToZ(angle)
        else:
            s.rotateToZ(0)
            self.anim_start = None

        s.draw()

    def setValue(self, value):
        if self.value != value:
            self.value = value
            self.anim_start = time.time()

    def animValue(self, now):
        x = now - self.anim_start
        return math.sin(2 * math.pi * x * self.speed) * math.pow(100., -x * x)


class Gui():
    def __init__(self, scaling_factor, fps, bus, show_leds=False):
        self.state = GuiState()
        self.bus = bus
        self.bus.subscribe(self.process_event)
        self.show_leds = show_leds
        self.__init_display(scaling_factor, fps)
        if self.is_x11():
            monkeypatch.fixX11KeyEvents(self.DISPLAY)

        self.__setup_sprites()

    def __init_display(self, sf, fps):
        bgcolor = (0.0, 0.0, 0.0, 0.0)
        if sf == 0:
            #adapt to screen size
            self.DISPLAY = pi3d.Display.create(background=bgcolor)
            sf = 1920 / self.DISPLAY.width
        else:
            print("Forcing size")
            self.DISPLAY = pi3d.Display.create(x=0, y=0, w=1920 // sf, h=1080 // sf,
                                               background=bgcolor)

        self.DISPLAY.frames_per_second = fps
        print("Display %dx%d@%d" % (self.DISPLAY.width, self.DISPLAY.height, self.DISPLAY.frames_per_second))

        self.CAMERA = pi3d.Camera(is_3d=False, scale=1 / sf)

    def __setup_sprites(self):
        flat = pi3d.Shader("uv_flat")
        posx = 750
        posy = 450
        self.yellow = pi3d.ImageSprite("yellow.jpg", flat, x=posx - 120, y=posy, w=60, h=66, z=5.0)
        self.black = pi3d.ImageSprite("black.jpg", flat, x=posx + 120, y=posy, w=60, h=66, z=5.0)
        font = pi3d.Font("LiberationMono-Bold.ttf", (255, 255, 255, 255), font_size=40)
        self.goal_time = pi3d.String(font=font, string=self.__get_time_since_last_goal(), is_3d=False, x=posx, y=posy - 100, z=6.0)
        self.goal_time.set_shader(flat)

        self.yCounter = Counter(0, flat, w=60, h=88, x=posx - 40, y=posy, z=5)
        self.bCounter = Counter(0, flat, w=60, h=88, x=posx + 40, y=posy, z=5)

        self.ledShapes = {
            "YD": pi3d.shape.Disk.Disk(radius=20, sides=12, x=-100, y=-430, z=0, rx=90),
            "YI": pi3d.shape.Disk.Disk(radius=20, sides=12, x=-100, y=-370, z=0, rx=90),
            "OK": pi3d.shape.Disk.Disk(radius=50, sides=12, x=0, y=-400, z=0, rx=90),
            "BD": pi3d.shape.Disk.Disk(radius=20, sides=12, x=100, y=-430, z=0, rx=90),
            "BI": pi3d.shape.Disk.Disk(radius=20, sides=12, x=100, y=-370, z=0, rx=90),
        }
        red = (255, 0, 0, 0)
        green = (0, 255, 0, 0)
        self.blackColor = (0, 0, 0, 0)
        self.ledColors = {"YD": red, "YI": green, "OK": green, "BD": red, "BI": green}
        self.leds = []

    def process_event(self, ev):
        if ev.name == "leds_enabled":
            self.leds = ev.data
        if ev.name == "quit":
            self.stop()
        if ev.name == "score_changed":
            self.set_state(GuiState(ev.data['yellow'], ev.data['black'], ev.data['last_goal']))
            
    def run(self):
        try:
            print("Running")
            while self.DISPLAY.loop_running():
                self.yellow.draw()
                self.black.draw()
                self.yCounter.draw()
                self.bCounter.draw()
                self.goal_time.draw()
                self.goal_time.quick_change(self.__get_time_since_last_goal())
                if self.show_leds:
                    self.__draw_leds()

            print("Loop finished")

        except:
            traceback.print_exc()

    def __draw_leds(self):
        for name, s in self.ledShapes.items():
            color = self.blackColor
            if name in self.leds:
                color = self.ledColors[name]

            s.set_material(color)
            s.draw()

    def __get_time_since_last_goal(self):
        if self.state.lastGoal:
            diff = time.time() - self.state.lastGoal
            fract = diff - int(diff)
            timestr = ("%s.%d" % (time.strftime("%M:%S", time.gmtime(diff)), int(fract * 10))).replace("0", "O")
        else:
            timestr = "--:--.-"

        return "LG: %s" % timestr

    def set_state(self, state):
        self.state = self.__validate(state)
        self.yCounter.setValue(self.state.yScore)
        self.bCounter.setValue(self.state.bScore)

    def __validate(self, state):
        return GuiState(state.yScore, state.bScore, state.lastGoal)

    def cleanup(self):
        self.DISPLAY.destroy()

    def stop(self):
        self.DISPLAY.stop()

    def is_x11(self):
        return pi3d.PLATFORM != pi3d.PLATFORM_PI and pi3d.PLATFORM != pi3d.PLATFORM_ANDROID


class RandomScore(threading.Thread):
    def __init__(self, gui):
        super(RandomScore, self).__init__(daemon=True)
        self.gui = gui

    def run(self):
        state = GuiState()
        while True:
            if random.random() < 0.2:
                who = random.randint(0, 1)
                if who == 0:
                    state.yScore += 1
                else:
                    state.bScore += 1

                state.lastGoal = time.time()
                self.gui.set_state(state)
            time.sleep(1)


if __name__ == "__main__":
    #read scaling factor from argv if set, 2 means half the size, 0 means adapt automatically
    sf = 0
    frames = 0
    if len(sys.argv) > 1:
        sf = int(sys.argv[1])

    #optionally set the fps to limit CPU usage
    if len(sys.argv) > 2:
        frames = int(sys.argv[2])

    gui = Gui(sf, frames)

    RandomScore(gui).start()

    gui.run()
    gui.cleanup()
