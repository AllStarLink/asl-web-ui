"""asl-web-ui authentication helper.

Runs as root, one process per login (systemd socket activation with
Accept=yes). It speaks newline-delimited JSON on stdin/stdout, relays the PAM
conversation, and checks membership of the login group. It imports only the
Python standard library, never the web application.
"""
