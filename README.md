# svty
Curses UI for a combination of tmux/screen and SSH (with multiple jump hosts).

* SSH is often used in environments where lab machines are located behind one or more jump hosts. Svty allows convenient access to these targets whatever combination of password-less, manually-typed password or even hard-coded password authentications are needed..

    * Of course, svty works fine on your local machine too.

* tmux(1) and screen(1) are often used to provide for persistence sessions, but selecting the correct previously created session is typically a fiddly affair. Svty simplifies this by displaying the *content* of the saved sessions.

    * If neither tmux nor screen are available, svty falls back to just a regular SSH interactive session (or indeed the local equivalent).

## Installation

```bash
$ pip3 install svty
```

## Interactive use
Svty is typically run from a command line, or can be used with programs like konsole(1) and gnome-terminal(1). This works well if you don't need to specify any passwords interactively:
    
```bash
$ konsole -e svty jumphost+root@192.168.1.123
$ gnome-terminal -e 'svty jumphost+root@192.168.1.123'
```

Some GUI terminal emulators such as konsole can use commands like this to persistently configure terminal sessions.

Alternatively, just run svty directly, and you will be prompted as needed (password-less and hard-coded passwords are dealt with automatically). Examples:

1. Jump through jumphost to reach videoserver. The jumphost password is not needed because password-less login has been set up:

    ```bash
    $ copy-ssh-id jumphost
    $ svty srhaque@jumphost+admin:secret@videoserver
    ```

1. As before, jump through jumphost to reach videoserver. But this time, the user prefers to be prompted for the password on videoserver:

    ```bash
    $ svty srhaque@jumphost+admin@videoserver
    ```

1.  Jump through both jumphost and videoserver to reach videoslave2:

    ```bash
    $ svty srhaque@jumphost+admin@videoserver+admin:mycat@videoslave2
    ```

### Navigation model - basics

In each case, you'll end up on the home screen:

* Start on the home screen:  
    ![Home Screen][homescreen]  
    Here you see two tmux session and two screen sessions. One of each is already attached to a client, whereas the others are not.
* Use left/right arrow keys to view any of the tmux or screen session screens:  
    ![Capture from tmux(1)][tmux-capture]  
    ![Capture from screen(1)][screen-capture]  
    Notice that sessions "\[2\]" and "\[14083.14027\]" are from tmux and screen respectively, but they are presented in a uniform manner.
* Hit return to resume it:  
    ![Resumed tmux(1)][tmux-resume]  
    ![Resumed screen(1)][screen-resume]  
    Now you are in tmux and screen respectively, and svty has disappeared from view (of course, the SSH connection is setup for you is still there though).
* If you continue to scroll left/right, and end up on the home screen, hitting return there will create a new session.

    * The new session will be based on the first of tmux, screen, or plain vanilla SSH that works.
    * **TBD** Should svty push local tmux and screen settings to the new session? That would avoid having to manually configure each of your target systems with your favourite settings! Feedback or code welcome.

* Use "Q" or "q" on any screen to exit svty.

### Navigation model - additional features

* The UI model looks like this:  
    | Home Screen      | tmux Session Screens... | screen Session Screens... |  
    |------------------|-------------------------|---------------------------|  
    | Additional pages | Additional pages        | Additional pages          |  
    | ...              | ...                     | ...                       |  
    | Additional pages | Additional pages        | Additional pages          |
* On any screen, use Page Down to view the additional pages.

    * On the Home Screen, see the internal logging for svty. You may wish to invoke svty with the -v option to see more detail.
    * On a Session Screen, see the tmux or screen metadata for the session.
    * Use Page Up to get back to the top page, and be able to scroll left/right.

## Programmatic use

[homescreen]: https://github.com/ShaheedHaque/svty/raw/master/images/homescreen.png "Home Screen"
[screen-capture]: https://github.com/ShaheedHaque/svty/raw/master/images/screen-capture.png "Capture from screen(1)"
[screen-resume]: https://github.com/ShaheedHaque/svty/raw/master/images/screen-resume.png "Resumed screen(1)"
[tmux-capture]: https://github.com/ShaheedHaque/svty/raw/master/images/tmux-capture.png "Capture from tmux(1)"
[tmux-resume]: https://github.com/ShaheedHaque/svty/raw/master/images/tmux-resume.png "Resumed tmux(1)"
