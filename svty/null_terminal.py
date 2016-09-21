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
"""A "null" terminal, i.e. the raw SSH session."""
import subprocess

from abstract_terminal import AbstractTerminal


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