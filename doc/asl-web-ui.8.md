% asl-web-ui(8) asl-web-ui @@HEAD-DEVELOP@@
% AllStarLink
% October 2026

# NAME
asl-web-ui - web management interface for AllStarLink nodes

# SYNOPSIS
**systemctl** (**start** | **stop** | **restart** | **status**) **asl-web-ui**

# DESCRIPTION
asl-web-ui is a browser-based interface for managing an AllStarLink 3 node
server. It is served by Apache or nginx at **/asl-web-ui/** and talks to the
**asl-web-ui** service through the Unix socket */run/asl-web-ui/web.sock*.

The service runs as the **asterisk** user and is started on demand by
**asl-web-ui.socket**.

# FILES
*/etc/asl-web-ui/asl-web-ui.ini*
: Settings for asl-web-ui. Restart the service after changing it.

*/etc/apache2/conf-available/asl-web-ui.conf*
: Apache configuration, enabled with **a2enconf asl-web-ui**.

*/etc/asl-web-ui/nginx.conf*
: nginx configuration. Add **include /etc/asl-web-ui/nginx.conf;** inside the
  **server { }** block of your site and reload nginx.

*/var/lib/asl-web-ui/*
: State kept by the service.

# SECURITY
Logins are refused over plain HTTP unless **allow_insecure_http** is set in
*asl-web-ui.ini*. Configure HTTPS in the web server instead.

# BUGS
Report bugs to https://github.com/AllStarLink/asl3-web-ui/issues

# COPYRIGHT
Copyright (C) 2026 AllStarLink, Inc. and contributors, under the terms of the
GNU Affero General Public License, version 3.
