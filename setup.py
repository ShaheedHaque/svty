#!/usr/bin/env python3
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
from distutils.core import setup
import pypandoc

long_description = pypandoc.convert('README.md', 'rst')

setup(
    name='svty',
    version='0.8',
    packages=['svty'],
    url='https://github.com/ShaheedHaque/svty',
    license='GPL-3.0',
    author='Shaheed Haque',
    author_email='srhaque@theiet.org',
    description='Curses UI for a combination of tmux/screen and SSH (with multiple jump hosts)',
    long_description=long_description,
    classifiers=["Topic :: Terminals :: Terminal Emulators/X Terminals",
                 "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
                 "Development Status :: 5 - Production/Stable"]
)
