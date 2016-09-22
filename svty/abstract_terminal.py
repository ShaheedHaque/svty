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
import threading
from abc import ABCMeta, abstractmethod


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

        :return: A tuple (screen capture for current window, status line). Each of these lines is padded to the width
                 of the window, and the screen capture contains the same number of lines as the window.
        """
        raise NotImplementedError()

    @abstractmethod
    def attach(self):
        """
        Create a new terminal session. NOTE: this function never returns! See :func:AbstractTerminal.close() for more
        information.

        (Re-)attach to the session.
        """
        raise NotImplementedError()


class AbstractExecutor(threading.Thread):
    def __init__(self):
        super(AbstractExecutor, self).__init__(name=self.__class__.__name__)

    @abstractmethod
    def exec(self, args, quote=True):
        raise NotImplementedError()

    @abstractmethod
    def close(self):
        raise NotImplementedError()


class AbstractTerminal(object):
    """
    Model a verb used to implement terminal sessions.
    """
    __metaclass__ = ABCMeta

    def __init__(self, program: str, remote: AbstractExecutor) -> None:
        super(AbstractTerminal, self).__init__()
        self.program = program
        self.exec = remote

    @abstractmethod
    def check_output(self, args: list, safe_msgs: tuple = ()) -> str:
        raise NotImplementedError()

    def call(self, args: list) -> int:
        """
        Run a command in the terminal's execution context.

        :param args:            The command
        :return:                The return status of the command.
        """
        cmd = [self.program] + args
        return self.exec.exec(cmd)

    @abstractmethod
    def list_sessions(self) -> AbstractSession:
        """
        :return: List of AbstractSession.
        :raises: FileNotFoundError if the relevant program is not found.
        """
        raise NotImplementedError()

    @abstractmethod
    def new_session(self) -> None:
        """
        Create a new terminal session. NOTE: this function never returns! See :func:close() for more information.

        :raises: FileNotFoundError if the relevant program is not found.
        """
        raise NotImplementedError()

    def close(self) -> None:
        """
        Some methods in this module never return. In order to make them testable, they will typically be invoked from
        a thread and then this method used to close the sessions they use. NOTE: calling this method is the last
        operation that can be performed on an instance of this class.
        """
        self.exec.close()
