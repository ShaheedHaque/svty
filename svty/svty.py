#!/usr/bin/env python3
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
"""Visual management of terminal sessions."""
from __future__ import print_function

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
import setproctitle
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time

import jumper
from abstract_terminal import AbstractSession
from null_terminal import NullTerminal
from screen_terminal import ScreenTerminal
from tmux_terminal import TMuxTerminal

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


class Executor(threading.Thread):
    def __init__(self, args):
        super(Executor, self).__init__(name=self.__class__.__name__)
        self.args = args
        if self.args.uphps:
            #
            # Construct the SSH command. This is basically a loop that reads commands from stdin and eval's them. After
            # each command, the exit status and a token is printed to allow the results of the command execution to be
            # unambiguously captured.
            #
            self.token = "HI"
            command = ["while", "IFS=", "read", "-r", "l", ";", "do", "eval", "$l", ";", "echo", "-e", "\"\\n$?\\n" +
                       self.token + "\"", ";", "done"]
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
                lines = [_("{:8} {:19} {:8} {}").format(_("PROGRAM"), _("CREATED"), _("ATTACHED"), _("SESSION"))]
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

                lines = json.dumps(session, indent=4, sort_keys=True, default=handler).split("\n")
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
        # Write a screenful of normal content. Start by making sure everything is trimmed and padded as needed.
        #
        lines = lines[:page_lines]
        lines.extend([""] * (page_lines - len(lines)))
        lines = [l.ljust(page_cols)[:page_cols] for l in lines]
        i = 0
        for i, line in enumerate(lines):
            stdscr.addstr(i, 0, line, curses.color_pair(NORMAL))
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
    needed because password-less login has been set up:

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
        title = " ".join([os.path.basename(argv[0])] + argv[1:])
        setproctitle.setproctitle(title)
        #
        # Run...
        #
        args = parser.parse_args(argv[1:])
        if args.debug != 0:
            import pydevd
            pydevd.settrace('localhost', port=args.debug, suspend=False)
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
