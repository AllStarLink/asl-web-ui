"""HTTPS for Apache: a port 443 listener and Let's Encrypt certificates (issue #2).

asl-web-ui owns one Apache site, sites-available/asl-web-ui-https.conf,
for the names the certificate is for: a port 80 site (optionally
redirecting to HTTPS, except Let's Encrypt's checks) and, once there is a
certificate, a port 443 site using it. Both serve the same document root as
Debian's default sites, so asl-web-ui, Allmon3 and anything else enabled
globally work the same. Other sites (000-default, default-ssl, an
appliance's own) are left alone; requests for other names still reach them.

certbot (python3-certbot-apache, from Debian) only obtains and renews the
certificate ("certonly --apache"); it does not edit Apache's sites. Its
renewal configuration reloads Apache after each renewal, and Debian's
certbot.timer runs the renewals.

Every change to Apache is checked with "apache2ctl configtest" before the
reload, and undone if the check fails.
"""

import json
import os
import re
import subprocess
from collections.abc import Callable

Output = Callable[[str], None]

SITE = "asl-web-ui-https"
APACHE = "/etc/apache2"
LETSENCRYPT = "/etc/letsencrypt"
DOCUMENT_ROOT = "/var/www/html"
PACKAGES = ["python3-certbot-apache"]  # pulls in certbot
STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
RELOAD_HOOK = "systemctl reload apache2"
MARK = "# asl-web-ui: "
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


def site_path(root: str) -> str:
    return os.path.join(root, APACHE.lstrip("/"), "sites-available", f"{SITE}.conf")


def site_enabled(root: str) -> bool:
    return os.path.lexists(os.path.join(root, APACHE.lstrip("/"), "sites-enabled", f"{SITE}.conf"))


def read_site(root: str) -> dict | None:
    """The settings asl-web-ui wrote into its site, or None."""
    try:
        with open(site_path(root)) as f:
            for line in f:
                if line.startswith(MARK):
                    return json.loads(line[len(MARK):])
    except (OSError, ValueError):
        pass
    return None


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
        live = f"{LETSENCRYPT}/live/{cert}"
        lines += [
            "",
            "<IfModule ssl_module>",
            "<VirtualHost *:443>",
            *head,
            "    SSLEngine on",
            f"    SSLCertificateFile {live}/fullchain.pem",
            f"    SSLCertificateKeyFile {live}/privkey.pem",
            f"    Include {LETSENCRYPT}/options-ssl-apache.conf",
            "</VirtualHost>",
            "</IfModule>",
        ]
    return "\n".join(lines) + "\n"


class ApacheChange:
    """Change Apache's configuration and reload it, or put everything back.

    Records the site file's old content and which modules and sites were
    enabled here, so a failed configtest (or a failure afterwards) restores
    the previous state exactly."""

    def __init__(self, root: str, output: Output):
        self.root = root
        self.output = output
        self.path = site_path(root)
        try:
            with open(self.path, "rb") as f:
                self.old_site: bytes | None = f.read()
        except FileNotFoundError:
            self.old_site = None
        self.was_enabled = site_enabled(root)
        self.enabled_mods: list[str] = []
        self.enabled_sites: list[str] = []

    def write_site(self, text: str) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)

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
        run("systemctl", "reload", "apache2", check=True)
        self.output("Apache reloaded.")

    def undo(self) -> None:
        for site in self.enabled_sites:
            run("a2dissite", "-q", site)
        for mod in self.enabled_mods:
            run("a2dismod", "-q", "-f", mod)
        if self.old_site is None:
            if os.path.exists(self.path):
                os.unlink(self.path)
        else:
            with open(self.path, "wb") as f:
                f.write(self.old_site)
        if self.was_enabled and not site_enabled(self.root):
            run("a2ensite", "-q", SITE)
        elif not self.was_enabled and site_enabled(self.root):
            run("a2dissite", "-q", SITE)


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
    out: dict = {"apache": apache, "packages": _installed(PACKAGES[0])}
    if not apache:
        return out
    code, text = run("apache2ctl", "-S")
    out["listening_443"] = bool(re.search(r"^\*?[^\s]*:443\s", text, re.M))
    code, active = run("systemctl", "is-active", "certbot.timer")
    out["timer"] = active.strip()
    site = read_site(root)
    out["site"] = site
    out["site_enabled"] = site_enabled(root)
    name = site["domains"][0] if site else None
    out["served"] = served_certificate(name) if out["listening_443"] else None
    if site and site.get("cert"):
        live = os.path.join(root, LETSENCRYPT.lstrip("/"), "live", site["cert"], "cert.pem")
        out["certificate"] = cert_info(pem_path=live) if os.path.exists(live) else None
        out["renewal"] = renewal(root, site["cert"])
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


def _certbot_args(names: list[str], email: str | None, staging: bool, force: bool) -> list[str]:
    args = ["certonly", "--apache", "--non-interactive", "--agree-tos", "--cert-name", names[0],
            "--deploy-hook", RELOAD_HOOK]
    args += ["--email", email, "--no-eff-email"] if email else ["--register-unsafely-without-email"]
    if staging:
        args.append("--staging")
    if force:
        args.append("--force-renewal")
    for name in names:
        args += ["-d", name]
    return args


def obtain(root: str, args: dict, output: Output) -> dict:
    names = check_names(args.get("domains"))
    email = check_email(args.get("email"))
    if args.get("agree_tos") is not True:
        raise HttpsError("Agree to the Let's Encrypt subscriber agreement first.", "invalid", "agree_tos")
    staging = bool(args.get("staging"))
    redirect = bool(args.get("redirect"))
    if not os.path.exists(BIN["certbot"]):
        raise HttpsError("certbot is not installed. Install it first.", "unavailable")
    old = read_site(root)
    cert = names[0]
    existing = renewal(root, cert)
    # Switching between test and real certificates replaces the certificate
    # even though the current one is not due for renewal yet.
    force = existing is not None and existing["staging"] != staging

    # 1. A port 80 site for the names, so that certbot finds them.
    change = ApacheChange(root, output)
    try:
        if redirect:
            change.enable_mod("rewrite")
        change.write_site(render_site(names, redirect, old.get("cert") if old and old.get("domains") == names else None))
        change.enable_site(SITE)
        change.apply()
    except HttpsError:
        change.undo()
        raise

    # 2. The certificate.
    output("# certbot " + " ".join(_certbot_args(names, email, staging, force)))
    code, text = run("certbot", *_certbot_args(names, email, staging, force), output=output, timeout=600)
    if code != 0:
        change.undo()
        change.apply()
        raise HttpsError("certbot could not get the certificate; Apache is as it was. Check that each name "
                         "points to this server in DNS and that port 80 is reachable from the internet.")

    # 3. The HTTPS site with it.
    final = ApacheChange(root, output)
    try:
        final.enable_mod("ssl")
        final.write_site(render_site(names, redirect, cert))
        final.apply()
    except HttpsError:
        final.undo()
        raise
    return {"domains": names, "cert": cert, "staging": staging, "certificate": cert_info(
        pem_path=os.path.join(root, LETSENCRYPT.lstrip("/"), "live", cert, "cert.pem"))}


def set_redirect(root: str, redirect: bool, output: Output) -> dict:
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


def renew_test(root: str, output: Output) -> dict:
    site = read_site(root)
    if not site or not site.get("cert"):
        raise HttpsError("There is no Let's Encrypt certificate yet.", "not_found")
    code, _ = run("certbot", "renew", "--dry-run", "--cert-name", site["cert"], output=output)
    return {"ok": code == 0}


def remove(root: str, delete_certificate: bool, output: Output) -> dict:
    site = read_site(root)
    change = ApacheChange(root, output)
    try:
        change.disable_site(SITE)
        if os.path.exists(change.path):
            os.unlink(change.path)
        change.apply()
    except HttpsError:
        change.undo()
        raise
    output("Removed asl-web-ui's HTTPS site; the other Apache sites are unchanged.")
    if delete_certificate and site and site.get("cert"):
        run("certbot", "delete", "--non-interactive", "--cert-name", site["cert"], output=output)
    return {"removed": True}
