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
"""Abstract models of Terminals, Sessions and Windows."""
from abc import ABCMeta, abstractmethod


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
