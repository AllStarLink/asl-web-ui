"""HTTPS for Apache: a port 443 listener and Let's Encrypt certificates (issue #2).

Who owns Apache's sites depends on "apache_vhosts" in the [https] section
of asl-web-ui's settings (asl-web-ui.ini, then conf.d/*.ini):

own (the default): asl-web-ui owns one Apache site,
sites-available/asl-web-ui-https.conf, for the names the certificate is
for: a port 80 site (optionally redirecting to HTTPS, except Let's
Encrypt's checks) and, once there is a certificate, a port 443 site using
it. Both serve the same document root as Debian's default sites, so
asl-web-ui, Allmon3 and anything else enabled globally work the same.
Other sites (000-default, default-ssl) are left alone; requests for other
names still reach them.

external: another package (the ASL3 appliance) owns the sites, and its
port 443 site includes /etc/asl-web-ui/apache-tls.conf when it exists.
asl-web-ui writes only that file, with the certificate; the redirect is
the other package's business. Its port 80 site must be the default one
(no ServerName), so that certbot finds it for the names.

Either way the certificate's lines are guarded with <IfFile>: if the
certificate disappears behind asl-web-ui's back (certbot delete), Apache
falls back to the self-signed certificate instead of refusing to start.
The lines include certbot's options-ssl-apache.conf, its recommended TLS
settings. sync() moves the certificate between the two places when the
setting changes (asl-web-ui-https-sync, run by the packages).

certbot (python3-certbot-apache, from Debian) only obtains and renews the
certificate ("certonly --apache"); it does not edit Apache's sites. Its
renewal configuration reloads Apache after each renewal, and Debian's
certbot.timer runs the renewals. Each request starts with a dry run
against Let's Encrypt's staging server, which checks the names without
keeping a certificate; only if it passes is the real one requested.

Every change to Apache is checked with "apache2ctl configtest" before the
reload, and undone if the check fails.

If Cockpit is installed, it gets the same certificate (issue #25): a copy in
/etc/cockpit/ws-certs.d (Cockpit uses the last *.cert there, with the *.key
beside it), and a certbot deploy hook that copies each renewal there too.
"""

import configparser
import glob
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable

Output = Callable[[str], None]

SITE = "asl-web-ui-https"
APACHE = "/etc/apache2"
SETTINGS = "/etc/asl-web-ui/asl-web-ui.ini"
SETTINGS_D = "/etc/asl-web-ui/conf.d"
TLS_SNIPPET = "/etc/asl-web-ui/apache-tls.conf"
SNAKEOIL = ("/etc/ssl/certs/ssl-cert-snakeoil.pem", "/etc/ssl/private/ssl-cert-snakeoil.key")
LETSENCRYPT = "/etc/letsencrypt"
DOCUMENT_ROOT = "/var/www/html"
PACKAGES = ["python3-certbot-apache"]  # pulls in certbot
STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
RELOAD_HOOK = "systemctl reload apache2"
MARK = "# asl-web-ui: "
COCKPIT_CERTS = "/etc/cockpit/ws-certs.d"
COCKPIT_NAME = "90-asl-web-ui"  # after Cockpit's own 0-self-signed.cert
COCKPIT_HOOK = f"{LETSENCRYPT}/renewal-hooks/deploy/asl-web-ui-cockpit"
MAX_NAMES = 10
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_EMAIL = re.compile(r"^[^@\s,;'\"\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Programs, replaceable for tests.
BIN = {
    "apache2ctl": "/usr/sbin/apache2ctl",
    "a2enmod": "/usr/sbin/a2enmod",
    "a2dismod": "/usr/sbin/a2dismod",
    "a2ensite": "/usr/sbin/a2ensite",
    "a2dissite": "/usr/sbin/a2dissite",
    "certbot": "/usr/bin/certbot",
    "systemctl": "/usr/bin/systemctl",
    "apt-get": "/usr/bin/apt-get",
    "openssl": "/usr/bin/openssl",
    "make-ssl-cert": "/usr/sbin/make-ssl-cert",
    "dpkg-query": "/usr/bin/dpkg-query",
}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


class HttpsError(Exception):
    def __init__(self, message: str, code: str = "failed", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field


def run(name: str, *args: str, output: Output | None = None, timeout: float = 600, check: bool = False,
        env: dict | None = None) -> tuple[int, str]:
    """Run a program; stream its output lines to OUTPUT if given."""
    try:
        proc = subprocess.Popen([BIN[name], *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env={**ENV, **(env or {})})
    except FileNotFoundError:
        raise HttpsError(f"{BIN[name]} is not installed.", "unavailable")
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        if output:
            output(lines[-1])
    code = proc.wait(timeout=timeout)
    text = "\n".join(lines)
    if check and code != 0:
        raise HttpsError(f"{name} {' '.join(args)} failed (exit code {code}): {text[-400:]}")
    return code, text


# ---- names --------------------------------------------------------------------------------


def check_names(names) -> list[str]:
    if not isinstance(names, list) or not names:
        raise HttpsError("Enter the server's name as it is in DNS.", "invalid", "domains")
    out = []
    for raw in names:
        name = str(raw).strip().lower().rstrip(".")
        labels = name.split(".")
        if (len(labels) < 2 or len(name) > 253 or not all(_LABEL.match(label) for label in labels)
                or labels[-1].isdigit()):
            raise HttpsError(f"{raw!r} is not a host name such as node.example.org (no wildcards or IP "
                             "addresses: Let's Encrypt checks each name over HTTP).", "invalid", "domains")
        if name.endswith(".local") or name == "localhost":
            raise HttpsError(f"{name} is not a public name.", "invalid", "domains")
        if name not in out:
            out.append(name)
    if len(out) > MAX_NAMES:
        raise HttpsError(f"At most {MAX_NAMES} names.", "invalid", "domains")
    return out


def check_email(email) -> str | None:
    if email in (None, ""):
        return None
    email = str(email).strip()
    if not _EMAIL.match(email):
        raise HttpsError(f"{email!r} is not an email address.", "invalid", "email")
    return email


# ---- the managed site --------------------------------------------------------------------


def vhosts_mode(root: str) -> str:
    """"external" if another package owns Apache's sites, else "own"."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read([_rooted(root, SETTINGS), *sorted(glob.glob(os.path.join(_rooted(root, SETTINGS_D), "*.ini")))])
    except configparser.Error:
        return "own"
    return "external" if parser.get("https", "apache_vhosts", fallback="own").strip().lower() == "external" else "own"


def site_path(root: str) -> str:
    return os.path.join(root, APACHE.lstrip("/"), "sites-available", f"{SITE}.conf")


def snippet_path(root: str) -> str:
    return _rooted(root, TLS_SNIPPET)


def site_enabled(root: str) -> bool:
    return os.path.lexists(os.path.join(root, APACHE.lstrip("/"), "sites-enabled", f"{SITE}.conf"))


def _read_mark(path: str) -> dict | None:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(MARK):
                    return json.loads(line[len(MARK):])
    except (OSError, ValueError):
        pass
    return None


def read_site(root: str) -> dict | None:
    """The settings asl-web-ui wrote into its site (own) or TLS snippet (external), or None."""
    return _read_mark(snippet_path(root) if vhosts_mode(root) == "external" else site_path(root))


def render_tls(cert: str) -> list[str]:
    """The certificate lines for a port 443 site: Let's Encrypt's certificate
    while it exists, else the self-signed one, so Apache still starts."""
    live = f"{LETSENCRYPT}/live/{cert}"
    return [
        f"<IfFile {live}/fullchain.pem>",
        f"    SSLCertificateFile {live}/fullchain.pem",
        f"    SSLCertificateKeyFile {live}/privkey.pem",
        f"    Include {LETSENCRYPT}/options-ssl-apache.conf",
        "</IfFile>",
        f"<IfFile !{live}/fullchain.pem>",
        f"    SSLCertificateFile {SNAKEOIL[0]}",
        f"    SSLCertificateKeyFile {SNAKEOIL[1]}",
        "</IfFile>",
    ]


def render_snippet(names: list[str], cert: str) -> str:
    settings = {"domains": names, "redirect": False, "cert": cert}
    return "\n".join([
        "# The Let's Encrypt certificate for this system's port 443 site, which includes this",
        "# file. Written by asl-web-ui (its HTTPS page); changes made here are replaced.",
        MARK + json.dumps(settings),
        "",
        *render_tls(cert),
    ]) + "\n"


def render_site(names: list[str], redirect: bool, cert: str | None) -> str:
    settings = {"domains": names, "redirect": redirect, "cert": cert}
    head = [f"    ServerName {names[0]}"] + ([f"    ServerAlias {' '.join(names[1:])}"] if names[1:] else []) + [
        f"    DocumentRoot {DOCUMENT_ROOT}",
        "    ErrorLog ${APACHE_LOG_DIR}/error.log",
        "    CustomLog ${APACHE_LOG_DIR}/access.log combined",
    ]
    lines = [
        "# HTTPS for asl-web-ui's Let's Encrypt certificate. Written by asl-web-ui (its HTTPS",
        "# page); changes made here are replaced. Other names keep using the other sites.",
        MARK + json.dumps(settings),
        "",
        "<VirtualHost *:80>",
        *head,
    ]
    if redirect:
        lines += [
            "    RewriteEngine On",
            "    # Let's Encrypt checks each name, also at renewal, over plain HTTP.",
            "    RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/",
            "    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]",
        ]
    lines.append("</VirtualHost>")
    if cert:
        lines += [
            "",
            "<IfModule ssl_module>",
            "<VirtualHost *:443>",
            *head,
            "    SSLEngine on",
            *("    " + line for line in render_tls(cert)),
            "</VirtualHost>",
            "</IfModule>",
        ]
    return "\n".join(lines) + "\n"


class ApacheChange:
    """Change Apache's configuration and reload it, or put everything back.

    Records the old content of each file written or removed here, and which
    modules and sites were enabled here, so a failed configtest (or a
    failure afterwards) restores the previous state exactly."""

    def __init__(self, root: str, output: Output):
        self.root = root
        self.output = output
        self.old_files: dict[str, bytes | None] = {}
        self.was_enabled = site_enabled(root)
        self.enabled_mods: list[str] = []
        self.enabled_sites: list[str] = []

    def _remember(self, path: str) -> None:
        if path not in self.old_files:
            try:
                with open(path, "rb") as f:
                    self.old_files[path] = f.read()
            except FileNotFoundError:
                self.old_files[path] = None

    def write_file(self, path: str, text: str) -> None:
        self._remember(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)

    def remove_file(self, path: str) -> None:
        self._remember(path)
        if os.path.exists(path):
            os.unlink(path)

    def write_site(self, text: str) -> None:
        self.write_file(site_path(self.root), text)

    def enable_mod(self, mod: str) -> None:
        if not os.path.exists(os.path.join(self.root, APACHE.lstrip("/"), "mods-enabled", f"{mod}.load")):
            run("a2enmod", "-q", mod, check=True)
            self.enabled_mods.append(mod)
            self.output(f"Enabled Apache module {mod}.")

    def enable_site(self, site: str) -> None:
        if not os.path.lexists(os.path.join(self.root, APACHE.lstrip("/"), "sites-enabled", f"{site}.conf")):
            run("a2ensite", "-q", site, check=True)
            self.enabled_sites.append(site)
            self.output(f"Enabled Apache site {site}.")

    def disable_site(self, site: str) -> None:
        if os.path.lexists(os.path.join(self.root, APACHE.lstrip("/"), "sites-enabled", f"{site}.conf")):
            run("a2dissite", "-q", site, check=True)

    def apply(self) -> None:
        code, text = run("apache2ctl", "configtest")
        if code != 0:
            self.undo()
            raise HttpsError(f"Apache rejected the new configuration, so it was put back: {text[-500:]}")
        # Not running (e.g. during a package installation that restarted it
        # too often): nothing to reload, it starts with the new configuration.
        run("systemctl", "try-reload-or-restart", "apache2", check=True)
        self.output("Apache reloaded.")

    def undo(self) -> None:
        for site in self.enabled_sites:
            run("a2dissite", "-q", site)
        for mod in self.enabled_mods:
            run("a2dismod", "-q", "-f", mod)
        for path, old in self.old_files.items():
            if old is None:
                if os.path.exists(path):
                    os.unlink(path)
            else:
                with open(path, "wb") as f:
                    f.write(old)
        if self.was_enabled and not site_enabled(self.root):
            run("a2ensite", "-q", SITE)
        elif not self.was_enabled and site_enabled(self.root):
            run("a2dissite", "-q", SITE)


# ---- Cockpit -------------------------------------------------------------------------------


def _rooted(root: str, path: str) -> str:
    return os.path.join(root, path.lstrip("/"))


def cockpit_installed() -> bool:
    return _installed("cockpit-ws")


def render_cockpit_hook(cert: str) -> str:
    live = f"{LETSENCRYPT}/live/{cert}"
    dest = f"{COCKPIT_CERTS}/{COCKPIT_NAME}"
    return "\n".join([
        "#!/bin/sh",
        "# Gives Cockpit the renewed Let's Encrypt certificate that Apache uses. Written by",
        "# asl-web-ui (its HTTPS page); changes made here are replaced.",
        f'[ "$RENEWED_LINEAGE" = "{live}" ] || exit 0',
        "[ -d /etc/cockpit ] || exit 0",
        f"mkdir -p {COCKPIT_CERTS}",
        f'install -m 644 "$RENEWED_LINEAGE/fullchain.pem" {dest}.cert.tmp',
        f'install -m 600 "$RENEWED_LINEAGE/privkey.pem" {dest}.key.tmp',
        f"mv -f {dest}.key.tmp {dest}.key",
        f"mv -f {dest}.cert.tmp {dest}.cert",
        "systemctl try-restart cockpit.service",
    ]) + "\n"


def _copy(src: str, dest: str, mode: int) -> None:
    tmp = dest + ".tmp"
    with open(src, "rb") as f:
        data = f.read()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, dest)


def use_for_cockpit(root: str, cert: str, output: Output) -> dict:
    """Give Cockpit the certificate CERT (a name in /etc/letsencrypt/live), now and after renewals."""
    if not cockpit_installed():
        raise HttpsError("Cockpit is not installed.", "unavailable")
    live = _rooted(root, f"{LETSENCRYPT}/live/{cert}")
    if not os.path.exists(os.path.join(live, "fullchain.pem")):
        raise HttpsError("There is no Let's Encrypt certificate yet.", "not_found")
    hook = _rooted(root, COCKPIT_HOOK)
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook + ".tmp", "w") as f:
        f.write(render_cockpit_hook(cert))
    os.chmod(hook + ".tmp", 0o755)
    os.replace(hook + ".tmp", hook)
    certs = _rooted(root, COCKPIT_CERTS)
    os.makedirs(certs, exist_ok=True)
    _copy(os.path.join(live, "privkey.pem"), os.path.join(certs, f"{COCKPIT_NAME}.key"), 0o600)
    _copy(os.path.join(live, "fullchain.pem"), os.path.join(certs, f"{COCKPIT_NAME}.cert"), 0o644)
    output(f"Cockpit now uses the certificate too ({COCKPIT_CERTS}/{COCKPIT_NAME}.cert).")
    run("systemctl", "try-restart", "cockpit.service")
    output("Cockpit restarted; anyone logged in to it logs in again.")
    return {"cockpit": True}


def stop_cockpit(root: str, output: Output) -> bool:
    """Take asl-web-ui's certificate and renewal hook away from Cockpit, if there."""
    removed = False
    for path in (COCKPIT_HOOK, f"{COCKPIT_CERTS}/{COCKPIT_NAME}.cert", f"{COCKPIT_CERTS}/{COCKPIT_NAME}.key"):
        try:
            os.unlink(_rooted(root, path))
            removed = True
        except FileNotFoundError:
            pass
    if removed:
        run("systemctl", "try-restart", "cockpit.service")
        output("Cockpit uses its own certificate again.")
    return removed


def cockpit_status(root: str, cert: str | None) -> dict:
    out: dict = {"installed": cockpit_installed()}
    if not out["installed"]:
        return out
    certs = _rooted(root, COCKPIT_CERTS)
    try:
        files = sorted(f for f in os.listdir(certs) if f.endswith(".cert"))
    except OSError:
        files = []
    out["uses"] = files[-1] if files else None  # None: Cockpit makes a self-signed one
    ours = os.path.join(certs, f"{COCKPIT_NAME}.cert")
    current = False
    if cert and os.path.exists(ours):
        try:
            with open(ours, "rb") as a, open(_rooted(root, f"{LETSENCRYPT}/live/{cert}/fullchain.pem"), "rb") as b:
                current = a.read() == b.read()
        except OSError:
            pass
    # Cockpit presents the Let's Encrypt certificate: ours, up to date, and the one it picks.
    out["letsencrypt"] = current and out["uses"] == f"{COCKPIT_NAME}.cert"
    out["hook"] = os.path.exists(_rooted(root, COCKPIT_HOOK))
    return out


# ---- status -------------------------------------------------------------------------------


def _installed(package: str) -> bool:
    try:
        code, text = run("dpkg-query", "-W", "-f=${Status}", package)
    except HttpsError:
        return False
    return code == 0 and text.endswith("installed") and "not-installed" not in text


def _iso(openssl_date: str) -> str:
    """openssl's "Dec 19 01:04:16 2026 GMT" as ISO 8601 (UTC), which browsers parse."""
    import time
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.strptime(openssl_date, "%b %d %H:%M:%S %Y %Z"))
    except ValueError:
        return openssl_date


def cert_info(pem_path: str | None = None, pem: str | None = None) -> dict | None:
    """Subject names, issuer and expiry of a certificate (file or PEM text)."""
    args = ["x509", "-noout", "-subject", "-issuer", "-enddate", "-ext", "subjectAltName", "-nameopt", "oneline"]
    try:
        if pem_path:
            code, text = run("openssl", *args, "-in", pem_path)
        else:
            proc = subprocess.run([BIN["openssl"], *args], input=pem, capture_output=True, text=True, env=ENV)
            code, text = proc.returncode, proc.stdout
    except (HttpsError, OSError):
        return None
    if code != 0:
        return None
    info = {"subject": None, "issuer": None, "expires": None, "names": []}
    for line in text.splitlines():
        if line.startswith("subject="):
            info["subject"] = line[8:].strip()
        elif line.startswith("issuer="):
            info["issuer"] = line[7:].strip()
        elif line.startswith("notAfter="):
            info["expires"] = _iso(line[9:].strip())
        elif "DNS:" in line:
            info["names"] = [n.strip()[4:] for n in line.split(",") if n.strip().startswith("DNS:")]
    issuer = info["issuer"] or ""
    info["staging"] = "STAGING" in issuer.upper()
    info["self_signed"] = info["issuer"] == info["subject"]
    return info


def served_certificate(name: str | None, port: int = 443) -> dict | None:
    """The certificate Apache actually presents for NAME (SNI) on this machine."""
    import socket
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=name or None) as tls:
                der = tls.getpeercert(binary_form=True)
    except OSError:
        return None
    return cert_info(pem=ssl.DER_cert_to_PEM_cert(der)) if der else None


def renewal(root: str, cert: str) -> dict | None:
    path = os.path.join(root, LETSENCRYPT.lstrip("/"), "renewal", f"{cert}.conf")
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return None
    values = dict(re.findall(r"^\s*([a-z_]+)\s*=\s*(.*?)\s*$", text, re.M))
    return {"server": values.get("server"), "staging": values.get("server") == STAGING,
            "authenticator": values.get("authenticator"), "renew_hook": values.get("renew_hook")}


def status(root: str = "/") -> dict:
    apache = os.path.exists(os.path.join(root, APACHE.lstrip("/"), "apache2.conf"))
    out: dict = {"apache": apache, "packages": _installed(PACKAGES[0]), "vhosts": vhosts_mode(root)}
    if not apache:
        return out
    code, text = run("apache2ctl", "-S")
    out["listening_443"] = bool(re.search(r"^\*?[^\s]*:443\s", text, re.M))
    code, active = run("systemctl", "is-active", "certbot.timer")
    out["timer"] = active.strip()
    site = read_site(root)
    out["site"] = site
    out["site_enabled"] = os.path.exists(snippet_path(root)) if out["vhosts"] == "external" else site_enabled(root)
    name = site["domains"][0] if site else None
    out["served"] = served_certificate(name) if out["listening_443"] else None
    if site and site.get("cert"):
        live = os.path.join(root, LETSENCRYPT.lstrip("/"), "live", site["cert"], "cert.pem")
        out["certificate"] = cert_info(pem_path=live) if os.path.exists(live) else None
        out["renewal"] = renewal(root, site["cert"])
    out["cockpit"] = cockpit_status(root, site.get("cert") if site else None)
    return out


# ---- actions ------------------------------------------------------------------------------


def install_packages(output: Output) -> dict:
    code, _ = run("apt-get", "install", "-y", *PACKAGES, output=output, env={"DEBIAN_FRONTEND": "noninteractive"})
    if code != 0:
        raise HttpsError(f"apt-get failed (exit code {code}).")
    run("systemctl", "enable", "--now", "certbot.timer")
    return {"installed": PACKAGES}


def enable_listener(root: str, output: Output) -> dict:
    """Make Apache listen for HTTPS on port 443 with the self-signed certificate
    (Debian's default-ssl site), if nothing serves port 443 yet."""
    if vhosts_mode(root) == "external":
        output("This system's web server configuration provides the HTTPS site; asl-web-ui leaves it alone.")
        return {"changed": False}
    code, text = run("apache2ctl", "-S")
    if re.search(r"^\*?[^\s]*:443\s", text, re.M):
        output("Apache already serves HTTPS on port 443.")
        return {"changed": False}
    snakeoil = os.path.join(root, "etc/ssl/certs/ssl-cert-snakeoil.pem")
    if not os.path.exists(snakeoil):
        if not os.path.exists(BIN["make-ssl-cert"]):
            run("apt-get", "install", "-y", "ssl-cert", output=output, env={"DEBIAN_FRONTEND": "noninteractive"},
                check=True)
        run("make-ssl-cert", "generate-default-snakeoil", output=output, check=True)
    change = ApacheChange(root, output)
    try:
        change.enable_mod("ssl")
        change.enable_site("default-ssl")
        change.apply()
    except HttpsError:
        change.undo()
        raise
    return {"changed": True}


def _certbot_args(names: list[str], email: str | None, dry_run: bool, force: bool) -> list[str]:
    args = ["certonly", "--apache", "--non-interactive", "--agree-tos", "--cert-name", names[0]]
    args += ["--email", email, "--no-eff-email"] if email else ["--register-unsafely-without-email"]
    # A dry run asks Let's Encrypt's staging server to check every name and
    # keeps nothing, so a mistake does not count against the real server's
    # limits on failed checks.
    args += ["--dry-run"] if dry_run else ["--deploy-hook", RELOAD_HOOK]
    if force:
        args.append("--force-renewal")
    for name in names:
        args += ["-d", name]
    return args


def ca_problems(text: str) -> list[str]:
    """What Let's Encrypt said was wrong, from certbot's output: each failed
    name's "Domain:" and "Detail:" lines, or the line after "An unexpected
    error occurred:" (rate limits and other refused orders)."""
    problems = []
    domain = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("Domain:"):
            domain = line[len("Domain:"):].strip()
        elif line.startswith("Detail:") and domain:
            problems.append(f"{domain}: {line[len('Detail:'):].strip()}")
            domain = None
        elif line == "An unexpected error occurred:" and i + 1 < len(lines) and lines[i + 1].strip():
            problems.append(lines[i + 1].strip())
    return problems


def obtain(root: str, args: dict, output: Output) -> dict:
    names = check_names(args.get("domains"))
    email = check_email(args.get("email"))
    if args.get("agree_tos") is not True:
        raise HttpsError("Agree to the Let's Encrypt subscriber agreement first.", "invalid", "agree_tos")
    external = vhosts_mode(root) == "external"
    redirect = bool(args.get("redirect")) and not external
    if not os.path.exists(BIN["certbot"]):
        raise HttpsError("certbot is not installed. Install it first.", "unavailable")
    old = read_site(root)
    cert = names[0]
    existing = renewal(root, cert)
    # A test certificate from an earlier version is replaced even though it
    # is not due for renewal yet.
    force = existing is not None and existing["staging"]

    # 1. A port 80 site for the names, so that certbot finds them. With
    # external sites, certbot uses their default port 80 site.
    change = ApacheChange(root, output)
    if not external:
        try:
            if redirect:
                change.enable_mod("rewrite")
            change.write_site(render_site(names, redirect,
                                          old.get("cert") if old and old.get("domains") == names else None))
            change.enable_site(SITE)
            change.apply()
        except HttpsError:
            change.undo()
            raise

    # 2. A dry run, then the certificate.
    for dry_run in (True, False):
        certbot_args = _certbot_args(names, email, dry_run, force and not dry_run)
        output("# certbot " + " ".join(certbot_args))
        code, text = run("certbot", *certbot_args, output=output, timeout=600)
        if code != 0:
            if not external:
                change.undo()
                change.apply()
            problems = ca_problems(text)
            raise HttpsError(("Let's Encrypt's test run failed, so no certificate was requested; "
                              if dry_run else "certbot could not get the certificate; ") + "Apache is as it was. " + (
                "Let's Encrypt reported: " + "; ".join(problems) if problems else
                "Check that each name points to this server in DNS and that port 80 is reachable from the internet."))

    # 3. The HTTPS site with it.
    final = ApacheChange(root, output)
    try:
        final.enable_mod("ssl")
        if external:
            final.write_file(snippet_path(root), render_snippet(names, cert))
        else:
            final.write_site(render_site(names, redirect, cert))
        final.apply()
    except HttpsError:
        final.undo()
        raise

    # 4. Cockpit, if installed, with the same certificate.
    cockpit = False
    if cockpit_installed():
        try:
            cockpit = use_for_cockpit(root, cert, output)["cockpit"]
        except (HttpsError, OSError) as exc:
            output(f"Apache uses the certificate, but Cockpit could not be given it: {getattr(exc, 'message', exc)}")
    return {"domains": names, "cert": cert, "cockpit": cockpit, "certificate": cert_info(
        pem_path=os.path.join(root, LETSENCRYPT.lstrip("/"), "live", cert, "cert.pem"))}


def set_redirect(root: str, redirect: bool, output: Output) -> dict:
    if vhosts_mode(root) == "external":
        raise HttpsError("The HTTP to HTTPS redirect is part of this system's web server configuration.", "invalid")
    site = read_site(root)
    if not site:
        raise HttpsError("There is no Let's Encrypt site yet.", "not_found")
    change = ApacheChange(root, output)
    try:
        if redirect:
            change.enable_mod("rewrite")
        change.write_site(render_site(site["domains"], redirect, site.get("cert")))
        change.apply()
    except HttpsError:
        change.undo()
        raise
    return {"redirect": redirect}


def cockpit(root: str, output: Output) -> dict:
    site = read_site(root)
    if not site or not site.get("cert"):
        raise HttpsError("There is no Let's Encrypt certificate yet.", "not_found")
    try:
        return use_for_cockpit(root, site["cert"], output)
    except OSError as exc:
        raise HttpsError(f"Could not give Cockpit the certificate: {exc}")


def renew_test(root: str, output: Output) -> dict:
    site = read_site(root)
    if not site or not site.get("cert"):
        raise HttpsError("There is no Let's Encrypt certificate yet.", "not_found")
    code, _ = run("certbot", "renew", "--dry-run", "--cert-name", site["cert"], output=output)
    return {"ok": code == 0}


def remove(root: str, delete_certificate: bool, output: Output) -> dict:
    site = read_site(root)
    external = vhosts_mode(root) == "external"
    change = ApacheChange(root, output)
    try:
        if external:
            change.remove_file(snippet_path(root))
        else:
            change.disable_site(SITE)
            change.remove_file(site_path(root))
        change.apply()
    except HttpsError:
        change.undo()
        raise
    output("Apache uses the self-signed certificate again." if external else
           "Removed asl-web-ui's HTTPS site; the other Apache sites are unchanged.")
    stop_cockpit(root, output)
    if delete_certificate and site and site.get("cert"):
        run("certbot", "delete", "--non-interactive", "--cert-name", site["cert"], output=output)
    return {"removed": True}


# ---- switching between own and external sites ---------------------------------------------


def sync(root: str, output: Output) -> dict:
    """Put the certificate where the current setting wants it: from
    asl-web-ui's own site into the TLS snippet (external), or back (own).
    Run by the packages when the setting may have changed."""
    if not os.path.exists(os.path.join(root, APACHE.lstrip("/"), "apache2.conf")):
        return {"changed": False}
    external = vhosts_mode(root) == "external"
    site, snippet = site_path(root), snippet_path(root)
    change = ApacheChange(root, output)
    try:
        if external and os.path.exists(site):
            settings = _read_mark(site)
            if settings and settings.get("cert"):
                change.enable_mod("ssl")
                change.write_file(snippet, render_snippet(settings["domains"], settings["cert"]))
            change.disable_site(SITE)
            change.remove_file(site)
            change.apply()
            output(f"Moved the Let's Encrypt certificate from {site_path('/')} to {TLS_SNIPPET}."
                   if settings and settings.get("cert") else f"Removed {site_path('/')}.")
        elif not external and os.path.exists(snippet):
            settings = _read_mark(snippet)
            if settings and settings.get("cert"):
                change.enable_mod("ssl")
                change.write_site(render_site(settings["domains"], False, settings["cert"]))
                change.enable_site(SITE)
            change.remove_file(snippet)
            change.apply()
            output(f"Moved the Let's Encrypt certificate from {TLS_SNIPPET} to {site_path('/')}."
                   if settings and settings.get("cert") else f"Removed {TLS_SNIPPET}.")
        else:
            return {"changed": False}
    except HttpsError:
        change.undo()
        raise
    return {"changed": True}


def main() -> None:
    """asl-web-ui-https-sync [--mode]: sync(), or print the current setting."""
    if sys.argv[1:] == ["--mode"]:
        print(vhosts_mode("/"))
        return
    try:
        sync("/", print)
    except HttpsError as exc:
        print(f"asl-web-ui-https-sync: {exc.message}", file=sys.stderr)
        sys.exit(1)
