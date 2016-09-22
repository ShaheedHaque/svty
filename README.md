# svty
Curses UI for a combination of tmux/screen and SSH (with multiple jump hosts).

* SSH is often used in environments where lab machines are located behind one or more jump hosts. Svty allows convenient access to these targets whatever combination of password-less, manually-typed password or even hard-coded password authentications are needed..

    * Of course, svty works fine on your local machine too.

* tmux(1) and screen(1) are often used to provide for persistence sessions, but selecting the correct previously created session is typically a fiddly affair. Svty simplifies this by displaying the *content* of the saved sessions.

    * If neither tmux nor screen are available, svty falls back to just a regular SSH interactive session (or indeed the local equivalent).

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

In each case, you'll end up on the home screen:

* Start on the home screen
![Home Screen][homescreen]
* Use left/right arrow keys to view any of the tmux(1) or screen(1) sessions:
![Capture from tmux(1)][tmux-capture]
![Capture from screen(1)][screen-capture] 
* Hit return to resume it:
![Resumed tmux(1)][tmux-resume] 
![Resumed screen(1)][screen-resume] 

## Programmatic use

[homescreen]: https://github.com/ShaheedHaque/svty/raw/master/images/homescreen.png "Home Screen"
[screen-capture]: https://github.com/ShaheedHaque/svty/raw/master/images/screen-capture.png "Capture from screen(1)"
[screen-resume]: https://github.com/ShaheedHaque/svty/raw/master/images/screen-resume.png "Resumed screen(1)"
[tmux-capture]: https://github.com/ShaheedHaque/svty/raw/master/images/tmux-capture.png "Capture from tmux(1)"
[tmux-resume]: https://github.com/ShaheedHaque/svty/raw/master/images/tmux-resume.png "Resumed tmux(1)"
