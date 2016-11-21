#!/usr/bin/env python3
#
# Use SSH to connect to a host, possibly jumping through multiple intermediaries.
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
"""Use SSH to connect to a host, possibly jumping through multiple intermediaries."""
from __future__ import print_function
import argparse
import errno
import fcntl
import gettext
import inspect
import logging
import os
import pty
import re
import select
import setproctitle
import shlex
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty


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


class SSHMultiPass(threading.Thread):
    """
    Drive passwords into a nested set of SSH proxies. This is similar to the
    "sshpass" program except that it can handle multiple hosts which need
    passwords.
    """

    PROMPT = b"'s password: "

    """
    An invocation of call() can be a simple one where the login process is handled, and then the returned value is
    simply the SSH returncode (FOLLOW_ON_NONE), or the caller can follow on from the login with either programmed IO
    (FOLLOW_ON_PIO) or human-computer interaction (FOLLOW_ON_HCI).
    """
    FOLLOW_ON_NONE = "none"
    """
    An invocation of call() or follow_on() with FOLLOW_ON_PIO signals the use of programmed IO where calls to ping()
    and pong() are used to interact with the remote end of the SSH connection. End the programmed IO with close() or
    another follow_on(FOLLOW_ON_HCI).
    """
    FOLLOW_ON_PIO = "programmed_io"
    """
    An invocation of call() or follow_on() with FOLLOW_ON_HCI signals that the human user will interact directly with
    remote end of the SSH session (i.e. using stdin and stdout). End the human-computer interaction with wait()+close()
    or a follow_on(FOLLOW_ON_PIO).
    """
    FOLLOW_ON_HCI = "human_computer_interaction"

    def __init__(self, passwords, add_cr=False):
        """
        Grab passwords, and options.

        :param passwords:       Dictionary of passwords, keyed by "user@host".
                                Note: the host should take the form of an
                                address, not a name subject to a DNS lookup.
        :param add_cr:          We use raw mode TTYs. Convert LF into CR-LF?
        """
        super(SSHMultiPass, self).__init__(name=self.__class__.__name__)
        self.prompt_buffer = b""
        self.passwords = {k.encode(): v.encode() for k, v in passwords.items()}
        self.allpasswords = list(self.passwords.keys())
        self.add_cr = add_cr
        self.is_a_tty = None
        self.old_tty = None
        self.old_sigwinch = None
        self.stdin = None
        self.stdout = None
        self.pid = None
        self.master_fd = None
        self._follow_on = None
        self.stopping = False

    def output(self, argv, stdin=sys.stdin):
        """
        Execute the command, and return output. All passwords provided in the constructor will be used automatically
         and the user will be prompted where there is no password and SSH is unable to use password-less login.
         Modelled on subprocess.output().

        :param argv:            The ssh(1) or scp(1) command to run. This should
                                use -oProxyCommand's to jump across hosts. See the
                                get_xxx_with_proxies() staticmethods for pre-canned
                                implementations.
        :param stdin:           The source of input.
        :return:                String stdout.
        """
        output = ""
        self._follow_on = SSHMultiPass.FOLLOW_ON_NONE
        try:
            with tempfile.TemporaryFile(mode="rw+U") as f:
                self._spawn(argv, stdin, stdout=f)
                f.flush()
                f.seek(0)
                #
                # Omit lines asking for passwords...
                #
                for line in f:
                    if line[:-1].endswith(SSHMultiPass.PROMPT):
                        continue
                    output += line
            self.wait()
        finally:
            self.close()
        return output

    def call(self, argv, follow_on, stdin=sys.stdin):
        """
        Execute the command, output goes to sys.stdout. All passwords provided in the constructor will be used
         automatically and the user will be prompted where there is no password and SSH is unable to use
         password-less login. Modelled on subprocess.call().

        :param argv:            The ssh(1) or scp(1) command to run. This should use
                                -oProxyCommand's to jump across hosts. See the
                                get_xxx_with_proxies() staticmethods for pre-canned
                                implementations.
        :param stdin:           The source of input.
        :param follow_on:       Is this a simple invocation, or will the caller then follow on to reuse this session
                                for other stuff? See FOLLOW_ON_XXX for details.
        :return:                Returncode or, if there is follow on, self.
        """
        self._follow_on = follow_on
        try:
            self._spawn(argv, stdin, stdout=sys.stdout)
            if follow_on == SSHMultiPass.FOLLOW_ON_NONE:
                return self.wait()
            else:
                return self
        finally:
            if follow_on == SSHMultiPass.FOLLOW_ON_NONE:
                self.close()

    def _sigwinch(self, signum, frame):
        #
        # Set win sizes.
        #
        sizes = struct.pack('HHHH', 0, 0, 0, 0)
        sizes = fcntl.ioctl(self.stdin, termios.TIOCGWINSZ, sizes)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, sizes)

    def _spawn(self, argv, stdin, stdout):
        """
        Main loop wrapper handling the cases where stdin is not a file-like object.

        :param stdin:           A file-like object, string filename, or an array of strings.
        :param stdout:          A file-like object.
        """
        if isinstance(stdin, list):
            with tempfile.TemporaryFile(mode="rw+U") as f:
                for line in stdin:
                    f.write(line)
                    if line[-1] != "\n":
                        f.write("\n")
                f.flush()
                f.seek(0)
                self._spawn_with_files(argv, f, stdout)
        elif isinstance(stdin, str):
            with open(stdin, mode="rU") as f:
                self._spawn_with_files(argv, f, stdout)
        else:
            self._spawn_with_files(argv, stdin, stdout)

    def _spawn_with_files(self, argv, stdin, stdout):
        """
        Main loop. The caller should use the wait() method to tidyup.

        :param stdin:           A file-like object.
        :param stdout:          A file-like object.
        """
        self.stdin = stdin
        self.stdout = stdout
        self.pid, self.master_fd = pty.fork()
        if self.pid == pty.CHILD:
            os.execlp(argv[0], *argv)
            #
            # Well, we are the child, but make the code look sane.
            #
            return
        self.is_a_tty = os.isatty(self.stdin.fileno())
        if self.is_a_tty:
            #
            # Initialise and track the window size.
            #
            self._sigwinch(signal.SIGWINCH, 0)
            self.old_sigwinch = signal.signal(signal.SIGWINCH, self._sigwinch)
            self.old_tty = tty.tcgetattr(self.stdin)
            #
            # Pass all characters including ^C to the remote end.
            #
            tty.setraw(self.stdin)
        try:
            readable = False
            while self.passwords or self._follow_on == SSHMultiPass.FOLLOW_ON_NONE:
                try:
                    r, w, e = select.select([self.master_fd, self.stdin], [], [], 0.1)
                except OSError as e:
                    if e.errno != errno.EINTR:
                        raise e
                    continue
                if self.master_fd in r:
                    if not self.passwords:
                        readable = True
                    #
                    # Forward to user.
                    #
                    try:
                        data = os.read(self.master_fd, 1024)
                    except OSError as e:
                        if e.errno == errno.EIO:
                            logger.debug(_("Proxied child transport closed"))
                            break
                        else:
                            raise
                    self._write_parent(data)
                if self.stdin in r:
                    #
                    # Don't mix scripted input and passwords.
                    #
                    if not readable:
                        continue
                    #
                    # Forward to child.
                    #
                    data = os.read(self.stdin.fileno(), 1024)
                    if len(data) == 0:
                        logger.debug(_("Stdin closed"))
                        break
                    self._write_child(data)
        finally:
            #
            # In ping-pong mode, defer the tidyup else do it now.
            #
            if self._follow_on != SSHMultiPass.FOLLOW_ON_NONE:
                self.start()
            else:
                self.run()

    def run(self):
        try:
            while not self.stopping and self._follow_on != SSHMultiPass.FOLLOW_ON_NONE:
                while not self.stopping and self._follow_on == SSHMultiPass.FOLLOW_ON_PIO:
                    time.sleep(0.1)

                while not self.stopping and self._follow_on == SSHMultiPass.FOLLOW_ON_HCI:
                    try:
                        r, w, e = select.select([self.master_fd, self.stdin], [], [], 0.1)
                    except OSError as e:
                        if e.errno != errno.EINTR:
                            raise e
                        continue
                    if self.master_fd in r:
                        #
                        # Forward to user.
                        #
                        try:
                            data = os.read(self.master_fd, 1024)
                        except OSError as e:
                            if e.errno == errno.EIO:
                                logger.debug(_("Proxied child transport closed"))
                                break
                            else:
                                raise
                        self._write_parent(data)
                    if self.stdin in r:
                        #
                        # Forward to child.
                        #
                        data = os.read(self.stdin.fileno(), 1024)
                        if len(data) == 0:
                            logger.debug(_("Stdin closed"))
                            break
                        self._write_child(data)
        finally:
            logger.debug(_("Stopping {}").format(self))
            if self.is_a_tty:
                tty.tcsetattr(self.stdin, tty.TCSAFLUSH, self.old_tty)
                try:
                    signal.signal(signal.SIGWINCH, self.old_sigwinch)
                except ValueError:
                    #
                    # ValueError: signal only works in main thread. See self.close().
                    #
                    pass
            os.close(self.master_fd)

    def close(self):
        logger.debug(_("Signalling stop for {}").format(self))
        self.stopping = True
        if self.old_sigwinch:
            signal.signal(signal.SIGWINCH, self.old_sigwinch)

    def wait(self):
        #
        # What happened?
        #
        killed_pid, exit_status_indication = os.waitpid(self.pid, 0)
        assert killed_pid == self.pid
        kill_signal = exit_status_indication & 0xff
        rc = (exit_status_indication >> 8) & 0x7f
        core_dumped = (exit_status_indication >> 15) & 0x1
        logger.debug(_("Child exited rc {}, signal {}, core {}").format(rc, kill_signal, core_dumped))
        return rc

    def ping(self, data):
        """
        Write to remote end of SSH connection. See FOLLOW_ON_PIO for details.

        :param data:                Bytes to be written.
        """
        self._write_child(data)

    def pong(self, size):
        """
        Write to remote end of SSH connection. See FOLLOW_ON_PIO for details.

        :return:                    Upto size bytes read.
        """
        return os.read(self.master_fd, size)

    def follow_on(self, value):
        """
        Set the style of interaction with the remote end of the SSH connection.

        :param value:               Either FOLLOW_ON_PIO, or FOLLOW_ON_HCI.
        """
        follow_ons = [SSHMultiPass.FOLLOW_ON_PIO, SSHMultiPass.FOLLOW_ON_HCI]
        assert value in follow_ons, _("{} must be one of {}").format(value, follow_ons)
        logger.debug(_("Setting follow_on to {}").format(value))
        self._follow_on = value
        #
        # TODO: Return the last useful status?
        #
        status = None
        return status

    def _write_child(self, data):
        """
        Write to the child process.
        """
        n = 0
        while n < len(data):
            n += os.write(self.master_fd, data[n:])

    def _write_parent(self, data):
        """
        Write to the parent process.
        """
        if self.add_cr:
            data = data.replace("\n", "\r\n")
        n = 0
        while n < len(data):
            n += os.write(self.stdout.fileno(), data[n:])
        #
        # Respond to any inbound password prompts. We use a history buffer
        # during initial processing to ensure we match across read buffer
        # boundaries. But once we have no more passwords, we can bypass all
        # this; this avoid growing the buffer indefinitely and also speeds
        # things up.
        #
        if self.passwords:
            self.prompt_buffer += data
            while True:
                prompt = SSHMultiPass.PROMPT
                iprompt = self.prompt_buffer.find(prompt)
                if iprompt == -1:
                    break
                iuser_host = self.prompt_buffer.rfind(b"\n", 0, iprompt)
                user_host = self.prompt_buffer[iuser_host + 1:iprompt]
                #
                # Send this password.
                #
                logging.debug(_("Password login to {}").format(user_host))
                try:
                    password = self.passwords.pop(user_host)
                except KeyError:
                    raise RuntimeError(_("No password for {} ({})").format(user_host, self.allpasswords))
                self._write_child(password + b"\n")
                #
                # Trim the buffer and go around in case we have any more
                # passwords in this buffer.
                #
                self.prompt_buffer = self.prompt_buffer[iprompt + len(prompt):]

    @staticmethod
    def get_proxies(uphps, options):
        """
        Get the proxies.
        """
        proxy = ""
        for i in range(len(uphps) - 1):
            via_username, via_password, via_host, via_port = uphps[i]
            to_username, to_password, to_host, to_port = uphps[i + 1]
            if proxy:
                proxy = proxy.replace('\\', '\\\\')
                proxy = proxy.replace('"', '\\"')
            #
            # We cannot use the -W %h:%p form for multiple hops...
            # The new -J option does not support passing options to these proxying steps.
            #
            proxy = "-oProxyCommand=\"ssh {} {} -W {}:{} -p {} {}@{}\"".format(options, proxy, to_host, to_port,
                                                                               via_port, via_username, via_host)
        #
        # Create password list.
        #
        passwords = {uphp[0] + "@" + uphp[2]: uphp[1] for uphp in uphps if uphp[1]}
        return proxy, passwords

    @staticmethod
    def get_ssh_with_proxies(uphps, options, extra_options):
        """
        Create an SSH session to an endpoint via any needed jump hosts. The
        result can be used in instances of this class.
        """
        proxy, passwords = SSHMultiPass.get_proxies(uphps, options)
        #
        # Now for the final hop.
        #
        to_username, to_password, to_host, to_port = uphps[-1]
        wrapper = "ssh {} {} {} -p {} {}@{}".format(options, extra_options, proxy, to_port, to_username, to_host)
        return wrapper, passwords

    @staticmethod
    def get_scp_with_proxies(uphps, options):
        """
        Create an SCP session to an endpoint via any needed jump hosts. The
        result can be used in instances of this class.
        """
        proxy, passwords = SSHMultiPass.get_proxies(uphps, options)
        #
        # Now for the final hop.
        #
        to_username, to_password, to_host, to_port = uphps[-1]
        wrapper = "scp {} {} -P {}".format(options, proxy, to_port)
        remote = "{}@{}:".format(to_username, to_host)
        return wrapper, remote, passwords

    @staticmethod
    def get_sftp_with_proxies(uphps, options):
        """
        Create an SFTP session to an endpoint via any needed jump hosts. The
        result can be used in instances of this class.
        """
        proxy, passwords = SSHMultiPass.get_proxies(uphps, options)
        #
        # Now for the final hop.
        #
        to_username, to_password, to_host, to_port = uphps[-1]
        wrapper = "sftp {} {} -P {}".format(options, proxy, to_port)
        remote = "{}@{}:".format(to_username, to_host)
        return wrapper, remote, passwords


def parse_uphps(encoded_uphps: str) -> list:
    """
    Decode a list of User[:Password]@Host[:Port] entries, separated by "+".

    :return: A list of (user, password, host, port).
    """
    #
    # Split/canonicalise User[:Password]@Host[:Port].
    #
    uphp_splitter = re.compile(r"\+(?!\+)")
    uphps = []
    try:
        for uphp in uphp_splitter.split(encoded_uphps):
            logger.debug(_("Parsing {}").format(uphp))
            try:
                up, hp = uphp.rsplit("@", 1)
            except ValueError:
                #
                # Expected exactly one '@'.
                #
                up = os.environ["USER"]
                hp = uphp
            #
            # Default password is "".
            #
            up = up.split(":", 1)
            if len(up) > 1:
                user = up[0]
                #
                # Unescape passwords.
                #
                password = "p:" + up[1].replace("++", "+")
            elif up[0].find("=") > -1:
                up = up[0].split("=", 1)
                user = up[0]
                password = "k:" + up[1]
            else:
                user = up[0]
                password = "p:"
            #
            # Default port is 22.
            #
            hp = hp.split(":", 1) + ["22"]
            #
            # Convert any hostnames to canonical form, i.e. an address to
            # make it possible to lookup passwords without ambiguity.
            #
            try:
                host = socket.gethostbyname(hp[0])
            except:
                raise ValueError(_("Cannot find host address in '{}'").format(uphp)) from None
            try:
                port = int(hp[1])
            except ValueError:
                raise ValueError(_("Expected numeric port in '{}'").format(uphp)) from None
            uphps.append((user, password[2:], host, port))
    except ValueError as e:
        raise ValueError(_("'{}' is not a valid list of uphps ({})").format(encoded_uphps, e)) from None
    return uphps


def run(args, follow_on=SSHMultiPass.FOLLOW_ON_NONE):
    uphps = parse_uphps(args.uphps)
    #
    # Construct the SSH command.
    #
    if args.ssh_options:
        args.outer_options += " " + args.ssh_options
    wrapper, passwords = SSHMultiPass.get_ssh_with_proxies(uphps, args.proxy_options, args.outer_options)
    #
    # Execute.
    #
    logger.debug(_("Connect {} {}").format("->".join([uphp[0] + "@" + uphp[2] for uphp in uphps]),
                                           " ".join(args.command)))
    command = shlex.split(wrapper) + args.command
    proxied_ssh = SSHMultiPass(passwords)
    try:
        return proxied_ssh.call(command, follow_on=follow_on)
    finally:
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
Use SSH to connect to a destination host after jumping through multiple
intermediate hosts as needed. The outer SSH session does the jumping using
a series of proxy SSH commands.

The --persistence option used either screen(1) ot tmux(1) to enable persistence
for the outer session. When using screen(1), users may wish to adjust the
options in the destination host's $HOME/.screenrc file as follows:

    # On xterm, use the scrollbars by disabling ("@") the smcup ("ti") and
    # rmcup ("te") alternate screen sequences.
    termcapinfo xterm* ti@:te@
    # If using screen's internal scrollbuffer, save 10000 lines.
    defscrollback 10000

When using tmux(1), users may to adjust the options in the destination host's
$HOME/.tmux.conf file as follows:

    # On xterm, use the scrollbars by disabling ("@") the smcup ("ti") and
    # rmcup ("te") alternate screen sequences.
    set -ga terminal-overrides ',xterm*:smcup@:rmcup@'
    # If using screen's internal scrollbuffer, save 10000 lines.
    set -g history-limit 10000
    # Disable the status bar.
    set -g status off

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
    parser.add_argument("--proxy-options", default="-q -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null",
                        help=_("The proxy SSH options to use for the proxies and the outer SSH"))
    parser.add_argument("--outer-options", default="-tt",
                        help=_("The additional SSH options to use for the outer SSH"))
    parser.add_argument("-s", "--ssh-options", default="-X",
                        help=_("Any extra SSH options to use for the outer SSH"))
    parser.add_argument("uphps",
                        help=_("List of [User][:Password]@Host[:Port], separated by '+' (use '++' in passwords)"))
    parser.add_argument("command", nargs="*",
                        help=_("The command to execute"))
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
        if args.verbose:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(name)s %(levelname)s: %(message)s')
        else:
            logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        return run(args)
    except CommandLineArgumentException as e:
        logger.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
