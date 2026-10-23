% asl-web-ui(8) asl-web-ui @@HEAD-DEVELOP@@
% AllStarLink
% October 2026

# NAME
asl-web-ui - web management interface for AllStarLink nodes

# SYNOPSIS
**systemctl** (**start** | **stop** | **restart** | **status**) **asl-web-ui**

# DESCRIPTION
asl-web-ui is a browser-based interface for managing an AllStarLink 3 node
server: setting up nodes, Asterisk settings, backups, diagnostics, radio
interface tuning, and (for experienced users) the raw configuration files.
It does everything the asl3-menu tools (**asl-menu**, **node-setup**,
**asl-backup-menu**) do, works on the same files, and is built to tolerate
files edited by hand or by those tools.

It is served by Apache or nginx at **/asl-web-ui/** and talks to the
**asl-web-ui** service through the Unix socket */run/asl-web-ui/web.sock*.

# USERS
Log in with a Linux account on the server. The account must be a member of
the **asl-web-ui** group:

    sudo usermod -aG asl-web-ui USERNAME

Removing someone from the group takes effect on their next request. Logins
go through PAM (service **asl-web-ui**, */etc/pam.d/asl-web-ui*), so PAM
modules such as one-time codes work as for SSH. The **root** account cannot
log in.

Restarting or stopping Asterisk, rebooting, shutting down, restoring a
backup, restoring the default configuration, removing a node, fixing file
ownership and changing Allmon3's users ask for the password again if it was entered more than ten minutes
earlier.

# PROCESSES
**asl-web-ui.service**
: The web service, as user **asterisk**, sandboxed by systemd; it can write
  only */etc/asterisk* and its state directory. Started on demand by
  **asl-web-ui.socket**.

**asl-web-ui-auth@.service**
: One root process per login (socket **asl-web-ui-auth.socket**, reachable
  only by **asterisk**): the PAM conversation and the group check.

**asl-web-ui-priv@.service**
: One root process per privileged request (socket **asl-web-ui-priv.socket**,
  reachable only by **asterisk**): backups, restores, the default
  configuration, Allmon3's settings and users, the SA818 radio module, HTTPS
  and Let's Encrypt certificates in Apache, ownership fixes in
  */etc/asterisk*, the network interface list, the ASL3 appliance's
  fallback access point, and the 44Net Connect tunnel.
  Every request is authorized with polkit (**pkcheck**) for the calling
  process.

Starting, stopping and restarting **asterisk**, **allmon3** and
**asl3-update-nodelist**, rebooting and powering off use **systemctl**,
allowed for the **asterisk** user by the polkit rule below.

# POLKIT
*/usr/share/polkit-1/actions/org.allstarlink.asl-web-ui.policy*
: The privileged helper's actions, **org.allstarlink.asl-web-ui.***
  (default: administrators only).

*/usr/share/polkit-1/rules.d/50-asl-web-ui.rules*
: Grants those actions, and the service and power actions above, to the
  **asterisk** user. To restrict them, add a rule with a lower number in
  */etc/polkit-1/rules.d/* that returns **polkit.Result.NO**.

# FILES
*/etc/asl-web-ui/asl-web-ui.ini*, */etc/asl-web-ui/conf.d/\*.ini*
: Settings for asl-web-ui: the main file, then each file in *conf.d* in name
  order (later files win). Other packages put their settings in *conf.d*.
  Restart the service after changing them.

*/etc/apache2/conf-available/asl-web-ui.conf*
: Apache configuration, enabled with **a2enconf asl-web-ui**.

*/etc/asl-web-ui/nginx.conf*
: nginx configuration. Add **include /etc/asl-web-ui/nginx.conf;** inside the
  **server { }** block of your site and reload nginx.

*/etc/allmon3/*
: Allmon3's settings, changed on the Allmon3 page through the privileged
  helper. Each change restarts **allmon3**.

*/etc/apache2/sites-available/asl-web-ui-https.conf*
: Written by the HTTPS page for the names of the Let's Encrypt certificate
  (port 80 site with the optional redirect, port 443 site with the
  certificate). The certificate itself is managed by **certbot**(1) in
  */etc/letsencrypt*. Not used when **apache_vhosts** is **external**.

*/etc/asl-web-ui/apache-tls.conf*
: With **apache_vhosts = external** in the **[https]** section of the
  settings, another package (the ASL3 appliance) owns Apache's sites, and
  its port 443 site includes this file. The HTTPS page writes only this
  file: the Let's Encrypt certificate and certbot's
  */etc/letsencrypt/options-ssl-apache.conf*, or the self-signed certificate
  if the Let's Encrypt one is gone. The other package's port 80 site must
  be the default one and provides the redirect to HTTPS.
  **/usr/libexec/asl-web-ui/asl-web-ui-https-sync**, run by the packages,
  moves the certificate between this file and *asl-web-ui-https.conf* when
  the setting changes.

*/etc/sa818.conf*
: The SA818 radio module's settings, shared with **sa818-menu**(1) (same
  format), and programmed into the module with **sa818**(1).

*/usr/libexec/asl3/fallback-ap\**, *fallback-ap.timer*
: The fallback access point of **asl3-appliance-pc** or **asl3-appliance-pi**.
  The Network page offers it only when these are installed, and enables or
  disables the timer. Its settings stay in */etc/default/fallback-ap*.

*/etc/NetworkManager/system-connections/44net-connect.nmconnection*
: The 44Net Connect tunnel (on the ASL3 appliance only): a NetworkManager
  WireGuard connection on interface **wg44net** in the firewalld zone
  **44NetConnect**, written by the 44Net Connect page. It holds the tunnel's
  private key, so it is never included in backups or restored from them. In
  split-routing mode, **asl-web-ui-net44-routes.timer** keeps the routes to
  the AllStarLink servers up to date.

*/var/asl-backups/*
: Backups, shared with **asl-backup-menu** (same names and format). The
  include list is */var/asl-backups/asl-backup-files*. Archives made by
  asl-web-ui are readable only by root and the **asterisk** group.

*/var/lib/asl-web-ui/snapshots/*
: A copy of every file before asl-web-ui changed it, with a manifest
  (the last 50 changes).

*/var/lib/asl-web-ui/audit.jsonl*
: Who changed what, when, which files, the snapshot, and the result.

*/var/lib/asl-web-ui/connectivity.json*
: The last node connectivity check (**asl-node-auth-check**).

# SECURITY
Logins are refused over plain HTTP unless **allow_insecure_http** is set in
*asl-web-ui.ini*. Configure HTTPS in the web server instead; consider HSTS
and limiting access by address if the server is reachable from the
internet. Sessions are kept in memory, so restarting the service logs
everyone out. Failed logins are slowed down per address and per user and
are logged to the journal.

Restoring a backup writes only the paths in the include list, refuses
absolute paths, "..", links leading elsewhere and special files, never takes
file ownership from the archive, and saves the current configuration as a
backup first.

# SEE ALSO
**asl-menu**(1), **node-setup**(8), **asl-backup-menu**(1),
**asl-node-auth-check**(1), **sa818-menu**(1), **certbot**(1), **pkcheck**(1), **polkit**(8)

# BUGS
Report bugs to https://github.com/AllStarLink/asl-web-ui/issues

# COPYRIGHT
Copyright (C) 2026 AllStarLink, Inc. and contributors, under the terms of the
GNU Affero General Public License, version 3.
