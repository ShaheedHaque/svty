#
# Copyright (c) 2016 S.R.Haque (srhaque@theiet.org)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""nosetest suite for svty's tmux support."""
import argparse
import os
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(__file__)
sys.path = [os.path.dirname(SCRIPT_DIR)] + sys.path
from abstract_terminal import AbstractTerminal
from svty import screen_terminal
from svty import tmux_terminal
from svty import svty


class Runner(threading.Thread):
    def __init__(self, terminal: AbstractTerminal):
        super(Runner, self).__init__()
        self.terminal = terminal

    def run(self):
        self.terminal.new_session()


def new_session(init):
    args = argparse.Namespace()
    args.uphps = ""
    executor = svty.Executor(args)
    terminal = init(executor)
    runner = Runner(terminal)
    runner.start()
    #
    # Give it a chance!
    #
    time.sleep(1)
    terminal.close()
    assert terminal


def test_001():
    """
    TEST: check tmux new_session.
    """
    new_session(tmux_terminal.TMuxTerminal)


def test_002():
    """
    TEST: check screen new_session.
    """
    new_session(screen_terminal.ScreenTerminal)
