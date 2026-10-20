from asl_web_ui import VERSION
from asl_web_ui import config
from asl_web_ui.app import create_app


async def test_health(aiohttp_client):
    client = await aiohttp_client(create_app())
    resp = await client.get("/api/v1/health")
    assert resp.status == 200
    assert await resp.json() == {"status": "ok", "version": VERSION}


def test_settings_defaults_when_file_missing(tmp_path):
    assert config.load(tmp_path / "missing.ini") == config.Settings()


def test_settings_from_file(tmp_path):
    ini = tmp_path / "asl-web-ui.ini"
    ini.write_text("[web]\nallow_insecure_http = yes\n[logging]\nlevel = DEBUG\n")
    assert config.load(ini) == config.Settings(allow_insecure_http=True, log_level="debug")


def test_settings_from_conf_d(tmp_path):
    ini = tmp_path / "asl-web-ui.ini"
    ini.write_text("[logging]\nlevel = info\n")
    (tmp_path / "conf.d").mkdir()
    (tmp_path / "conf.d/10-a.ini").write_text("[logging]\nlevel = warning\n")
    (tmp_path / "conf.d/20-b.ini").write_text("[logging]\nlevel = error\n")
    (tmp_path / "conf.d/30-c.conf").write_text("[logging]\nlevel = debug\n")  # not *.ini
    assert config.load(ini).log_level == "error"
