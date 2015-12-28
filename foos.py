#!/usr/bin/python3

from gl.foos_gui import Gui, GuiState
import os
import sys
import time
import queue
import getopt
import atexit
import pickle
import hipbot
from collections import namedtuple
from subprocess import check_output, call
import threading
import traceback

from iohandler.io_serial import IOSerial
from iohandler.io_debug import IODebug
from iohandler.io_keyboard import IOKeyboard
from clock import Clock
from ledcontroller import LedController, pat_goal, pat_reset, pat_ok, pat_error, Pattern
from soundcontroller import SoundController
import config
import youtube_uploader

State = namedtuple('State', ['yellow_goals', 'black_goals', 'last_goal'])


class ScoreBoard:
    event_queue = None
    last_goal_clock = None
    status_file = '.status'

    def __init__(self, event_queue):
        self.last_goal_clock = Clock('last_goal_clock')
        self.scores = {'black': 0, 'yellow': 0}
        self.event_queue = event_queue
        self.sound = SoundController()
        if not self.__load_info():
            self.reset()

    def score(self, team):
        d = self.last_goal_clock.get_diff()
        if d and d <= 3:
            print("Ignoring goal command {} happening too soon".format(team))
            return

        self.last_goal_clock.reset()
        self.increment(team)
        leds.setMode(pat_goal)
        replay()
        # Ignore events any event while replaying
        q = self.event_queue
        while not q.empty():
            q.get_nowait()
            q.task_done()

    def increment(self, team):
        s = self.scores.get(team, 0)
        self.scores[team] = (s + 1) % 10
        self.pushState()

    def decrement(self, team):
        s = self.scores.get(team, 0)
        self.scores[team] = max(s - 1, 0)
        self.pushState()

    def __load_info(self):
        loaded = False
        try:
            if os.path.isfile(self.status_file):
                with open(self.status_file, 'rb') as f:
                    state = pickle.load(f)
                    self.scores['yellow'] = state.yellow_goals
                    self.scores['black'] = state.black_goals
                    self.last_goal_clock.set(state.last_goal)
                    self.pushState()
                    loaded = True
        except:
            print("State loading failed")
            traceback.print_exc()

        return loaded

    def save_info(self):
        state = State(self.scores['yellow'], self.scores['black'], self.last_goal())
        with open(self.status_file, 'wb') as f:
            pickle.dump(state, f)

    def reset(self):
        self.scores = {'black': 0, 'yellow': 0}
        self.last_goal_clock.reset()
        self.pushState()

    def last_goal(self):
        return self.last_goal_clock.get()

    def pushState(self):
        state = GuiState(self.scores['yellow'], self.scores['black'], self.last_goal())
        gui.set_state(state)
        bot.send_info(state)
        self.sound.send_info(state)


class Buttons:
    # Class to manage the state of the buttons and the needed logic
    event_table = {}

    def __init__(self, upload_delay=1):
        self.upload_delay = upload_delay

    def event(self, board, event):
        et = self.event_table
        print("New event:", event, et)

        now = time.time()
        if event.state == 'down':
            # Actions are executed on button release
            if event.action not in et:
                et[event.action] = now
                if event.action == 'ok':
                    schedule_upload_confirmation(self.upload_delay)

            return

        if event.action not in et:
            # No press action => ignore
            return

        delta = now - et[event.action]
        print("Press duration:", delta)

        if event.action != 'ok':
            color, what = event.action.split('_')

            if ('yellow_minus' in et and 'yellow_plus' in et) or ('black_minus' in et and 'black_plus' in et):
                # Double press for reset?
                board.reset()
                for key in ['yellow_minus', 'yellow_plus', 'black_minus', 'black_plus']:
                    if key in et:
                        del et[key]
                return

            if what == 'minus':
                action = board.decrement
            else:
                action = board.increment

            action(color)
        else:
            reset_upload_confirmation()
            if delta < self.upload_delay:
                replay(True)
            else:
                upload()

        del et[event.action]

ButtonEvent = namedtuple('ButtonEvent', ['action', 'state'])

button_events = {
    'YD_D': ButtonEvent('yellow_minus', 'down'),
    'YD_U': ButtonEvent('yellow_minus', 'up'),
    'YI_D': ButtonEvent('yellow_plus', 'down'),
    'YI_U': ButtonEvent('yellow_plus', 'up'),
    'BD_D': ButtonEvent('black_minus', 'down'),
    'BD_U': ButtonEvent('black_minus', 'up'),
    'BI_D': ButtonEvent('black_plus', 'down'),
    'BI_U': ButtonEvent('black_plus', 'up'),
    'OK_D': ButtonEvent('ok', 'down'),
    'OK_U': ButtonEvent('ok', 'up')
}


def replay(manual=False, regenerate=True):
    if config.replay_enabled:
        #TODO: where to move this?
        call(["./replay.sh", "manual" if manual else "auto", "true" if regenerate else "false"])


def schedule_upload_confirmation(delay):
    leds.setMode([Pattern(delay, []), Pattern(0.1, ["OK"])])


def reset_upload_confirmation():
    leds.setMode([])


def upload():
    if config.upload_enabled:
        call(["./upload-latest.sh"])
        leds.setMode(pat_ok)
        youtube_uploader.async_upload('/tmp/replay/replay_long.mp4', bot)
    else:
        leds.setMode(pat_error)

try:
    opts, args = getopt.getopt(sys.argv[1:], "s:f:")
except getopt.GetoptError:
    print('usage: python2 ir_controller [-sfl]')
    print('-s: scale')
    print('-f: framerate (default: 25)')
    sys.exit(2)

sf = 0
frames = 25
for opt, arg in opts:
    if opt == '-f':
        frames = int(arg)
    if opt == '-s':
        sf = int(arg)

print("Run GUI")
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/gl/")
gui = Gui(sf, frames, show_leds=config.onscreen_leds_enabled)
bot = hipbot.HipBot()

event_queue = queue.Queue()

board = ScoreBoard(event_queue)
# Register save status on exit
atexit.register(board.save_info)

buttons = Buttons(upload_delay=0.6)

serial = IOSerial(event_queue)
debug = IODebug(event_queue)

leds = LedController([serial, debug, gui])

if gui.is_x11():
    print("Running Keyboard")
    IOKeyboard(event_queue)


def processEvents():
    while True:
        e = event_queue.get(True)
        print("Received event", e)
        if e['type'] == 'quit':
            gui.stop()
        elif e['type'] == 'input_command':
            command = e['value']

            if command in button_events:
                buttons.event(board, button_events[command])

            if command == 'BG' or command == 'YG':
                command2team = {'BG': 'black', 'YG': 'yellow'}
                board.score(command2team[command])

        event_queue.task_done()

threading.Thread(target=processEvents, daemon=True).start()
gui.run()
gui.cleanup()
