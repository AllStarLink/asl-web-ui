#!/usr/bin/python3
"""Assemble the clickable mockup into one self-contained HTML file.

Inlines PatternFly 6.6.0 CSS (with its asset URLs rewritten to embedded
data: URIs or removed) plus the mockup's own CSS and JS.
"""
import base64
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PF = pathlib.Path(sys.argv[1])          # directory with downloaded PF files
OUT = pathlib.Path(sys.argv[2])


def b64(name):
    return base64.b64encode((PF / name).read_bytes()).decode()


css = (PF / "patternfly.min.css").read_text()

fonts = {
    "Red Hat Text": "RedHatTextVF.woff2",
    "Red Hat Display": "RedHatDisplayVF.woff2",
    "Red Hat Mono": "RedHatMonoVF.woff2",
}


def fix_face(m):
    face = m.group(0)
    if "font-style:italic" in face or "pficon" in face:
        return ""
    for fam, f in fonts.items():
        if f"font-family:{fam};" in face:
            return re.sub(r"url\([^)]*\)", f"url(data:font/woff2;base64,{b64(f)})", face)
    if "fa-solid-900" in face:
        return re.sub(r"url\([^)]*\)", f"url(data:font/woff2;base64,{b64('fa-solid-900.woff2')})", face)
    return ""


css = re.sub(r"@font-face\{[^}]*\}", fix_face, css)
# background images we do not ship
css = re.sub(r'url\("?\./assets/images/[^)]*\)', "none", css)
leftover = re.findall(r"url\((?!data:)[^)]*\)", css)
if leftover:
    sys.exit(f"unresolved asset urls: {leftover[:5]}")

src = (HERE / "mockup.src.html").read_text()
js = (HERE / "mockup.js").read_text()
page = src.replace("/*__PF_CSS__*/", css).replace("/*__APP_JS__*/", js)
OUT.write_text(page)
print(f"wrote {OUT} ({len(page)/1024:.0f} KB)")
