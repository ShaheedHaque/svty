#!/usr/bin/env python3
# vim: set fileencoding=utf-8 :
#
# Visual management of terminal sessions.
#
# Copyright (c) 2015 S.R.Haque (srhaque@theiet.org)
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
"""Visual management of terminal sessions."""
from __future__ import print_function
from abc import ABCMeta, abstractmethod
import argparse
import curses
import curses.ascii
import datetime
import fcntl
import gettext
import inspect
import json
import logging
import logging.handlers
import os
import re
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time

import jumper

gettext.install(os.path.basename(__file__))
logger = logging.getLogger(__name__)

# Keep PyCharm happy.
_ = _


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """
    Using "Multiple inheritance" to have both defaults exposed as well as
    raw description for the epilog
    """
    pass


class CommandLineArgumentException(Exception):
    """Used to inform the user that s/he specified incorrect command line args"""
    pass


class AbstractTerminal(object):
    """
    Model a verb used to implement terminal sessions.
    """
    __metaclass__ = ABCMeta

    def __init__(self, program, remote):
        super(AbstractTerminal, self).__init__()
        self.program = program
        self.exec = remote

    @abstractmethod
    def check_output(self, args, safe_msgs=()):
        raise NotImplementedError()

    def call(self, args):
        cmd = [self.program] + args
        return self.exec.exec(cmd)

    @abstractmethod
    def list_sessions(self):
        """
        :return: List of AbstractSession.
        :raises: FileNotFoundError if the relevant program is not found.
        """
        raise NotImplementedError()

    @abstractmethod
    def new_session(self):
        """
        :raises: FileNotFoundError if the relevant program is not found.
        """
        raise NotImplementedError()


class AbstractSession(dict):
    __metaclass__ = ABCMeta

    def __init__(self, manager):
        super(AbstractSession, self).__init__()
        self.manager = manager

    @abstractmethod
    def id(self):
        """
        The key for the object.

        Returns: The string key.
        """
        raise NotImplementedError()

    @abstractmethod
    def check_output(self, args):
        """
        Run a command on the session.
        """
        raise NotImplementedError()

    @abstractmethod
    def list_windows(self):
        """
        :return: A list of the Windows in the session.
        """
        raise NotImplementedError()

    @abstractmethod
    def capture(self):
        """
        Screen capture.

        :return: A tuple (screen capture for current window, status line).
        """
        raise NotImplementedError()

    @abstractmethod
    def attach(self):
        """
        (Re-)attach to the session.
        """
        raise NotImplementedError()


class AbstractWindow(dict):
    """
    Model of a screen window, a subset of tmux's model.
    """
    __metaclass__ = ABCMeta

    def __init__(self, manager):
        super(AbstractWindow, self).__init__()
        self.manager = manager

    @abstractmethod
    def id(self):
        """
        The key for the object.

        Returns: The string key.
        """
        raise NotImplementedError()

    @abstractmethod
    def list_panes(self):
        """
        :return: A list of the Panes in the AbstractWindow.
        """
        raise NotImplementedError()


class Executor(threading.Thread):
    def __init__(self, args):
        super(Executor, self).__init__(name=self.__class__.__name__)
        self.args = args
        if self.args.uphps:
            #
            # Construct the SSH command.
            #
            self.token = "HI"
            command = ["while", "IFS=", "read", "-r", "l", ";", "do", "eval", "$l", ";", "echo", "-e", "\"\\n$?\\n" + self.token + "\"", ";", "done"]
            self.args.command = command
            self.jumper = jumper.run(self.args, follow_on=jumper.SSHMultiPass.FOLLOW_ON_PIO)
            self.stopping = False
            self.start()

    def exec(self, args, quote=True):
        if self.args.uphps:
            args = ["exec"] + args
            if quote:
                args = [shlex.quote(a) for a in args]
            cmd = " ".join(args) + "\n"
            logger.debug(_("Remote exec '{}'").format(cmd[:-1]))
            self.jumper.ping(cmd.encode())
            stdout = b""
            while len(stdout) < len(cmd) + 1:
                time.sleep(0.05)
                stdout += self.jumper.pong(1024)
            assert cmd == stdout[:len(cmd) + 1].decode().replace("\r\n", "\n")
            stdout = stdout[len(cmd) + 1:]
            os.write(sys.stdout.fileno(), stdout)
            #
            # TODO, what is the exit condition?
            #
            self.jumper.follow_on(jumper.SSHMultiPass.FOLLOW_ON_HCI)
            self.jumper.wait()
            self.close()
        else:
            logger.debug(_("Local exec '{}'").format(" ".join(args)))
            return subprocess.call(args)

    def check_output(self, args, ignore_errors=None):
        returncode = None
        if self.args.uphps:
            args = ["TZ=UTC", "LANG=en_GB.UTF-8"] + args
            cmd = [shlex.quote(a) for a in args]
            cmd = " ".join(cmd) + "\n"
            logger.debug(_("Remote check_output '{}'").format(cmd[:-1]))
            self.jumper.ping(cmd.encode())
            stdout = b""
            while True:
                time.sleep(0.05)
                stdout += self.jumper.pong(1024)
                if stdout[-len(self.token) - 2:].decode() == self.token + "\r\n":
                    stdout = stdout.decode().replace("\r\n", "\n")
                    stdout, returncode, t, t = stdout.rsplit("\n", 3)
                    #
                    # Jumping through intermediate hosts seems to introduce extraneous stuff.
                    #
                    stdout = stdout.lstrip()
                    #
                    # Remove the command string. TODO: for some reason, we sometimes get 1-2 copies of the command
                    # on consecutive reads!!!
                    #
                    while stdout.startswith(cmd):
                        stdout = stdout.split("\n", 1)[1]
                    returncode = int(returncode)
                    break
        else:
            os.environ["TZ"] = "UTC"
            os.environ["LANG"] = "en_GB.UTF-8"
            logger.debug(_("Local check_output '{}'").format(" ".join(args)))
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            stdout, stderr = process.communicate()
            returncode = process.returncode
        logger.debug(_("Returning {} '{}'").format(returncode, stdout))
        #
        # Ignore certain errors...
        #
        if returncode != 0:
            if not ignore_errors or not ignore_errors(stdout, returncode):
                raise subprocess.CalledProcessError(returncode, args, stdout)
        if stdout is None:
            stdout = ""
        return stdout

    def run(self):
        try:
            while not self.stopping:
                time.sleep(0.5)
        finally:
            logger.debug(_("Stopping {}").format(self))

    def close(self):
        logger.debug(_("Signalling stop for {}").format(self))
        self.stopping = True
        if self.args.uphps:
            self.jumper.close()


class ScreenTerminal(AbstractTerminal):
    """
    Support for screen(1).
    """
    def __init__(self, remote):
        super(ScreenTerminal, self).__init__("screen", remote)

    def check_output(self, args, safe_msgs=()):
        cmd = [self.program] + args
        stdout = self.exec.check_output(cmd, lambda stdout, returncode: returncode == 1 and stdout.startswith(safe_msgs))
        return stdout.strip().split("\n") if stdout else []

    def list_sessions(self):
        try:
            safe_msgs = ("There is a screen on", "There are screens on")
            lines = self.check_output(["-list"], safe_msgs)
        except subprocess.CalledProcessError as e:
            unsafe_msgs = ("No Sockets found in", "No screen session found")
            if e.returncode == 127 and e.stdout.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.stdout.strip()) from None
            elif e.returncode == 1 and e.stdout.startswith(unsafe_msgs):
                logger.debug(_("No session list: {}").format(e.stdout.strip()))
                lines = ["", ""]
            else:
                raise
        #
        # $ screen -list
        # There is a screen on:
        #         3883.pts-2.myhost (16/09/16 08:35:16)     (Attached)
        # 1 Socket in /var/run/screen/S-srhaque.
        # $ screen -list
        # There are screens on:
        #         4007.pts-4.session1 (16/09/16 08:35:58)     (Attached)
        #         3883.pts-2.host (16/09/16 08:35:15)     (Detached)
        # 2 Sockets in /var/run/screen/S-srhaque.
        #
        lines = lines[1:-1]
        lines = [l.strip().split("\t") for l in lines]
        sessions = []
        for line in lines:
            name, created, attached = line
            #
            # NOTE: the format is locale-dependent.
            #
            created = datetime.datetime.strptime(created[1:-1], "%d/%m/%y %H:%M:%S")
            attached = 1 if attached[1:-1].lower() == "attached" else 0
            sessions.append(ScreenSession(self, name, created, attached))
        logger.debug(_("Found sessions {}").format([s["session_name"] for s in sessions]))
        return sessions

    def new_session(self):
        try:
            return self.call([])
        except subprocess.CalledProcessError as e:
            if e.returncode == 127 and e.stdout.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.stdout.strip()) from None
            else:
                raise


class ScreenSession(AbstractSession):
    def __init__(self, manager, name, created, attached):
        super(ScreenSession, self).__init__(manager)
        self[self.ID] = name
        self["session_name"] = name
        self["session_created"] = created
        self["session_attached"] = attached

    ID = "session_id"

    def id(self):
        return self[self.ID]

    def check_output(self, args):
        return self.manager.check_output(["-X", "-S", self.id()] + args)

    def list_windows(self):
        #
        # $ screen -S 3345.hi -Q windows
        # 0$ bash  1$ bash  2-$ bash  3*$ bash
        #
        stdout = self.check_output(["-Q", "windows"])
        if not stdout:
            return []
        stdout = stdout[0].split()
        assert len(stdout) % 2 == 0
        windows = [(stdout[i], stdout[i + 1]) for i in range(0, len(stdout), 2)]
        windows = [(re.sub("[-$!@L&Z]", "", w[0]), w[1]) for w in windows]
        windows = [ScreenWindow(self.manager, w[0].replace("*", ""), w[1], 1 if w[0][-1] == "*" else 0) for w in windows]
        #
        # If the window list is of length 1, ensure that the one window is marked active, since screen does not bother.
        #
        if len(windows) == 1:
            windows[0]["window_active"] = 1
        return windows

    def capture(self):
        #
        # Get the state of the session.
        #
        windows = self.list_windows()
        w = [w for w in windows if w["window_active"]]
        assert len(w) <= 1, _("Expected upto 1 active window, not {}").format(len(w))
        if w:
            w = w[0]
        else:
            raise RuntimeError(_("Active window not found"))
        #
        # Get the content of the active window.
        #
        try:
            #
            # Get the window dimensions.
            #
            # $ screen -X -S 21522.hello50 -Q info
            # (37,45)/(143,45)+10000 +flow UTF-8 0(srhaque)
            #
            stdout = self.check_output(["-Q", "info"])
            stdout = stdout[0].split("(")[2]
            stdout = stdout.split(")")[0]
            stdout = stdout.split(",")
            self["window_width"] = int(stdout[0])
            self["window_height"] = int(stdout[1]) + 1
            #
            # Create a temporary file and make sure it is deleted to avoid the append mode (in case it is in effect).
            # Handle both local and remote cases.
            #
            name = self.manager.exec.check_output(["mktemp"]).strip()
            self.manager.exec.check_output(["rm", "-f", name])
            self.check_output(["hardcopy", name])
            stdout = self.manager.exec.check_output(["cat", name])
            self.manager.exec.check_output(["rm", name])
        except subprocess.CalledProcessError:
            raise RuntimeError(_("Window capture failed"))
        #
        # Read the output.
        #
        s_lines = stdout.split("\n")[:-1]
        assert len(s_lines) + 1 == self["window_height"]
        s_lines = [l.ljust(self["window_width"]) + "│" for l in s_lines]
        #
        # Add a line describing the windows in this session.
        #
        lhs = ["{}:{}{}".format(w["window_index"], w["window_name"], "*" if w["window_active"] else "-") for w in
               windows]
        lhs = "[{}] ".format(self.id()) + " ".join(lhs)
        rhs = ""
        return s_lines, lhs, rhs

    def attach(self):
        return self.manager.call(["-x", self.id()])


class ScreenWindow(AbstractWindow):
    """
    Model of a screen window, a subset of tmux's model.
    """
    def __init__(self, manager, window_index, window_name, window_active):
        super(ScreenWindow, self).__init__(manager)
        self[self.ID] = window_name
        self["window_index"] = window_index
        self["window_name"] = window_name
        self["window_active"] = window_active

    ID = "window_id"

    def id(self):
        return self[self.ID]

    def list_panes(self):
        return []


class TMuxTerminal(AbstractTerminal):
    """
    Support for tmux(1).
    """
    def __init__(self, remote):
        super(TMuxTerminal, self).__init__("tmux", remote)

    def check_output(self, args, safe_msgs=()):
        #
        # Ideally, we'd use "CONTROL MODE" which is supposed to delimit output nicely:
        #
        # tmux -C list-sessions
        # %begin 1473880629 1 0
        # rtmux: 1 windows (created Wed Sep 14 18:20:00 2016) [143x43] (attached)
        # rtmux0: 1 windows (created Wed Sep 14 18:22:52 2016) [143x43] (attached)
        # %end 1473880629 1 0
        #
        cmd = [self.program, "-C"] + args
        #
        # Jumper does not separate stderr...
        #
        stdout = self.exec.check_output(cmd, lambda stdout, returncode: returncode == 1 and stdout.startswith(safe_msgs))
        if not stdout:
            return []
        #
        # Sadly, on tmux V1.8 at least, CONTROL MODE does not work
        #
        if stdout.startswith("%begin"):
            return stdout.split("\n")[1:-2]
        else:
            return stdout.split("\n")[:-1]

    def lister(self, query, clazz, safe_msgs=(), parent=None, sep=None):
        formatter = ["\"{}\": \"#{{{}}}\"".format(p, p) for p in clazz.PROPERTIES]
        formatter = "{" + ",".join(formatter) + "}"
        if parent:
            lines = self.check_output([query, "-t", parent, "-F", formatter], safe_msgs)
        else:
            lines = self.check_output([query, "-F", formatter], safe_msgs)
        items = []
        for line in lines:
            item = clazz(self)
            line = json.loads(line)
            for k, v in line.items():
                try:
                    v = int(v)
                    if k in clazz.TIMESTAMPS:
                        v = datetime.datetime.fromtimestamp(v)
                except ValueError:
                    if k == clazz.ID:
                        if parent:
                            v = parent + sep + v
                item[k] = v
            items.append(item)
        return items

    def list_sessions(self):
        try:
            sessions = self.lister("list-sessions", TMuxSession)
        except subprocess.CalledProcessError as e:
            unsafe_msgs = ("error connecting to ", "no server running on", "failed to connect to server")
            if e.returncode == 127 and e.stdout.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.stdout.strip()) from None
            elif e.returncode == 1 and e.stdout.startswith(unsafe_msgs):
                logger.debug(_("No session list: {}").format(e.stdout.strip()))
                sessions = []
            else:
                raise
        logger.debug(_("Found sessions {}").format([s["session_name"] for s in sessions]))
        return sessions

    def new_session(self):
        try:
            return self.call(["new-session"])
        except subprocess.CalledProcessError as e:
            if e.returncode == 127 and e.stdout.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.stdout.strip()) from None
            else:
                raise


class TMuxSession(AbstractSession):
    PROPERTIES = [
        "session_attached",
        "session_activity",
        "session_created",
        "session_last_attached",
        "session_group",
        "session_grouped",
        "session_height",
        "session_id",
        "session_many_attached",
        "session_name",
        "session_width",
    ]

    TIMESTAMPS = [
        "session_activity",
        "session_created",
        "session_last_attached",
    ]

    def __init__(self, manager):
        super(TMuxSession, self).__init__(manager)

    ID = "session_id"

    def id(self):
        return self[self.ID]

    def check_output(self, args):
        return self.manager.check_output(args + ["-t", self.id])

    def list_windows(self):
        return self.manager.lister("list-windows", TMuxWindow, parent=self.id(), sep=":")

    def capture(self):
        #
        # Get the state of the session.
        #
        windows = self.list_windows()
        w = [w for w in windows if w["window_active"]]
        assert len(w) <= 1, _("Expected upto 1 active window, not {}").format(len(w))
        if w:
            w = w[0]
        else:
            raise RuntimeError(_("Active window not found"))
        #
        # Get the content of the active window.
        #
        try:
            s_lines = w.capture()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_("Window capture failed"), e)
        panes = w.list_panes()
        p = [p for p in panes if p["pane_active"]]
        assert len(p) <= 1, _("Expected upto 1 active pane, not {}").format(len(p))
        #
        # Add a line describing the windows in this session.
        #
        lhs = ["{}:{}{}".format(w["window_index"], w["window_name"], "*" if w["window_active"] else "-") for w in
               windows]
        lhs = "[{}] ".format(self["session_name"]) + " ".join(lhs)
        rhs = " \"{}\"                ".format(p[0]["pane_title"] if p else "")
        return s_lines, lhs, rhs

    def attach(self):
        return self.manager.call(["attach-session", "-t", self.id()])


class TMuxWindow(AbstractWindow):
    """
    Model of a tmux window
    """
    PROPERTIES = [
        "window_activity",
        "window_active",
        "window_bell_flag",
        "window_find_matches",
        "window_flags",
        "window_height",
        "window_id",
        "window_index",
        "window_last_flag",
        "window_layout",
        "window_linked",
        "window_name",
        "window_panes",
        "window_silence_flag",
        "window_visible_layout",
        "window_width",
        "window_zoomed_flag",
    ]

    TIMESTAMPS = [
        "window_activity",
    ]

    def __init__(self, manager):
        super(TMuxWindow, self).__init__(manager)

    ID = "window_id"

    def id(self):
        return self[self.ID]

    def check_output(self, args):
        """
        Run a command on the pane.
        """
        return self.manager.check_output(args + ["-t", self.id])

    def list_panes(self):
        panes = self.manager.lister("list-panes", TMuxPane, parent=self.id(), sep=".")
        #
        # Sadly, on tmux V1.8 at least, using pane_top and pane_left can be empty strings.
        #
        for p in panes:
            if p["pane_top"] == "":
                p["pane_top"] = 0
            if p["pane_left"] == "":
                p["pane_left"] = 0
        return panes

    def capture(self):
        w_width = self["window_width"]
        w_height = self["window_height"]
        w_lines = []
        for i in range(w_height):
            w_lines.append(" " * w_width)
        panes = self.list_panes()
        for p in panes:
            p_top = p["pane_top"]
            p_left = p["pane_left"]
            p_width = p["pane_width"]
            p_height = p["pane_height"]
            p_lines = p.capture()
            p_lines = [l.ljust(p_width) for l in p_lines]
            #
            # Add separators if the pane ends short of the window.
            #
            if p_top + p_height < w_height:
                p_lines.append("─" * p_width)
            if p_left + p_width < w_width:
                p_lines = [l + "│" for l in p_lines]
            for y, p_line in enumerate(p_lines):
                w_line = w_lines[p_top + y]
                w_line = w_line[:p_left] + p_line + w_line[p_left + p_width + 1:]
                w_lines[p_top + y] = w_line
        #
        # Merge separators at corners using ┤ ├ ┴ ┬ ┼.
        #
        for p in panes:
            p_top = p["pane_top"]
            p_left = p["pane_left"]
            p_width = p["pane_width"]
            p_height = p["pane_height"]
            if p_top > 0:
                #
                # There is a <hr> above us.
                #
                hr_y = p_top - 1
                if p_left > 0:
                    w_line = w_lines[hr_y]
                    vr_x = p_left - 1
                    if w_line[vr_x] == "─":
                        #
                        # There is a <hr> above us, and we need to fix the LHS.
                        #
                        if w_lines[hr_y - 1][vr_x] == "│":
                            if w_lines[hr_y - 1][vr_x + 1] == "─":
                                joiner = "┼"
                            else:
                                joiner = "├"
                        else:
                            joiner = "┬"
                        w_lines[hr_y] = w_line[:vr_x] + joiner + w_line[vr_x + 1:]
                if p_left + p_width < w_width:
                    w_line = w_lines[hr_y]
                    vr_x = p_left + p_width
                    if w_line[vr_x] == "─":
                        #
                        # There is a <hr> above us, and we need to fix the RHS.
                        #
                        if w_lines[hr_y - 1][vr_x] == "│":
                            if w_lines[hr_y - 1][vr_x + 1] == "─":
                                joiner = "┼"
                            else:
                                joiner = "┤"
                        else:
                            joiner = "┬"
                        w_lines[hr_y] = w_line[:vr_x] + joiner + w_line[vr_x + 1:]
            if p_top + p_height < w_height:
                #
                # There is a <hr> below us.
                #
                hr_y = p_top + p_height
                if p_left > 0:
                    w_line = w_lines[hr_y]
                    vr_x = p_left - 1
                    if w_line[vr_x] == "│":
                        #
                        # There is a <hr> below us, and we need to fix the LHS.
                        #
                        if w_lines[hr_y + 1][vr_x] == "│":
                            if w_lines[hr_y + 1][vr_x - 1] == "─":
                                joiner = "┼"
                            else:
                                joiner = "├"
                        else:
                            joiner = "┴"
                        w_lines[hr_y] = w_line[:vr_x] + joiner + w_line[vr_x + 1:]
                if p_left + p_width < w_width:
                    w_line = w_lines[hr_y]
                    vr_x = p_left + p_width
                    if w_line[vr_x] == "│":
                        #
                        # There is a <hr> below us, and we need to fix the RHS.
                        #
                        if w_lines[hr_y + 1][vr_x] == "│":
                            if w_lines[hr_y + 1][vr_x + 1] == "─":
                                joiner = "┼"
                            else:
                                joiner = "┤"
                        else:
                            joiner = "┴"
                        w_lines[hr_y] = w_line[:vr_x] + joiner + w_line[vr_x + 1:]
        return w_lines


class TMuxPane(dict):
    """
    Model of a tmux pane.
    """
    PROPERTIES = [
        "pane_active",
        "pane_bottom",
        "pane_current_command",
        "pane_current_path",
        "pane_dead",
        "pane_dead_status",
        "pane_height",
        "pane_id",
        "pane_in_mode",
        "pane_input_off",
        "pane_index",
        "pane_left",
        "pane_pid",
        "pane_right",
        "pane_start_command",
        "pane_synchronized",
        "pane_tabs",
        "pane_title",
        "pane_top",
        "pane_tty",
        "pane_width",
    ]

    TIMESTAMPS = [
    ]

    def __init__(self, manager):
        super(TMuxPane, self).__init__()
        self.manager = manager

    ID = "pane_id"

    def id(self):
        return self[self.ID]

    def check_output(self, args):
        """
        Run a command on the pane.
        """
        try:
            return self.manager.check_output(args + ["-t", self.id()])
        except subprocess.CalledProcessError as e:
            if e.stdout.startswith("can't find pane"):
                #
                # Sadly, on tmux V1.8 at least, using the fully-qualified id does not work
                #
                simple_id = self.id().split(".")[-1]
                logger.debug(_("Retrying with id {} instead of {}").format(simple_id, self.id()))
                return self.manager.check_output(args + ["-t", simple_id])
            else:
                raise

    def capture(self):
        """
        Screen capture.

        :return: List of lines representing the pane.
        """
        return self.check_output(["capture-pane", "-p"])


class NullTerminal(AbstractTerminal):
    """
    Support for just using the SSH connection.
    """
    def __init__(self, remote):
        super(NullTerminal, self).__init__("$SHELL", remote)

    def check_output(self, args, safe_msgs=()):
        cmd = [self.program] + args
        stdout = self.exec.check_output(cmd, lambda stdout, returncode: stdout.startswith(safe_msgs))
        return stdout.strip().split("\n") if stdout else []

    def list_sessions(self):
        return []

    def new_session(self):
        try:
            return self.exec.exec([self.program, "-i", "-l"], quote=False)
        except subprocess.CalledProcessError as e:
            if e.returncode == 127 and e.stdout.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.stdout.strip()) from None
            else:
                raise


class HomeScreenLogHandler(logging.Handler):
    def __init__(self):
        super(HomeScreenLogHandler, self).__init__()
        self.logs = []

    def emit(self, record):
        self.logs.append(record)
        self.logs = self.logs[-50:]


def show_sessions(stdscr, connections, log_handler):
    """
    Return None, "", or a session.
    """
    #
    # Clear the screen.
    #
    stdscr.clear()
    curses.curs_set(0)
    NORMAL = 1
    STATUS = 2
    curses.init_pair(NORMAL, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(STATUS, curses.COLOR_BLACK, curses.COLOR_GREEN)
    #
    # Start on the home session, page 0.
    #
    HOME_SESSION = 0
    current_session = HOME_SESSION
    sessions = []
    session = None
    page_number = 0
    while True:
        #
        # Re-query the screen size. Confusingly, this *causes* a curses.KEY_RESIZE!
        #
        sizes = struct.pack('HHHH', 0, 0, 0, 0)
        sizes = fcntl.ioctl(sys.stdin, termios.TIOCGWINSZ, sizes)
        sizes = struct.unpack('HHHH', sizes)
        resize_needed = curses.is_term_resized(sizes[0], sizes[1])
        if resize_needed:
            curses.resizeterm(sizes[0], sizes[1])
        page_lines = curses.LINES - 1
        page_cols = curses.COLS
        if current_session == HOME_SESSION:
            if page_number > 0:
                #
                # Debug mode: display log data.
                #
                lines = []
                for record in log_handler.logs:
                    lines.append(log_handler.format(record))
                pages = (len(lines) + page_lines - 1) // page_lines
                page_number = min(pages, page_number)
                lines = lines[(page_number - 1) * page_lines:]
                lines = [l.ljust(page_cols) for l in lines]
                status = _("Page {} of {}").format(page_number, pages)
            else:
                #
                # Re-query the number of sessions.
                #
                sessions = []
                not_found = 0
                for connection in connections:
                    try:
                        sessions.extend(connection.list_sessions())
                    except FileNotFoundError:
                        not_found += 1
                if not_found == len(connections):
                    raise FileNotFoundError("Terminal program not found")
                session = 0
                lines = []
                lines.append(_("{:8} {:19} {:8} {}").format(_("PROGRAM"), _("CREATED"), _("ATTACHED"), _("SESSION")))
                for s in sessions:
                    line = _("{:8} {:19} {:8} {}").format(s.manager.program,
                                                          s["session_created"].isoformat(),
                                                          _("Yes") if s["session_attached"] else _("No"),
                                                          s["session_name"])
                    lines.append(line)
                status = _("↵ to start new session, ←/→ then ↵ to attach to existing session, q to QUIT")
        else:
            #
            # Display a session.
            #
            session = sessions[current_session - 1]
            if page_number > 0:
                #
                # Debug mode: display tmux data.
                #
                windows = session.list_windows()
                for w in windows:
                    panes = w.list_panes()
                    w["window_panes"] = panes
                session["session_windows"] = windows

                def handler(x):
                    return x.isoformat() if isinstance(x, datetime.datetime) else x

                lines = json.dumps(session, indent=4, default=handler).split("\n")
                pages = (len(lines) + page_lines - 1) // page_lines
                page_number = min(pages, page_number)
                lines = lines[(page_number - 1) * page_lines:]
                status = _("Page {} of {}").format(page_number, pages)
            else:
                #
                # Show the reconstructed session content.
                #
                try:
                    lines, lhs, rhs = session.capture()
                except Exception as e:
                    lines = [str(e)]
                    lhs = ""
                    rhs = ""
                lines = lines[-page_lines:]
                if len(lhs) + len(rhs) > page_cols:
                    status = lhs[:page_cols - 3 - len(rhs)] + "..." + rhs
                else:
                    status = lhs.ljust(page_cols - len(rhs)) + rhs
        #
        # Write a screenful of normal content.
        #
        lines.extend([""] * (page_lines - len(lines)))
        for i, line in enumerate(lines):
            stdscr.addstr(i, 0, line.ljust(page_cols)[:page_cols], curses.color_pair(NORMAL))
        #
        # The status line is truncated by one char because trying to emit that last char
        # conflicts with way ncurses handles the cursor after the write.
        #
        stdscr.addstr(i + 1, 0, status.ljust(page_cols)[:page_cols - 1], curses.color_pair(STATUS))
        stdscr.refresh()
        #
        # Over to the user. Note that c can be outside the range that chr() understands.
        #
        c = stdscr.getch()
        if c in [ord("q"), ord("Q")]:
            session = None
            break
        elif c in [curses.ascii.CR, curses.ascii.LF, curses.KEY_ENTER]:
            if page_number == 0:
                break
        elif c == curses.KEY_LEFT:
            if page_number == 0:
                if current_session == HOME_SESSION:
                    current_session = len(sessions)
                else:
                    current_session -= 1
        elif c == curses.KEY_RIGHT:
            if page_number == 0:
                if current_session == len(sessions):
                    current_session = HOME_SESSION
                else:
                    current_session += 1
        elif c == curses.KEY_NPAGE:
            page_number += 1
        elif c == curses.KEY_PPAGE:
            if page_number:
                page_number -= 1
    if isinstance(session, AbstractSession):
        return session
    elif session == 0:
        return ""
    else:
        return None


def run(args, log_handler):
    #
    # Execute.
    #
    executor = Executor(args)
    try:
        tmux = TMuxTerminal(executor)
        screen = ScreenTerminal(executor)
        null = NullTerminal(executor)
        connections = [tmux, screen, null]
        session = curses.wrapper(show_sessions, connections, log_handler)
        if session is not None:
            if session == "":
                #
                # Create a new session using the preferred order of Terminal.
                #
                not_found = 0
                for connection in connections:
                    try:
                        return connection.new_session()
                    except FileNotFoundError:
                        not_found += 1
                if not_found == len(connections):
                    raise FileNotFoundError("Terminal program not found")
            else:
                return session.attach()
    finally:
        #
        # Gracefully stop subprocesses etc.
        #
        if executor.is_alive():
            executor.close()
        e_type, e, tbk = sys.exc_info()
        if e:
            #
            # Last gasp error. We have a lot vested in subprocesses, treat those errors as nicely as we can.
            #
            if e_type == subprocess.CalledProcessError:
                if isinstance(e.cmd, list):
                    e.cmd = [shlex.quote(a) for a in e.cmd]
                    e.cmd = " ".join(e.cmd)
                    if e.stdout is None:
                        e.stdout = ""
                    if e.stderr is None:
                        e.stderr = ""
                logger.error(_("{}, stdout '{}', stderr '{}'").format(e, e.stdout, e.stderr))
            else:
                logger.error(str(e))


def main(argv=None):
    """
Visual selection of tmux(1) (or screen(1)) sessions.

Examples:

    Jump through jumphost to reach videoserver. The jumphost password is not
    needed because passwordless login has been set up:

        copy-ssh-id jumphost
        jumper srhaque@jumphost+admin:secret@videoserver

    As before, jump through jumphost to reach videoserver. But this time, the
    user prefers to be prompted for the password on videoserver:

        jumper srhaque@jumphost+admin@videoserver

    Jump through both jumphost and videoserver to reach videoslave2:

        jumper srhaque@jumphost+admin@videoserver+admin:mycat@videoslave2

    Some GUI terminal emulators such as konsole can use commands like this to
    configure terminal sessions.
"""
    if argv is None:
        argv = sys.argv
    parser = argparse.ArgumentParser(epilog=inspect.getdoc(main),
                                     formatter_class=HelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help=_("Enable verbose output"))
    parser.add_argument("-d", "--debug", type=int, default=0,
                        help=_("Enable remote debug"))
    parser.add_argument("--proxy-options", default="-q -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null",
                        help=_("The proxy SSH options to use for the proxies and the outer SSH"))
    parser.add_argument("--outer-options", default="-tt",
                        help=_("The additional SSH options to use for the outer SSH"))
    parser.add_argument("-s", "--ssh-options", default="-X",
                        help=_("Any extra SSH options to use for the outer SSH"))
    parser.add_argument("uphps", nargs="?",
                        help=_("List of [User][:Password]@Host[:Port], separated by '+' (use '++' in passwords)"))
    try:
        #
        # Set the local title.
        #
        try:
            import setproctitle
            title = " ".join([os.path.basename(argv[0])] + argv[1:])
            setproctitle.setproctitle(title)
        except ImportError:
            pass
        #
        # Run...
        #
        args = parser.parse_args(argv[1:])
        if args.debug != 0:
            import pydevd
            pydevd.settrace('localhost', port=args.debug)  # , stdoutToServer = True, stderrToServer = True)
            os.environ['TERM'] = 'xterm'
        #
        # Curses log handler.
        #
        ch = HomeScreenLogHandler()
        ch.setLevel(logging.DEBUG)
        if args.verbose:
            logger.setLevel(logging.DEBUG)
            cf = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s')
        else:
            logger.setLevel(logging.INFO)
            cf = logging.Formatter('%(levelname)s: %(message)s')
        ch.setFormatter(cf)
        logger.addHandler(ch)
        return run(args, ch)
    except CommandLineArgumentException as e:
        logger.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
