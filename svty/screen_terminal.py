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
"""A screen(1) terminal."""
import datetime
import re
import subprocess
import gettext
import logging
import os

from abstract_terminal import AbstractTerminal, AbstractSession, AbstractWindow


gettext.install(os.path.basename(__file__))
logger = logging.getLogger(__name__)

# Keep PyCharm happy.
_ = _


class ScreenTerminal(AbstractTerminal):
    """
    Support for screen(1).
    """
    def __init__(self, remote):
        super(ScreenTerminal, self).__init__("screen", remote)

    def check_output(self, args, safe_msgs=()):
        cmd = [self.program] + args
        stdout = self.exec.check_output(cmd,
                                        lambda stdout, returncode: returncode == 1 and stdout.startswith(safe_msgs))
        return stdout.strip().split("\n") if stdout else []

    def list_sessions(self):
        try:
            safe_msgs = ("There is a screen on", "There are screens on")
            lines = self.check_output(["-list"], safe_msgs)
        except subprocess.CalledProcessError as e:
            unsafe_msgs = ("No Sockets found in", "No screen session found")
            if e.returncode == 127 and e.output.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.output.strip()) from None
            elif e.returncode == 1 and e.output.startswith(unsafe_msgs):
                logger.debug(_("No session list: {}").format(e.output.strip()))
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
        logger.info(_("Found sessions {}").format([s["session_name"] for s in sessions]))
        return sessions

    def new_session(self):
        try:
            return self.call([])
        except subprocess.CalledProcessError as e:
            if e.returncode == 127 and e.output.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.output.strip()) from None
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
        windows = [ScreenWindow(self.manager, w[0].replace("*", ""),
                                w[1],
                                1 if w[0][-1] == "*" else 0) for w in windows]
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
            w["window_width"] = int(stdout[0])
            w["window_height"] = int(stdout[1]) + 1
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
        assert len(s_lines) + 1 == w["window_height"]
        s_lines = [l.ljust(w["window_width"]) for l in s_lines]
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
