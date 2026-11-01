"""HTTPS and Let's Encrypt through the API.

The helper's commands run in-process on a temporary root. apache2ctl,
a2enmod/a2ensite, systemctl, apt-get and certbot are stand-ins that act on
that root (certbot writes a self-signed certificate where Let's Encrypt's
would go, and its renewal file); openssl is the real one.
"""

import pytest

from asl_web_ui_priv import https
from test_backups_api import cloud, env  # noqa: F401 (fixtures)

FAKES = {
    "apache2ctl": """
case "$1" in
  -S) for f in $ROOT/etc/apache2/sites-enabled/*.conf; do
        [ -e "$f" ] || continue
        grep -q '<VirtualHost \\*:443>' "$f" && echo "*:443                  x ($f:1)"
        grep -q '<VirtualHost \\*:80>' "$f" && echo "*:80                   x ($f:1)"
      done; exit 0 ;;
  configtest) [ -e $ROOT/configtest-fails ] && { echo "Syntax error on line 1"; exit 1; }; echo "Syntax OK" ;;
esac""",
    "a2enmod": 'for m; do [ "$m" = -q ] || ln -sf ../mods-available/$m.load $ROOT/etc/apache2/mods-enabled/$m.load; done',
    "a2dismod": 'for m; do case "$m" in -*) ;; *) rm -f $ROOT/etc/apache2/mods-enabled/$m.load ;; esac; done',
    "a2ensite": 'for s; do [ "$s" = -q ] || ln -sf ../sites-available/$s.conf $ROOT/etc/apache2/sites-enabled/$s.conf; done',
    "a2dissite": 'for s; do [ "$s" = -q ] || rm -f $ROOT/etc/apache2/sites-enabled/$s.conf; done',
    "systemctl": '[ "$1" = is-active ] && echo active; exit 0',
    "apt-get": 'echo "Setting up python3-certbot-apache (4.0.0-2) ..."',
    "dpkg-query": 'case "$*" in *cockpit-ws*) [ -d $ROOT/etc/cockpit ] || exit 1 ;; esac; echo "install ok installed"',
    "make-ssl-cert": 'touch $ROOT/etc/ssl/certs/ssl-cert-snakeoil.pem',
    # The appliance's script: a certificate Apple accepts, with the --name given.
    "asl3-self-signed-cert": """
[ -e $ROOT/self-signed-fails ] && { echo "$(cat $ROOT/self-signed-fails)"; exit $(cat $ROOT/self-signed-code); }
san=DNS:node.local,DNS:node
while [ $# -gt 0 ]; do case "$1" in --name) case "$2" in *[!0-9.]*) san="$san,DNS:$2" ;; *) san="$san,IP:$2" ;; esac
  shift ;; esac; shift; done
/usr/bin/openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 -subj /CN=node.local \\
  -addext subjectAltName=$san -addext extendedKeyUsage=serverAuth \\
  -keyout $ROOT/etc/ssl/snakeoil.key -out $ROOT/etc/ssl/certs/ssl-cert-snakeoil.pem 2>/dev/null
echo "Made a new self-signed certificate"
""",
    "certbot": """
[ -e $ROOT/certbot-fails ] && { echo "Challenge failed for domain"; cat $ROOT/certbot-fails; exit 1; }
[ "$1" = certonly ] || exit 0
case " $* " in *" --dry-run "*) echo "The dry run was successful."; exit 0 ;; esac
name=""; server=https://acme-v02.api.letsencrypt.org/directory; names=""
while [ $# -gt 0 ]; do case "$1" in
  --cert-name) name=$2; shift ;; -d) names="$names,DNS:$2"; shift ;;
  --staging) server=https://acme-staging-v02.api.letsencrypt.org/directory ;; esac; shift; done
live=$ROOT/etc/letsencrypt/live/$name; mkdir -p $live $ROOT/etc/letsencrypt/renewal
/usr/bin/openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 90 -subj /CN=$name \\
  -addext subjectAltName=${names#,} -keyout $live/privkey.pem -out $live/cert.pem 2>/dev/null
cp $live/cert.pem $live/fullchain.pem
printf '[renewalparams]\\nserver = %s\\nauthenticator = apache\\nrenew_hook = systemctl reload apache2\\n' $server \\
  > $ROOT/etc/letsencrypt/renewal/$name.conf
echo "Successfully received certificate."
""",
}


@pytest.fixture
def web(env, monkeypatch):  # noqa: F811
    root = env.root
    for d in ("etc/apache2/sites-available", "etc/apache2/sites-enabled", "etc/apache2/mods-available",
              "etc/apache2/mods-enabled", "etc/ssl/certs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "etc/apache2/apache2.conf").write_text("# apache\n")
    for mod in ("ssl", "rewrite"):
        (root / f"etc/apache2/mods-available/{mod}.load").write_text(f"LoadModule {mod}_module x\n")
    (root / "etc/apache2/sites-available/000-default.conf").write_text("<VirtualHost *:80>\n</VirtualHost>\n")
    (root / "etc/apache2/sites-available/default-ssl.conf").write_text("<VirtualHost *:443>\n</VirtualHost>\n")
    (root / "etc/apache2/sites-enabled/000-default.conf").symlink_to("../sites-available/000-default.conf")
    bindir = env.log.parent / "fakebin"
    bindir.mkdir()
    calls = env.log.parent / "calls.log"
    bins = dict(https.BIN)
    for name, body in FAKES.items():
        script = bindir / name
        script.write_text(f'#!/bin/sh\nROOT={root}\necho "{name} $*" >> {calls}\n{body}\n')
        script.chmod(0o755)
        bins[name] = str(script)
    monkeypatch.setattr(https, "BIN", bins)
    env.calls = calls
    env.site = root / "etc/apache2/sites-available/asl-web-ui-https.conf"
    env.enabled = root / "etc/apache2/sites-enabled/asl-web-ui-https.conf"
    return env


ORDER = {"domains": ["Node.Example.org", "hub.example.org"], "email": "op@example.org", "agree_tos": True,
         "redirect": True}


async def test_status_without_https(web):
    a = await web.make()
    status_, body = await a.call("GET", "https")
    assert status_ == 200 and body["apache"] and body["packages"] and body["listening_443"] is False
    assert body["site"] is None and body["timer"] == "active"


async def test_enable_listener(web):
    a = await web.make()
    job = await a.job("POST", "https/listener")
    assert job["ok"] and job["result"]["changed"], job
    assert (web.root / "etc/apache2/sites-enabled/default-ssl.conf").exists()
    assert (web.root / "etc/apache2/mods-enabled/ssl.load").is_symlink()
    assert "systemctl try-reload-or-restart apache2" in web.calls.read_text()
    job = await a.job("POST", "https/listener")
    assert job["result"]["changed"] is False  # already listening


async def test_obtain_certificate_and_site(web):
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert job["ok"], job
    site = web.site.read_text()
    assert "ServerName node.example.org\n    ServerAlias hub.example.org" in site
    assert "RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/" in site
    assert "SSLCertificateFile /etc/letsencrypt/live/node.example.org/fullchain.pem" in site
    assert "Include /etc/letsencrypt/options-ssl-apache.conf" in site
    # Guarded: a certificate deleted behind asl-web-ui's back must not stop Apache.
    assert "<IfFile !/etc/letsencrypt/live/node.example.org/fullchain.pem>" in site
    assert "SSLCertificateFile /etc/ssl/certs/ssl-cert-snakeoil.pem" in site
    assert not (web.root / "etc/asl-web-ui/apache-tls.conf").exists()
    assert web.enabled.exists() and (web.root / "etc/apache2/mods-enabled/rewrite.load").exists()
    certbot = [line for line in web.calls.read_text().splitlines() if line.startswith("certbot certonly")]
    assert certbot == [
        "certbot certonly --apache --non-interactive --agree-tos --cert-name node.example.org "
        "--email op@example.org --no-eff-email --dry-run -d node.example.org -d hub.example.org",
        "certbot certonly --apache --non-interactive --agree-tos --cert-name node.example.org "
        "--email op@example.org --no-eff-email --deploy-hook systemctl reload apache2 "
        "-d node.example.org -d hub.example.org"]
    _, body = await a.call("GET", "https")
    assert body["site"] == {"domains": ["node.example.org", "hub.example.org"], "redirect": True,
                            "cert": "node.example.org"}
    assert body["certificate"]["names"] == ["node.example.org", "hub.example.org"]
    assert body["certificate"]["expires"].endswith("Z") and body["certificate"]["expires"][4] == "-"
    assert body["renewal"]["staging"] is False and body["renewal"]["renew_hook"] == "systemctl reload apache2"


async def test_test_certificate_is_replaced_at_once(web):
    # A test certificate from an earlier version, not due for renewal yet.
    renewal = web.root / "etc/letsencrypt/renewal"
    renewal.mkdir(parents=True)
    (renewal / "node.example.org.conf").write_text(
        "[renewalparams]\nserver = https://acme-staging-v02.api.letsencrypt.org/directory\n")
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    certbot = [line for line in web.calls.read_text().splitlines() if line.startswith("certbot certonly")]
    assert job["ok"] and "--force-renewal" not in certbot[0] and "--force-renewal" in certbot[1]
    _, body = await a.call("GET", "https")
    assert body["renewal"]["staging"] is False


async def test_failed_dry_run_requests_no_certificate(web):
    (web.root / "certbot-fails").touch()
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert not job["ok"] and "test run failed" in job["error"], job
    certbot = [line for line in web.calls.read_text().splitlines() if line.startswith("certbot certonly")]
    assert len(certbot) == 1 and "--dry-run" in certbot[0]


async def test_redirect_toggle_and_remove(web):
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    status_, _ = await a.call("PUT", "https/redirect", {"redirect": False})
    assert status_ == 200 and "RewriteRule" not in web.site.read_text()
    assert "SSLEngine on" in web.site.read_text()
    status_, body = await (await web.make(recent_auth=0)).call("DELETE", "https?delete_certificate=1")
    assert status_ == 403 and body["error"] == "reauth_required"
    status_, _ = await a.call("DELETE", "https?delete_certificate=1")
    assert status_ == 200 and not web.site.exists() and not web.enabled.exists()
    assert "certbot delete --non-interactive --cert-name node.example.org" in web.calls.read_text()
    assert (web.root / "etc/apache2/sites-enabled/000-default.conf").exists()  # others untouched


async def test_certbot_failure_puts_apache_back(web):
    (web.root / "certbot-fails").touch()
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert not job["ok"] and "Apache is as it was" in job["error"]
    assert "port 80 is reachable" in job["error"]
    assert not web.site.exists() and not web.enabled.exists()
    assert not (web.root / "etc/apache2/mods-enabled/rewrite.load").exists()


async def test_certbot_failure_shows_what_lets_encrypt_reported(web):
    (web.root / "certbot-fails").write_text(
        "Certbot failed to authenticate some domains (authenticator: apache). The Certificate Authority "
        "reported these problems:\n"
        "  Domain: node.example.org\n"
        "  Type:   dns\n"
        "  Detail: no valid A records found for node.example.org\n"
        "\n"
        "Hint: The Certificate Authority failed to verify the temporary Apache configuration changes made "
        "by Certbot.\n")
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert not job["ok"]
    assert "Let's Encrypt reported: node.example.org: no valid A records found for node.example.org" in job["error"]
    assert "port 80" not in job["error"]


def test_ca_problems():
    from asl_web_ui_priv.https import ca_problems
    assert ca_problems("  Domain: a.example\n  Type:   dns\n  Detail: no A\n"
                       "  Domain: b.example\n  Type:   connection\n  Detail: timeout\n") == [
        "a.example: no A", "b.example: timeout"]
    assert ca_problems("An unexpected error occurred:\nError creating new order :: too many certificates\n") == [
        "Error creating new order :: too many certificates"]
    assert ca_problems("Some other failure\n") == []


async def test_configtest_failure_puts_apache_back(web):
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    before = web.site.read_text()
    (web.root / "configtest-fails").touch()
    status_, body = await a.call("PUT", "https/redirect", {"redirect": False})
    assert status_ == 500 and "put back" in body["message"]
    assert web.site.read_text() == before


async def test_validation(web):
    a = await web.make()
    for change, field in (({"domains": ["*.example.org"]}, "domains"), ({"domains": ["192.0.2.1"]}, "domains"),
                          ({"domains": ["node.local"]}, "domains"), ({"domains": []}, "domains"),
                          ({"domains": "node.example.org"}, "domains"), ({"email": "not-an-email"}, "email"),
                          ({"agree_tos": False}, "agree_tos")):
        status_, body = await a.call("POST", "https/certificate", {**ORDER, **change})
        assert status_ == 400 and body["field"] == field, (change, body)
    assert not web.site.exists()
    assert https.check_names(["Node.Example.org.", "node.example.org"]) == ["node.example.org"]


async def test_cockpit_not_installed(web):
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert job["ok"] and job["result"]["cockpit"] is False
    assert not (web.root / "etc/cockpit").exists()
    assert not (web.root / "etc/letsencrypt/renewal-hooks").exists()
    _, body = await a.call("GET", "https")
    assert body["cockpit"] == {"installed": False}


async def test_cockpit_gets_the_certificate(web):
    certs = web.root / "etc/cockpit/ws-certs.d"
    certs.mkdir(parents=True)
    (certs / "0-self-signed.cert").write_text("self-signed\n")
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert job["ok"] and job["result"]["cockpit"] is True, job
    live = web.root / "etc/letsencrypt/live/node.example.org"
    assert (certs / "90-asl-web-ui.cert").read_bytes() == (live / "fullchain.pem").read_bytes()
    assert (certs / "90-asl-web-ui.key").read_bytes() == (live / "privkey.pem").read_bytes()
    assert (certs / "90-asl-web-ui.key").stat().st_mode & 0o777 == 0o600
    assert "systemctl try-restart cockpit.service" in web.calls.read_text()
    hook = web.root / "etc/letsencrypt/renewal-hooks/deploy/asl-web-ui-cockpit"
    assert hook.stat().st_mode & 0o111
    assert '[ "$RENEWED_LINEAGE" = "/etc/letsencrypt/live/node.example.org" ] || exit 0' in hook.read_text()
    _, body = await a.call("GET", "https")
    assert body["cockpit"] == {"installed": True, "uses": "90-asl-web-ui.cert", "letsencrypt": True, "hook": True}

    # An administrator's own certificate later in the order wins; the status says so.
    (certs / "99-mine.cert").write_text("mine\n")
    _, body = await a.call("GET", "https")
    assert body["cockpit"]["uses"] == "99-mine.cert" and body["cockpit"]["letsencrypt"] is False
    (certs / "99-mine.cert").unlink()

    status_, _ = await a.call("DELETE", "https")
    assert status_ == 200
    assert not (certs / "90-asl-web-ui.cert").exists() and not (certs / "90-asl-web-ui.key").exists()
    assert not hook.exists() and (certs / "0-self-signed.cert").exists()


async def test_cockpit_installed_later(web):
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    (web.root / "etc/cockpit").mkdir()
    _, body = await a.call("GET", "https")
    assert body["cockpit"] == {"installed": True, "uses": None, "letsencrypt": False, "hook": False}
    status_, body = await a.call("POST", "https/cockpit")
    assert status_ == 200 and body == {"cockpit": True}
    _, body = await a.call("GET", "https")
    assert body["cockpit"]["letsencrypt"] is True


async def test_cockpit_without_certificate(web):
    (web.root / "etc/cockpit").mkdir()
    a = await web.make()
    status_, body = await a.call("POST", "https/cockpit")
    assert status_ == 404 and body["error"] == "not_found"


# ---- external sites (the ASL3 appliance owns Apache's sites) ------------------------------


def external(web, on=True):
    dropin = web.root / "etc/asl-web-ui/conf.d/asl3-appliance.ini"
    if on:
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text("[https]\napache_vhosts = external\n")
    else:
        dropin.unlink()


def test_vhosts_mode(web):
    assert https.vhosts_mode(str(web.root)) == "own"
    external(web)
    assert https.vhosts_mode(str(web.root)) == "external"
    (web.root / "etc/asl-web-ui/conf.d/zz-admin.ini").write_text("[https]\napache_vhosts = own\n")
    assert https.vhosts_mode(str(web.root)) == "own"  # later files win
    (web.root / "etc/asl-web-ui/conf.d/zz-admin.ini").write_text("[https]\napache_vhosts = nonsense\n")
    assert https.vhosts_mode(str(web.root)) == "own"
    (web.root / "etc/asl-web-ui/conf.d/zz-admin.ini").write_text("not an ini file\n")
    assert https.vhosts_mode(str(web.root)) == "own"


async def test_external_obtain_writes_only_the_snippet(web):
    external(web)
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert job["ok"], job
    assert not web.site.exists() and not web.enabled.exists()
    assert not (web.root / "etc/apache2/mods-enabled/rewrite.load").exists()  # no redirect of ours
    assert (web.root / "etc/apache2/mods-enabled/ssl.load").exists()
    snippet = (web.root / "etc/asl-web-ui/apache-tls.conf").read_text()
    assert "<VirtualHost" not in snippet
    assert ("<IfFile /etc/letsencrypt/live/node.example.org/fullchain.pem>\n"
            "    SSLCertificateFile /etc/letsencrypt/live/node.example.org/fullchain.pem\n"
            "    SSLCertificateKeyFile /etc/letsencrypt/live/node.example.org/privkey.pem\n"
            "    Include /etc/letsencrypt/options-ssl-apache.conf\n"
            "</IfFile>\n"
            "<IfFile !/etc/letsencrypt/live/node.example.org/fullchain.pem>\n"
            "    SSLCertificateFile /etc/ssl/certs/ssl-cert-snakeoil.pem\n"
            "    SSLCertificateKeyFile /etc/ssl/private/ssl-cert-snakeoil.key\n"
            "</IfFile>\n") in snippet
    certbot = next(line for line in web.calls.read_text().splitlines() if line.startswith("certbot certonly"))
    assert certbot.startswith("certbot certonly --apache ")
    _, body = await a.call("GET", "https")
    assert body["vhosts"] == "external" and body["site_enabled"] is True
    assert body["site"] == {"domains": ["node.example.org", "hub.example.org"], "redirect": False,
                            "cert": "node.example.org"}


async def test_external_certbot_failure_leaves_apache_alone(web):
    external(web)
    (web.root / "certbot-fails").touch()
    a = await web.make()
    job = await a.job("POST", "https/certificate", ORDER)
    assert not job["ok"] and "Apache is as it was" in job["error"]
    assert not (web.root / "etc/asl-web-ui/apache-tls.conf").exists() and not web.site.exists()
    assert "systemctl try-reload-or-restart apache2" not in web.calls.read_text()


async def test_external_no_redirect_or_listener(web):
    external(web)
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    status_, body = await a.call("PUT", "https/redirect", {"redirect": True})
    assert status_ == 400 and "web server configuration" in body["message"]
    job = await a.job("POST", "https/listener")
    assert job["ok"] and job["result"]["changed"] is False
    assert not (web.root / "etc/apache2/sites-enabled/default-ssl.conf").exists()


async def test_external_remove(web):
    external(web)
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    status_, _ = await a.call("DELETE", "https")
    assert status_ == 200 and not (web.root / "etc/asl-web-ui/apache-tls.conf").exists()
    _, body = await a.call("GET", "https")
    assert body["site"] is None and body["site_enabled"] is False


async def test_sync_moves_the_certificate_both_ways(web):
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    root = str(web.root)
    snippet = web.root / "etc/asl-web-ui/apache-tls.conf"
    assert https.sync(root, print) == {"changed": False}  # own, already in the site

    external(web)  # the appliance is installed
    assert https.sync(root, print) == {"changed": True}
    assert not web.site.exists() and not web.enabled.exists()
    assert "SSLCertificateFile /etc/letsencrypt/live/node.example.org/fullchain.pem" in snippet.read_text()
    assert https.read_site(root) == {"domains": ["node.example.org", "hub.example.org"], "redirect": False,
                                     "cert": "node.example.org"}
    assert https.sync(root, print) == {"changed": False}

    external(web, on=False)  # the appliance is purged
    assert https.sync(root, print) == {"changed": True}
    assert not snippet.exists() and web.enabled.exists()
    site = web.site.read_text()
    assert "<VirtualHost *:443>" in site and "RewriteRule" not in site
    assert https.read_site(root)["cert"] == "node.example.org"


async def test_sync_configtest_failure_puts_apache_back(web):
    a = await web.make()
    await a.job("POST", "https/certificate", ORDER)
    before = web.site.read_text()
    external(web)
    (web.root / "configtest-fails").touch()
    with pytest.raises(https.HttpsError, match="put back"):
        https.sync(str(web.root), print)
    assert web.site.read_text() == before and web.enabled.exists()
    assert not (web.root / "etc/asl-web-ui/apache-tls.conf").exists()


def test_sync_without_apache(tmp_path):
    assert https.sync(str(tmp_path), print) == {"changed": False}


# ---- self-signed certificates Apple can trust (#46) ----------------------------------------


def make_cert(tmp_path, *extra: str, days: int = 825) -> str:
    import subprocess
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    args = []
    for e in extra:
        args += ["-addext", e]
    subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                    "-nodes", "-days", str(days), "-subj", "/CN=node.local", *args, "-keyout", str(key),
                    "-out", str(cert)], check=True, capture_output=True)
    return cert.read_text()


def test_first_boot_certificate_breaks_apples_rules(tmp_path):
    # As asl3-firstboot makes it: the name only in the subject, ten years.
    info = https.cert_info(pem=make_cert(tmp_path, days=3650))
    assert info["self_signed"] and info["names"] == [] and info["lifetime_days"] == 3650
    assert info["apple_problems"] == ["no_san", "no_server_auth", "too_long"]
    assert info["starts"].endswith("Z") and len(info["fingerprint"].split(":")) == 32


def test_certificate_apple_accepts(tmp_path):
    info = https.cert_info(pem=make_cert(tmp_path, "subjectAltName=DNS:node.local,DNS:node,IP:192.0.2.7",
                                         "extendedKeyUsage=serverAuth"))
    assert info["names"] == ["node.local", "node"] and info["ips"] == ["192.0.2.7"]
    assert info["server_auth"] and info["lifetime_days"] == 825 and info["apple_problems"] == []


def test_browser_name():
    assert https.browser_name("Node.Local:8443") == "node.local"
    assert https.browser_name("192.0.2.7") == "192.0.2.7"
    assert https.browser_name("[fd00::1]:443") == "fd00::1"
    assert https.browser_name("bad name;x") is None
    assert https.browser_name("") is None


async def test_renew_self_signed(web):
    a = await web.make()
    _, body = await a.call("GET", "https")
    assert body["self_signed_tool"] is True
    job = await a.job("POST", "https/self-signed")
    assert job["ok"], job
    calls = web.calls.read_text()
    # The name the browser used goes in too; the test client uses an address.
    assert "asl3-self-signed-cert --renew --name 127.0.0.1" in calls
    assert "systemctl try-reload-or-restart apache2" in calls
    cert = job["result"]["certificate"]
    assert cert["names"] == ["node.local", "node"] and cert["ips"] == ["127.0.0.1"] and cert["apple_problems"] == []


async def test_renew_self_signed_refusals(web, monkeypatch):
    a = await web.make()
    (web.root / "self-signed-fails").write_text("/etc/ssl/certs/ssl-cert-snakeoil.pem is not self-signed")
    (web.root / "self-signed-code").write_text("2")
    job = await a.job("POST", "https/self-signed")
    assert not job["ok"] and "not self-signed" in job["error"]
    (web.root / "self-signed-code").write_text("3")
    job = await a.job("POST", "https/self-signed")
    assert not job["ok"] and "could not make the certificate" in job["error"]
    assert "try-reload-or-restart" not in web.calls.read_text()
    # Without the appliance.
    monkeypatch.setitem(https.BIN, "asl3-self-signed-cert", str(web.root / "missing"))
    _, body = await a.call("GET", "https")
    assert body["self_signed_tool"] is False
    job = await a.job("POST", "https/self-signed")
    assert not job["ok"] and "ASL3 appliance" in job["error"]


async def test_download_served_certificate(web, monkeypatch):
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    asked = []
    monkeypatch.setattr(https, "served_pem", lambda name, port=443: asked.append(name) or pem)
    a = await web.make()
    resp = await a.client_.get("/api/v1/https/certificate.crt", headers={"X-Forwarded-Proto": "https"})
    assert resp.status == 401  # not logged in
    status_, body = await a.call("GET", "https/certificate.crt")
    assert status_ == 200 and body.decode() == pem and asked[-1] == "127.0.0.1"
    monkeypatch.setattr(https, "served_pem", lambda name, port=443: None)
    status_, body = await a.call("GET", "https/certificate.crt")
    assert status_ == 404


async def test_system_reports_served_certificate(web, monkeypatch, tmp_path):
    pem = make_cert(tmp_path, days=3650)
    monkeypatch.setattr(https, "served_pem", lambda name, port=443: pem)
    a = await web.make()
    _, body = await a.call("GET", "system")
    assert body["certificate"]["self_signed"] and body["certificate"]["apple_problems"] == [
        "no_san", "no_server_auth", "too_long"]
    monkeypatch.setattr(https, "served_pem", lambda name, port=443: None)
    _, body = await a.call("GET", "system")
    assert body["certificate"] is None
