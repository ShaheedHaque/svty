# vim: set fileencoding=utf-8 :
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
"""A tmux(1) terminal."""
import datetime
import subprocess
import gettext
import logging
import os
import json

from .abstract_terminal import AbstractTerminal, AbstractSession, AbstractWindow


gettext.install(os.path.basename(__file__))
logger = logging.getLogger(__name__)

# Keep PyCharm happy.
_ = _


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
        stdout = self.exec.check_output(cmd,
                                        lambda stdout, returncode: returncode == 1 and stdout.startswith(safe_msgs))
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
            if e.returncode == 127 and e.output.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.output.strip()) from None
            elif e.returncode == 1 and e.output.startswith(unsafe_msgs):
                logger.debug(_("No session list: {}").format(e.output.strip()))
                sessions = []
            else:
                raise
        logger.info(_("Found sessions {}").format([s["session_name"] for s in sessions]))
        return sessions

    def new_session(self):
        try:
            return self.call(["new-session"])
        except subprocess.CalledProcessError as e:
            if e.returncode == 127 and e.output.rfind("command not found") != -1:
                #
                # Emulate the local FileNotFoundError.
                #
                raise FileNotFoundError(e.output.strip()) from None
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
        assert len(w) <= 1, _("Expected up to 1 active window, not {}").format(len(w))
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
        assert len(p) <= 1, _("Expected up to 1 active pane, not {}").format(len(p))
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
            if e.output.startswith("can't find pane"):
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
