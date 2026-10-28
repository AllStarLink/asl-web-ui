'use strict';
/* ASL Web UI — clickable mockup. Sample data only; nothing here talks to a node. */

/* ===================== theme ===================== */
function applyTheme() {
  const t = document.documentElement.getAttribute('data-theme');
  const dark = t === 'dark' || (t !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('pf-v6-theme-dark', dark);
}
applyTheme();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

/* ===================== helpers ===================== */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ic = (n, c = '') => `<i class="fas fa-${n}${c ? ' ' + c : ''}" aria-hidden="true"></i>`;
const val = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
const checked = (id) => { const el = document.getElementById(id); return !!(el && el.checked); };

function B(text, o = {}) {
  const cls = ['pf-v6-c-button', 'pf-m-' + (o.v || 'secondary')];
  if (o.danger) cls.push('pf-m-danger');
  if (o.sm) cls.push('pf-m-small');
  if (o.inline) cls.push('pf-m-inline');
  if (o.block) cls.push('pf-m-block');
  const attrs = [
    o.act ? `data-act="${o.act}"` : '',
    o.arg != null ? `data-arg="${esc(o.arg)}"` : '',
    o.dis ? 'disabled' : '',
    o.id ? `id="${o.id}"` : '',
    o.aria ? `aria-label="${esc(o.aria)}"` : '',
    o.submit ? '' : '',
  ].join(' ');
  const icon = o.icon ? `<span class="pf-v6-c-button__icon${text ? ' pf-m-start' : ''}">${ic(o.icon)}</span>` : '';
  return `<button type="${o.submit ? 'submit' : 'button'}" class="${cls.join(' ')}" ${attrs}>${icon}${text ? `<span class="pf-v6-c-button__text">${text}</span>` : ''}</button>`;
}
function L(text, color, icon) {
  return `<span class="pf-v6-c-label${color ? ' pf-m-' + color : ''}"><span class="pf-v6-c-label__content">${icon ? `<span class="pf-v6-c-label__icon">${ic(icon)}</span>` : ''}<span class="pf-v6-c-label__text">${text}</span></span></span>`;
}
const AL_ICON = { success: 'check-circle', warning: 'exclamation-triangle', danger: 'exclamation-circle', info: 'info-circle', custom: 'bell' };
function Al(variant, title, desc = '', actions = '', o = {}) {
  return `<div class="pf-v6-c-alert pf-m-${variant}${o.plain ? ' pf-m-plain' : ''}${o.toast ? '' : ' pf-m-inline'}">
    <div class="pf-v6-c-alert__icon">${ic(AL_ICON[variant])}</div>
    <p class="pf-v6-c-alert__title"><span class="pf-v6-screen-reader">${variant} alert:</span>${title}</p>
    ${desc ? `<div class="pf-v6-c-alert__description">${desc}</div>` : ''}
    ${actions ? `<div class="pf-v6-c-alert__action-group">${actions}</div>` : ''}
  </div>`;
}
function Card(title, body, o = {}) {
  return `<div class="pf-v6-c-card">
    <div class="pf-v6-c-card__header"><div class="pf-v6-c-card__header-main"><div class="pf-v6-c-card__title"><h2 class="pf-v6-c-card__title-text">${title}</h2></div></div>${o.actions ? `<div class="pf-v6-c-card__actions">${o.actions}</div>` : ''}</div>
    <div class="pf-v6-c-card__body">${body}</div>
    ${o.footer ? `<div class="pf-v6-c-card__footer">${o.footer}</div>` : ''}
  </div>`;
}
function DL(pairs, o = {}) {
  return `<dl class="pf-v6-c-description-list${o.horiz !== false ? ' pf-m-horizontal' : ''}${o.cls ? ' ' + o.cls : ''}">${pairs.map(([t, d]) => `
    <div class="pf-v6-c-description-list__group"><dt class="pf-v6-c-description-list__term"><span class="pf-v6-c-description-list__text">${t}</span></dt>
    <dd class="pf-v6-c-description-list__description"><div class="pf-v6-c-description-list__text">${d}</div></dd></div>`).join('')}</dl>`;
}
function T(heads, rows, o = {}) {
  return `<div class="table-wrap"><table class="pf-v6-c-table pf-m-grid-md${o.compact ? ' pf-m-compact' : ''}" role="grid" aria-label="${esc(o.label || 'Table')}">
    <thead class="pf-v6-c-table__thead"><tr class="pf-v6-c-table__tr">${heads.map((h) => `<th class="pf-v6-c-table__th" scope="col">${h}</th>`).join('')}</tr></thead>
    <tbody class="pf-v6-c-table__tbody">${rows.map((r) => `<tr class="pf-v6-c-table__tr">${r.map((c, i) => `<td class="pf-v6-c-table__td${heads[i] === '' ? ' pf-v6-c-table__action' : ''}" data-label="${esc(String(heads[i]).replace(/<[^>]*>/g, ''))}">${c}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}
function Tabs(key, items, cur) {
  return `<div class="pf-v6-c-tabs" role="region"><ul class="pf-v6-c-tabs__list" role="tablist">${items.map(([id, label]) => `
    <li class="pf-v6-c-tabs__item${id === cur ? ' pf-m-current' : ''}" role="presentation"><button type="button" class="pf-v6-c-tabs__link" role="tab" aria-selected="${id === cur}" data-act="tab" data-arg="${key}:${id}"><span class="pf-v6-c-tabs__item-text">${label}</span></button></li>`).join('')}
  </ul></div>`;
}
function FG(label, control, helper = '', o = {}) {
  return `<div class="pf-v6-c-form__group">
    ${label ? `<div class="pf-v6-c-form__group-label"><label class="pf-v6-c-form__label" ${o.for ? `for="${o.for}"` : ''}><span class="pf-v6-c-form__label-text">${label}</span>${o.req ? '<span class="pf-v6-c-form__label-required" aria-hidden="true">&#42;</span>' : ''}</label></div>` : ''}
    <div class="pf-v6-c-form__group-control${o.stack ? ' pf-m-stack' : ''}">${control}${helper ? `<div class="pf-v6-c-form__helper-text"><div class="pf-v6-c-helper-text">${helper}</div></div>` : ''}</div>
  </div>`;
}
function HT(text, variant) {
  const iconFor = { error: 'exclamation-circle', warning: 'exclamation-triangle', success: 'check-circle' };
  return `<div class="pf-v6-c-helper-text__item${variant ? ' pf-m-' + variant : ''}">${variant ? `<span class="pf-v6-c-helper-text__item-icon">${ic(iconFor[variant])}</span>` : ''}<span class="pf-v6-c-helper-text__item-text">${text}</span></div>`;
}
function In(id, value = '', o = {}) {
  return `<span class="pf-v6-c-form-control${o.err ? ' pf-m-error' : ''}"><input id="${id}" type="${o.type || 'text'}" value="${esc(value)}" ${o.ph ? `placeholder="${esc(o.ph)}"` : ''} ${o.ac ? `autocomplete="${o.ac}"` : ''} ${o.dis ? 'disabled' : ''} ${o.inputmode ? `inputmode="${o.inputmode}"` : ''} ${o.act ? `data-input="${o.act}"` : ''} spellcheck="false" ${o.mono ? 'class="mono"' : ''}></span>`;
}
function Sel(id, opts, cur, o = {}) {
  return `<span class="pf-v6-c-form-control"><select id="${id}" ${o.act ? `data-change="${o.act}"` : ''}>${opts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${l}</option>`).join('')}</select><span class="pf-v6-c-form-control__utilities"><span class="pf-v6-c-form-control__toggle-icon">${ic('caret-down')}</span></span></span>`;
}
function Chk(id, label, on, desc = '', o = {}) {
  const k = o.radio ? 'radio' : 'check';
  return `<div class="pf-v6-c-${k}"><input class="pf-v6-c-${k}__input" type="${o.radio ? 'radio' : 'checkbox'}" id="${id}" ${o.name ? `name="${o.name}"` : ''} ${o.value != null ? `value="${esc(o.value)}"` : ''} ${on ? 'checked' : ''} ${o.dis ? 'disabled' : ''} ${o.act ? `data-change="${o.act}"` : ''}>
    <label class="pf-v6-c-${k}__label${o.dis ? ' pf-m-disabled' : ''}" for="${id}">${label}</label>${desc ? `<span class="pf-v6-c-${k}__description">${desc}</span>` : ''}</div>`;
}
function Sw(id, label, on, act, o = {}) {
  return `<label class="pf-v6-c-switch" for="${id}"><input class="pf-v6-c-switch__input" type="checkbox" id="${id}" role="switch" ${on ? 'checked' : ''} ${o.dis ? 'disabled' : ''} ${act ? `data-change="${act}"` : ''}><span class="pf-v6-c-switch__toggle"></span><span class="pf-v6-c-switch__label">${label}</span></label>`;
}
const Spinner = (sz = 'md') => `<svg class="pf-v6-c-spinner pf-m-${sz}" role="progressbar" aria-label="Working" viewBox="0 0 100 100"><circle class="pf-v6-c-spinner__path" cx="50" cy="50" r="45" fill="none"></circle></svg>`;
function Empty(icon, title, body, actions = '') {
  return `<div class="pf-v6-c-empty-state"><div class="pf-v6-c-empty-state__content">
    <div class="pf-v6-c-empty-state__icon">${ic(icon)}</div>
    <h2 class="pf-v6-c-empty-state__title-text">${title}</h2>
    <div class="pf-v6-c-empty-state__body">${body}</div>
    ${actions ? `<div class="pf-v6-c-empty-state__footer"><div class="pf-v6-c-empty-state__actions">${actions}</div></div>` : ''}
  </div></div>`;
}
function Breadcrumb(items) {
  return `<nav class="pf-v6-c-breadcrumb" aria-label="breadcrumb"><ol class="pf-v6-c-breadcrumb__list">${items.map(([label, route], i) => `
    <li class="pf-v6-c-breadcrumb__item">${i ? `<span class="pf-v6-c-breadcrumb__item-divider">${ic('angle-right')}</span>` : ''}${route ? `<a href="#${route}" class="pf-v6-c-breadcrumb__link">${label}</a>` : `<span class="pf-v6-c-breadcrumb__link pf-m-current" aria-current="page">${label}</span>`}</li>`).join('')}</ol></nav>`;
}
function Menu(items) {
  return `<div class="pf-v6-c-menu"><div class="pf-v6-c-menu__content"><ul class="pf-v6-c-menu__list" role="menu">${items.map((it) => it === '-' ? '<li class="pf-v6-c-divider" role="separator"></li>' : `
    <li class="pf-v6-c-menu__list-item${it.danger ? ' pf-m-danger' : ''}" role="none"><button type="button" class="pf-v6-c-menu__item" role="menuitem" data-act="${it.act}" ${it.arg != null ? `data-arg="${esc(it.arg)}"` : ''}><span class="pf-v6-c-menu__item-main">${it.icon ? `<span class="pf-v6-c-menu__item-icon">${ic(it.icon)}</span>` : ''}<span class="pf-v6-c-menu__item-text">${it.label}</span></span>${it.desc ? `<span class="pf-v6-c-menu__item-description">${it.desc}</span>` : ''}</button></li>`).join('')}</ul></div></div>`;
}
function Progress(label, pct, o = {}) {
  return `<div class="pf-v6-c-progress pf-m-sm${o.variant ? ' pf-m-' + o.variant : ''}"><div class="pf-v6-c-progress__description">${label}</div><div class="pf-v6-c-progress__status" aria-hidden="true"><span class="pf-v6-c-progress__measure">${pct}%</span></div><div class="pf-v6-c-progress__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="pf-v6-c-progress__indicator" style="width:${pct}%"></div></div></div>`;
}

/* simple line diff (LCS) → [[op, text]] with context collapsed */
function lineDiff(a, b, ctx = 3) {
  const A = a.split('\n'), Bv = b.split('\n'), n = A.length, m = Bv.length;
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === Bv[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) { if (A[i] === Bv[j]) { out.push([' ', A[i], i + 1]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(['-', A[i], i + 1]); i++; } else { out.push(['+', Bv[j], j + 1]); j++; } }
  while (i < n) { out.push(['-', A[i], i + 1]); i++; }
  while (j < m) { out.push(['+', Bv[j], j + 1]); j++; }
  const keep = out.map((l, k) => l[0] !== ' ' || out.slice(Math.max(0, k - ctx), k + ctx + 1).some((x) => x[0] !== ' '));
  const res = []; let skipping = false;
  out.forEach((l, k) => { if (keep[k]) { if (skipping) skipping = false; if (res.length === 0 || !keep[k - 1]) res.push(['@', `@@ line ${l[2]} @@`]); res.push([l[0], l[1]]); } else skipping = true; });
  return res;
}
function DiffView(files) {
  return files.map((f) => {
    const a = f.lines.filter((l) => l[0] === '+').length, d = f.lines.filter((l) => l[0] === '-').length;
    return `<details class="diff-file" open><summary>${ic('file-code')} ${esc(f.path || '/etc/asterisk/' + f.file)}${f.note ? ` <span class="muted">${f.note}</span>` : ''}<span class="diff-stat"><span class="a">+${a}</span> <span class="d">−${d}</span></span></summary>
      <pre class="diff">${f.lines.map(([t, s]) => `<span class="dl ${t === '+' ? 'add' : t === '-' ? 'del' : t === '@' ? 'hunk' : ''}"><span class="sig">${t === '@' ? '' : t}</span>${esc(s)}</span>`).join('')}</pre></details>`;
  }).join('');
}

/* ===================== sample data ===================== */
const NOW = new Date(2026, 9, 13, 14, 20);
const S = {
  authed: false, loginStep: 'password', loginErr: '', route: 'overview',
  tab: { node: 'general', asterisk: 'status', backups: 'local' },
  sim: { restart: true, stopped: false, firstRun: false, rootOwned: true, http: false, mfa: false, portFail: false, rptError: true, tuiRunning: false },
  lastAuth: NOW.getTime() - 3 * 3600e3, keepSignedIn: true,
  navOpen: false, notesOpen: false, menu: null, modal: null, pending: null, toasts: [],
  amiSecret: 'Wq8vR3nTz6Lk', iaxPort: 4569,
  nodes: [
    { num: '63001', call: 'N0CALL', iface: 'SimpleUSB', duplex: 1, linktolink: 'no', statpost: true, pw: 'Xk29fLq7', reg: 'Registered',
      access: { mode: 'deny', list: [{ id: '2000', reason: 'Test node, blocked while debugging' }] },
      customs: ['shari-pixx', 'keyed-gpio4'], needTune: false },
    { num: '1001', call: 'N0CALL', iface: 'Pseudo', duplex: 2, linktolink: 'no', statpost: false, pw: '', reg: 'Private',
      access: { mode: 'open', list: [] }, customs: [], needTune: false },
  ],
  diag: {
    ping: { st: 'ok', sum: '4 of 4 replies, average 18.4 ms', out: 'PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=18.1 ms\n64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=18.9 ms\n64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=18.2 ms\n64 bytes from 8.8.8.8: icmp_seq=4 ttl=117 time=18.4 ms\n\n--- 8.8.8.8 ping statistics ---\n4 packets transmitted, 4 received, 0% packet loss, time 3004ms' },
    regsrv: { st: 'ok', sum: 'register.allstarlink.org is reachable', out: 'Spider mode enabled. Check if remote file exists.\nRemote file exists and could contain further links,\nbut recursion is disabled -- not retrieving.' },
    version: { st: 'ok', sum: 'Asterisk 22.5.2+asl3-3.5.5-1.deb13', out: 'Asterisk 22.5.2+asl3-3.5.5-1.deb13 built by root @ buildhost on a x86_64 running Linux' },
    regs: { st: 'ok', sum: '1 node registered (63001)', out: 'Host                                    Username    Perceived              Refresh  State\n162.248.92.131:443                      63001       203.0.113.24:4569          179  Registered\n1 HTTP registration.\n\nHost                 dnsmgr Username    Perceived             Refresh State\n0 IAX2 registrations.' },
    nodelist: { st: 'ok', sum: 'Timer active · last update 12 minutes ago', out: '● asl3-update-nodelist.timer - Update the AllStarLink node list\n     Loaded: loaded (/usr/lib/systemd/system/asl3-update-nodelist.timer; enabled)\n     Active: active (waiting) since Fri 2026-10-10 09:14:02 EDT; 3 days ago\n    Trigger: Tue 2026-10-13 14:30:00 EDT; 9min left' },
  },
  backups: [
    { name: 'ASL_2026-10-13_1402.tgz', when: 'Oct 13, 2026 14:02', size: '48 KB' },
    { name: 'ASL_2026-10-01_0930.tgz', when: 'Oct 1, 2026 09:30', size: '47 KB' },
    { name: 'ASL_2026-09-12_2210.tgz', when: 'Sep 12, 2026 22:10', size: '45 KB' },
  ],
  cloud: [
    { name: '20261013140212.tgz', when: 'Oct 13, 2026 14:02', size: '48 KB' },
    { name: '20260912221047.tgz', when: 'Sep 12, 2026 22:10', size: '45 KB' },
  ],
  console: [
    ['out', 'Asterisk 22.5.2+asl3-3.5.5-1.deb13, Copyright (C) 1999 - 2025, Sangoma Technologies Corporation and others.\nConnected to Asterisk 22.5.2+asl3-3.5.5-1.deb13 currently running on asl-node (pid = 1187)\nType "help" for a list of commands. Running as user asterisk.'],
  ],
  tune: { rxmixerset: 520, txmixaset: 480, txmixbset: 500, rxboost: false, carrierfrom: 'usbinvert', ctcssfrom: 'usbinvert', tx: false, dirty: false },
  wiz: null, editor: null, nodesMenu: null,
  authcheck: { st: 'done', when: '14:05', raw: false, pct: 0, step: '' },
};
const IFACES = {
  SimpleUSB: { name: 'SimpleUSB', desc: 'USB sound interface (CM1xx) without DSP — URIx, RA-40, most hotspot boards', ch: (n) => `SimpleUSB/${n}`, mod: 'chan_simpleusb', file: 'simpleusb.conf' },
  USBRadio: { name: 'USBRadio', desc: 'USB sound interface (CM1xx) with DSP for tone decoding — URIx, RA-40, AIOC', ch: (n) => `Radio/${n}`, mod: 'chan_usbradio', file: 'usbradio.conf' },
  Voter: { name: 'RTCM / VOTER', desc: 'Radio Thin Client Module or VOTER boards', ch: (n) => `Voter/${n}`, mod: 'chan_voter', file: 'voter.conf' },
  Pseudo: { name: 'No radio (hub)', desc: 'No radio interface — a hub or link-only node (Local/pseudo)', ch: () => 'Local/pseudo', mod: null, file: null },
  USRP: { name: 'USRP', desc: 'USRP protocol to an external program such as DVSwitch', ch: () => 'USRP/127.0.0.1:34001:32001', mod: 'chan_usrp', file: null },
};
const DUPLEX = [
  ['Half or full duplex, no telemetry (link)', 'For a link radio or an external repeater controller. Choose half or full below.'],
  ['Half duplex with telemetry (hotspot)', 'Most hotspots and simplex nodes.'],
  ['Full duplex with telemetry (repeater)', 'Repeater: audio is repeated and telemetry is sent.'],
  ['Full duplex with telemetry, in-cabinet repeat', 'The repeater hardware repeats audio itself.'],
  ['Full duplex with telemetry, no repeat, autopatch', 'Full duplex but received audio is not repeated.'],
];
const duplexLabel = (n) => `${n.duplex} — ${DUPLEX[n.duplex][0]}${n.duplex === 0 ? (n.linktolink === 'yes' ? ' · full' : ' · half') : ''}`;
const CUSTOMS = [
  { id: 'aioc', label: '*AIOC*', kind: 'iface', iface: 'USBRadio', duplex: 1, files: 'rpt.conf, usbradio.conf' },
  { id: 'hotspotradio-pihat', label: '*HotSpotRadio* PiHat', kind: 'iface', iface: 'SimpleUSB', duplex: 1, files: 'rpt.conf, simpleusb.conf' },
  { id: 'hotspotradio-usb', label: '*HotSpotRadio* HSR-USB', kind: 'iface', iface: 'SimpleUSB', duplex: 1, files: 'rpt.conf, simpleusb.conf' },
  { id: 'hotspotradio-repeater', label: '*HotSpotRadio* HSR-Repeater', kind: 'iface', iface: 'SimpleUSB', duplex: 2, files: 'rpt.conf, simpleusb.conf' },
  { id: 'allscan-uci', label: '*AllScan* UCI', kind: 'iface', iface: 'SimpleUSB', duplex: 3, files: 'rpt.conf, simpleusb.conf' },
  { id: 'shari-pihat-pizero', label: '*Kits4Hams* SHARI PiHat, PiZero', kind: 'iface', iface: 'SimpleUSB', duplex: 1, files: 'rpt.conf, simpleusb.conf' },
  { id: 'shari-pixx', label: '*Kits4Hams* SHARI PiXX', kind: 'iface', iface: 'SimpleUSB', duplex: 1, files: 'rpt.conf, simpleusb.conf' },
  { id: 'keyed-gpio4', label: 'Assert GPIO pin 4 when keyed (COS LED)', kind: 'opt', files: 'rpt.conf' },
  { id: 'keyed-gpio8', label: 'Assert GPIO pin 8 when keyed (COS LED)', kind: 'opt', files: 'rpt.conf' },
  { id: 'clip-led-gpio1', label: 'Assert GPIO pin 1 when audio is clipped', kind: 'opt', files: 'simpleusb.conf or usbradio.conf' },
  { id: 'audio-archiving', label: 'Archive audio frames (monitor disk usage)', kind: 'opt', files: 'rpt.conf' },
  { id: 'hd', label: 'Hotspot wait times', kind: 'opt', files: 'rpt.conf' },
  { id: 'SkywarnPlus', label: '-DEMO- SkywarnPlus courtesy tones', kind: 'opt', files: 'rpt.conf' },
  { id: 'keyed-file', label: '-DEMO- Indicate TX activity in filesystem', kind: 'opt', files: 'rpt.conf' },
];
const FILES = [
  ['rpt.conf', 'Nodes, telemetry, functions and macros (app_rpt)'],
  ['rpt_http_registrations.conf', 'Registration with AllStarLink'],
  ['iax.conf', 'IAX2: listening port and node-to-node connections'],
  ['extensions.conf', 'Dialplan'],
  ['modules.conf', 'Which Asterisk modules are loaded'],
  ['manager.conf', 'Asterisk Manager Interface (AMI) accounts'],
  ['echolink.conf', 'EchoLink'],
  ['usbradio.conf', 'USBRadio interfaces'],
  ['simpleusb.conf', 'SimpleUSB interfaces'],
  ['voter.conf', 'RTCM / voter clients'],
  ['savenode.conf', 'Credentials for AllStarLink cloud backups'],
];
const RPT_CONF = `; Radio Repeater configuration file (for use with app_rpt)
;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
; Most per-node settings live in the [node-main] template below and in
; the per-node stanzas at the end of this file.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

[general]
node_lookup_method = both

[node-main](!)
duplex = 1                     ; 0 = half duplex, no telemetry (link)
hangtime = 5000
althangtime = 5000
totime = 180000
idrecording = |iNOTSET
idtime = 540000
politeid = 30000
telemetry = telemetry
morse = morse
functions = functions
events = events
wait_times = wait-times
context = radio
callerid = "Repeater" <0000000>
accountcode = RADIO
macro = macro
scheduler = schedule
controlstates = controlstates

[nodes]
; Only local and private nodes belong here. AllStarLink nodes are
; looked up automatically.
63001 = radio@127.0.0.1/63001,NONE
1001 = radio@127.0.0.1/1001,NONE

[functions-main](!)
1 = ilink,1          ; Disconnect specified link
2 = ilink,2          ; Connect specified link -- monitor only
3 = ilink,3          ; Connect specified link -- transceive
*4 = cop,4           ; Command line remote
*6 = ilink,6         ; Disconnect all links

[telemetry-main](!)
ct1 = |t(350,0,100,2048)(500,0,100,2048)(660,0,100,2048)
ct2 = |t(660,880,150,2048)
remotetx = |t(1633,0,50,0)(0,0,80,0)(1209,0,50,0)

[events-main](!)

[functions](functions-main)

[telemetry](telemetry-main)

#tryinclude "custom/rpt.conf"
#tryinclude "custom/rpt/*.conf"

;;;;;;;;;;;;;;;;;;; Your node settings here ;;;;;;;;;;;;;;;;;;;
[63001](node-main,shari-pixx)
rxchannel = SimpleUSB/63001
duplex = 1
statpost_url = http://stats.allstarlink.org/uhandler
idrecording = |iN0CALL
duplex = 1
events = events-63001

[events-63001](events-main,keyed-gpio4)

[1001](node-main)
rxchannel = Local/pseudo
duplex = 2
idrecording = |iN0CALL
`;
function stubConf(f) {
  return `; ${f} — sample content for the mockup\n;\n; (In the product this is the live file from /etc/asterisk.)\n\n[general]\n; …\n`;
}
const PLANNED = {
  allmon3: { title: 'Allmon3', icon: 'tachometer-alt', body: 'Full management of Allmon3: its node list (allmon3.ini), web settings, menus, and user accounts. Phase 1 already keeps allmon3.ini in sync when a node is renamed or the AMI secret changes.' },
  scheduler: { title: 'Scheduled tasks', icon: 'clock', body: 'Schedule recurring actions, such as connecting to a net every Tuesday at 20:00. Each schedule would be stored with one of three backends: the app_rpt scheduler in rpt.conf, the asterisk user’s crontab, or systemd timers. The choice is still open.' },
  sounds: { title: 'Sound files', icon: 'music', body: 'Upload audio for announcements and IDs. Files are converted to Asterisk formats (8 kHz ulaw/gsm/wav) and stored where app_rpt can play them.' },
};

/* ===================== routing ===================== */
function go(route) { S.navOpen = false; S.menu = null; if (location.hash.slice(1) !== route) location.hash = route; else render(); }
window.addEventListener('hashchange', () => { const r = location.hash.slice(1); if (r) { S.route = r; if (!S.authed) S.authed = true; } stopTimers(); render(); window.scrollTo(0, 0); const m = $('.main'); if (m) m.scrollTop = 0; });
(function init() { const r = location.hash.slice(1); if (r && r !== 'login') { S.route = r; S.authed = true; } })();

/* ===================== timers (tuning meter) ===================== */
let meterTimer = null;
function stopTimers() { if (meterTimer) { clearInterval(meterTimer); meterTimer = null; } }
function startMeter() {
  if (meterTimer || matchMedia('(prefers-reduced-motion: reduce)').matches) { setMeter(0.68); return; }
  let t = 0;
  meterTimer = setInterval(() => {
    t += 0.15;
    const base = S.tune.rxmixerset / 760;
    const v = Math.max(0, Math.min(1, base * (0.75 + 0.25 * Math.sin(t) + 0.12 * Math.sin(t * 3.7)) + (Math.random() - 0.5) * 0.06));
    setMeter(v);
  }, 120);
}
function setMeter(v) { const cos = v > 0.18; if (cos !== S.tune.cos) { S.tune.cos = cos; const ls = $('#live-status'); if (ls) { const lbl = (on) => on ? L('Keyed', 'green', 'circle') : L('Clear', ''); const kids = ls.children; if (kids[0]) kids[0].lastElementChild.outerHTML = lbl(cos); if (kids[2]) kids[2].lastElementChild.outerHTML = lbl(cos); } } const f = $('#rx-meter'); if (f) f.style.width = (v * 100).toFixed(1) + '%'; const o = $('#rx-meter-val'); if (o) o.textContent = Math.round(v * 100); }

/* ===================== toasts / modals / re-auth ===================== */
let toastId = 0;
function toast(variant, title, desc = '') {
  const id = ++toastId; S.toasts.push({ id, variant, title, desc }); renderToasts();
  setTimeout(() => { S.toasts = S.toasts.filter((t) => t.id !== id); renderToasts(); }, 6500);
}
function renderToasts() {
  $('#toasts').innerHTML = S.toasts.map((t) => `<li class="pf-v6-c-alert-group__item">${Al(t.variant, t.title, t.desc ? `<p>${t.desc}</p>` : '', '', { toast: true })}</li>`).join('');
}
function M(title, body, footer, o = {}) {
  return `<div class="pf-v6-c-backdrop"><div class="pf-v6-l-bullseye"><div class="pf-v6-c-modal-box pf-m-${o.size || 'md'}${o.variant ? ' pf-m-' + o.variant : ''}" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="pf-v6-c-modal-box__close">${B('', { v: 'plain', icon: 'times', act: 'closeModal', aria: 'Close' })}</div>
    <header class="pf-v6-c-modal-box__header"><div class="pf-v6-c-modal-box__header-main"><h1 class="pf-v6-c-modal-box__title" id="modal-title">${o.variant ? `<span class="pf-v6-c-modal-box__title-icon">${ic(AL_ICON[o.variant])}</span>` : ''}<span class="pf-v6-c-modal-box__title-text">${title}</span></h1>${o.desc ? `<div class="pf-v6-c-modal-box__description">${o.desc}</div>` : ''}</div></header>
    <div class="pf-v6-c-modal-box__body">${body}</div>
    ${footer ? `<footer class="pf-v6-c-modal-box__footer">${footer}</footer>` : ''}
  </div></div></div>`;
}
function openModal(html, onOpen) { S.modal = html; renderModal(); if (onOpen) onOpen(); else { const f = $('#modal-root input:not([type=hidden]):not([disabled]), #modal-root select, #modal-root textarea'); if (f) f.focus(); } }
function closeModal() { S.modal = null; S.wiz = null; renderModal(); }
function renderModal() { $('#modal-root').innerHTML = S.modal || ''; }
const RELOAD_RE = /^\s*(core reload|module reload(\s+app_rpt(\.so)?)?|rpt restart|core restart\s+(now|gracefully|when convenient))\s*$/i;
const RECENT_MS = 10 * 60e3;
function requireAuth(reason, fn) {
  if (Date.now() - S.lastAuth < RECENT_MS) { fn(); return; }
  S.pending = fn;
  openModal(M('Confirm your password',
    `<form class="pf-v6-c-form" data-submit="reauth" novalidate>
      <p>${reason} This needs your password because you last entered it more than 10 minutes ago.</p>
      ${FG('Password for <b>operator</b>', In('reauth-pw', '', { type: 'password', ac: 'current-password' }), '<div id="reauth-err"></div>', { for: 'reauth-pw' })}
    </form>`,
    B('Confirm', { v: 'primary', act: 'reauth' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm' }));
}
function restartGate() {
  const errs = lintRpt(rptText()).filter((p) => p.sev === 'error');
  if (!errs.length) return false;
  openModal(M(`rpt.conf has ${errs.length} error${errs.length > 1 ? 's' : ''}`,
    `<div class="stack"><p>app_rpt will reject rpt.conf. <b>Restarting now takes all nodes off the air</b> until the file is fixed. Your nodes are still running on the configuration loaded at 09:14.</p>
      <ul class="health-list">${errs.map((p) => `<li><span class="st-fail">${ic('times-circle')}</span><span>Line ${p.line}: ${p.msg}</span></li>`).join('')}</ul></div>`,
    B('Fix in editor', { v: 'primary', act: 'fixRpt', arg: errs[0].line }) + B('Restart anyway', { v: 'secondary', danger: true, act: 'doRestartAnyway' }) + B('Cancel', { v: 'link', act: 'closeModal' }),
    { variant: 'danger' }));
  return true;
}
function needRestart(msg) { S.sim.restart = true; toast('success', msg, 'Restart Asterisk to apply the change.'); render(); }

/* ===================== login ===================== */
const STAR = `<svg viewBox="0 0 24 24" class="brand-mark" aria-hidden="true"><polygon points="12,1.5 14.9,8.4 22.4,8.9 16.6,13.7 18.5,21 12,17 5.5,21 7.4,13.7 1.6,8.9 9.1,8.4" fill="#f5c12e"/></svg>`;
function renderLogin() {
  let form;
  if (S.sim.http) {
    form = Al('danger', 'This connection is not secure',
      `<p>asl-web-ui only accepts logins over HTTPS, so your password is never sent unencrypted.</p>
       <p>Set up TLS in Apache (for example with Let’s Encrypt and certbot), then open <span class="mono">https://asl-node/asl-web-ui/</span>.</p>
       <p class="small">An administrator can allow plain HTTP by setting <span class="mono">allow_insecure_http = yes</span> in <span class="mono">/etc/asl-web-ui/asl-web-ui.ini</span>. This is not recommended.</p>`,
      `<a class="pf-v6-c-button pf-m-link pf-m-inline" href="https://allstarlink.github.io/" target="_blank" rel="noopener"><span class="pf-v6-c-button__text">How to set up HTTPS</span></a>`);
  } else if (S.loginStep === 'mfa') {
    form = `<form class="pf-v6-c-form" data-submit="login" novalidate>
      <p>Signed in as <b>operator</b>. One more step:</p>
      ${FG('Verification code', In('login-code', '', { ac: 'one-time-code', inputmode: 'numeric', ph: '6 digits' }), HT('Prompt text comes from the server’s PAM configuration (here: pam_google_authenticator).'), { for: 'login-code' })}
      <div class="pf-v6-c-form__group pf-m-action"><div class="pf-v6-c-form__actions">${B('Verify', { v: 'primary', act: 'login', block: true })}</div></div>
      ${B('Start over', { v: 'link', inline: true, act: 'loginRestart' })}
    </form>`;
  } else {
    form = `<form class="pf-v6-c-form" data-submit="login" novalidate>
      ${S.loginErr ? Al('danger', S.loginErr) : ''}
      ${FG('User name', In('login-user', 'operator', { ac: 'username' }), '', { for: 'login-user' })}
      ${FG('Password', In('login-pw', '', { type: 'password', ac: 'current-password' }), '', { for: 'login-pw' })}
      ${FG('', Chk('login-keep', 'Keep me signed in', S.keepSignedIn, 'Stay signed in on this browser for up to 30 days. Leave unchecked on shared computers.'))}
      <div class="pf-v6-c-form__group pf-m-action"><div class="pf-v6-c-form__actions">${B('Log in', { v: 'primary', act: 'login', block: true })}</div></div>
    </form>`;
  }
  return `<div class="login-wrap"><div>
    <div class="login-card">
      <div class="login-brand">${STAR}<div><b>AllStarLink</b><span>asl-node · ASL Web UI</span></div></div>
      ${form}
    </div>
    <p class="login-foot">Log in with your Linux account on this server. Your account must be in the <span class="mono">asl-web-ui</span> group.</p>
  </div></div>`;
}

/* ===================== shell ===================== */
const NAV = [
  ['overview', 'Overview', 'tachometer-alt'],
  ['nodes', 'Nodes', 'broadcast-tower'],
  ['asterisk', 'Asterisk', 'asterisk'],
  ['diagnostics', 'Diagnostics', 'stethoscope'],
  ['backups', 'Backups', 'archive'],
];
function routeBase(r) { if (r.startsWith('node-')) return 'nodes'; if (r.startsWith('edit-')) return 'config'; if (r.startsWith('planned-')) return r; return r; }
function navLink(id, label, icon, extra = '') {
  const cur = routeBase(S.route) === id;
  return `<li><button type="button" class="nav-link${cur ? ' current' : ''}${extra.cls ? ' ' + extra.cls : ''}" data-act="nav" data-arg="${id}" ${cur ? 'aria-current="page"' : ''}>${ic(icon)}<span>${label}</span>${extra.badge ? `<span class="nav-badge">${extra.badge}</span>` : ''}</button></li>`;
}
function renderShell(page) {
  const userMenu = S.menu === 'user' ? `<div class="tb-menu">${Menu([{ label: 'Log out', icon: 'sign-out-alt', act: 'logout' }])}</div>` : '';
  const helpMenu = S.menu === 'help' ? `<div class="tb-menu">${Menu([{ label: 'AllStarLink documentation', icon: 'book', act: 'extDocs' }, { label: 'Community forum', icon: 'comments', act: 'extForum' }, '-', { label: 'About ASL Web UI', icon: 'info-circle', act: 'about' }])}</div>` : '';
  const statusBtn = S.sim.stopped
    ? `<button type="button" class="tb-btn danger" data-act="nav" data-arg="asterisk">${ic('times-circle')}<span class="lbl">Asterisk stopped</span></button>`
    : S.sim.restart ? `<button type="button" class="tb-btn warn" data-act="restartAsterisk">${ic('redo')}<span class="lbl">Restart needed</span></button>` : '';
  return `<div class="shell">
    <header class="topbar">
      <button type="button" class="tb-btn hamburger" data-act="toggleNav" aria-label="Menu" aria-expanded="${S.navOpen}">${ic('bars')}</button>
      <a class="brand" href="#overview">${STAR}<span class="brand-text"><b>AllStarLink</b><span>operator@asl-node</span></span></a>
      <span class="spacer"></span>
      ${statusBtn}
      <span class="tb-menu-wrap"><button type="button" class="tb-btn" data-act="menu" data-arg="help" aria-haspopup="menu" aria-expanded="${S.menu === 'help'}">${ic('question-circle')}<span class="lbl">Help</span></button>${helpMenu}</span>
      <span class="tb-menu-wrap"><button type="button" class="tb-btn" data-act="menu" data-arg="user" aria-haspopup="menu" aria-expanded="${S.menu === 'user'}">${ic('user')}<span class="lbl">operator</span>${ic('caret-down')}</button>${userMenu}</span>
    </header>
    <nav class="sidebar${S.navOpen ? ' open' : ''}" aria-label="Main">
      <div class="nav-search">${ic('search')}<input type="search" placeholder="Search" aria-label="Search pages" data-input="navSearch" value="${esc(S.navQ || '')}"></div>
      <ul class="nav-list">${NAV.filter((n) => !S.navQ || n[1].toLowerCase().includes(S.navQ.toLowerCase())).map((n) => navLink(...n)).join('')}</ul>
      <div class="nav-section"><div class="nav-section-title">Advanced</div><ul class="nav-list">${navLink('config', 'Manual Config Edit', 'file-code', { cls: 'caution', badge: 'Expert' })}</ul></div>
      <div class="nav-section"><div class="nav-section-title">Planned · not in phase 1</div><ul class="nav-list">
        ${navLink('planned-allmon3', 'Allmon3', 'tachometer-alt', { cls: 'planned' })}
        ${navLink('planned-scheduler', 'Scheduled tasks', 'clock', { cls: 'planned' })}
        ${navLink('planned-sounds', 'Sound files', 'music', { cls: 'planned' })}
      </ul></div>
    </nav>
    <main class="main" id="main" tabindex="-1">${globalAlerts()}${page}</main>
  </div>`;
}
function globalAlerts() {
  const a = [];
  if (S.rptDown && !S.sim.stopped) a.push(Al('danger', 'app_rpt is disabled: rpt.conf was rejected at startup', '<p>Asterisk is running, but none of your nodes are. Fix the errors in rpt.conf and restart Asterisk.</p>', B('Fix rpt.conf', { v: 'link', inline: true, act: 'nav', arg: 'edit-rpt.conf' })));
  if (S.sim.stopped) a.push(Al('danger', 'Asterisk is not running', '<p>Your nodes are off the air and nothing is registered with AllStarLink.</p>', B('Start Asterisk', { v: 'link', inline: true, act: 'startAsterisk' }) + B('View logs', { v: 'link', inline: true, act: 'nyi', arg: 'Log viewer' })));
  else if (S.sim.restart) a.push(Al('warning', 'Configuration changed since Asterisk started', '<p>rpt.conf and simpleusb.conf were modified after Asterisk started at 09:14. The changes take effect when Asterisk restarts. Restarting disconnects all links on every node for about 10 seconds.</p>', B('Restart Asterisk', { v: 'link', inline: true, act: 'restartAsterisk' }) + B('View changed files', { v: 'link', inline: true, act: 'changedFiles' })));
  return a.length ? `<div class="page-alerts">${a.join('')}</div>` : '';
}
function head(title, desc = '', o = {}) {
  return `<section class="page-head">${o.crumb || ''}<div class="head-row"><div class="grow"><h1>${title}</h1></div>${o.actions ? `<div class="row">${o.actions}</div>` : ''}</div>${desc ? `<p class="desc">${desc}</p>` : ''}${o.labels ? `<div class="row">${o.labels}</div>` : ''}${o.tabs || ''}</section>`;
}

/* ===================== pages ===================== */
function nodes() { return S.sim.firstRun ? [] : S.nodes; }
function regLabel(n) {
  if (S.sim.stopped || S.rptDown) return L('Offline', 'red', 'times-circle');
  if (n.reg === 'Registered') return L('Registered', 'green', 'check-circle');
  if (n.reg === 'Private') return L('Private · not registered', '', 'lock');
  return L(n.reg, 'orange', 'exclamation-triangle');
}
function pageOverview() {
  const ns = nodes();
  const sys = Card('System', DL([
    ['Hostname', 'asl-node'], ['Operating system', 'Debian GNU/Linux 13 (trixie)'],
    ['AllStarLink', 'app_rpt 3.5.5'], ['Asterisk', '22.5.2+asl3-3.5.5-1.deb13'], ['asl-web-ui', '0.1.0'], ['Up since', 'Oct 10, 2026 09:12 (3 days)'],
  ]), { footer: `<div class="row">${B('Reboot', { act: 'reboot', icon: 'redo' })}${B('Shut down', { act: 'shutdown', icon: 'power-off', danger: true })}</div>` });
  const ast = Card('Asterisk', S.sim.stopped
    ? `<div class="stack"><div class="row">${L('Stopped', 'red', 'times-circle')}<span class="muted small">since 14:11</span></div><p class="small muted">Nodes are off the air.</p></div>`
    : `<div class="stack"><div class="row">${L('Running', 'green', 'check-circle')}<span class="muted small">for 3 days, 5 hours</span></div>${S.sim.restart ? `<p class="small"><span class="st-warn">${ic('exclamation-triangle')}</span> Restart needed to apply configuration changes.</p>` : ''}</div>`,
    { footer: `<div class="row">${S.sim.stopped ? B('Start', { v: 'primary', act: 'startAsterisk', icon: 'play' }) : B('Restart', { v: S.sim.restart ? 'primary' : 'secondary', act: 'restartAsterisk', icon: 'redo' }) + B('Stop', { act: 'stopAsterisk', icon: 'stop', danger: true })}${B('Asterisk details', { v: 'link', act: 'nav', arg: 'asterisk' })}</div>` });
  const nodesCard = ns.length
    ? Card('Nodes', ns.map((n) => `<div class="node-mini"><div class="row spread"><div class="row"><b class="num">${n.num}</b><span>${n.call}</span></div>${regLabel(n)}</div><span class="small muted">${IFACES[n.iface].name} · ${DUPLEX[n.duplex][0]}</span></div>`).join(''),
      { footer: `<div class="row">${B('Manage nodes', { v: 'link', act: 'nav', arg: 'nodes' })}${B('Add node', { v: 'link', act: 'addNode', icon: 'plus' })}</div>` })
    : Card('Nodes', Empty('broadcast-tower', 'Set up your first node', '<p>This server has only the template node (1999). Enter the node number and password from your AllStarLink portal account, or use a private number (1000–1999).</p>', B('Set up node', { v: 'primary', act: 'addNode', arg: 'first' })));
  const d = S.diag; const iconFor = { ok: ['check-circle', 'st-ok'], warn: ['exclamation-triangle', 'st-warn'], fail: ['times-circle', 'st-fail'] };
  const h = (st, text, sub) => `<li><span class="${iconFor[st][1]}">${ic(iconFor[st][0])}</span><span>${text}${sub ? `<br><span class="small muted">${sub}</span>` : ''}</span></li>`;
  const health = Card('Health', `<ul class="health-list">
      ${S.sim.stopped ? h('fail', 'Asterisk is not running') : h('ok', 'Asterisk is running')}
      ${S.sim.restart && !S.sim.stopped ? h('warn', 'Restart pending', 'Configuration changed since Asterisk started') : ''}
      ${probCounts(lintRpt(rptText())).e ? h('fail', 'rpt.conf has errors', 'Asterisk would reject it: restarting now would take all nodes off the air') : ''}
      ${ns.length ? h(S.sim.stopped ? 'fail' : 'ok', S.sim.stopped ? 'No nodes registered' : 'Node 63001 is registered', S.sim.stopped ? '' : 'register.allstarlink.org · refresh in 179 s') : h('warn', 'No nodes configured')}
      ${S.sim.portFail ? h('fail', 'Other nodes cannot reach this node', 'Node connectivity check, today at 14:05') : h('ok', 'Other nodes can reach node 63001', 'Node connectivity check, today at 14:05')}
      ${h(d.ping.st, 'Internet reachable', d.ping.sum)}
      ${h(d.nodelist.st, 'Node list is up to date', d.nodelist.sum)}
      ${S.sim.rootOwned ? h('warn', 'voter.conf is owned by root', 'The web UI cannot change it until permissions are fixed') : ''}
    </ul>`, { footer: B('Open diagnostics', { v: 'link', act: 'nav', arg: 'diagnostics' }) });
  return head('asl-node', 'AllStarLink node server overview.') + `<section class="page-body"><div class="cards">${health}${nodesCard}${ast}${sys}</div></section>`;
}

function pageNodes() {
  const ns = nodes();
  const body = ns.length ? Card('', T(['Node', 'Callsign', 'Radio interface', 'Duplex', 'Registration', 'Access', ''],
    ns.map((n) => [
      `<a href="#node-${n.num}" class="num"><b>${n.num}</b></a>`, n.call, IFACES[n.iface].name, `${n.duplex} <span class="muted small">${DUPLEX[n.duplex][0].replace(/ \(.*/, '')}</span>`, regLabel(n),
      n.access.mode === 'open' ? 'Open' : n.access.mode === 'allow' ? `Allow list (${n.access.list.length})` : `Block list (${n.access.list.length})`,
      `<div class="tb-menu-wrap">${B('', { v: 'plain', icon: 'ellipsis-v', act: 'nodeMenu', arg: n.num, aria: `Actions for node ${n.num}` })}${S.nodesMenu === n.num ? `<div class="fixed-menu">${Menu([{ label: 'Open', act: 'nav', arg: 'node-' + n.num }, { label: 'Rename', act: 'renameNode', arg: n.num }, '-', { label: 'Remove node', act: 'removeNode', arg: n.num, danger: true }])}</div>` : ''}</div>`,
    ]), { label: 'Nodes' }))
    : Card('', Empty('broadcast-tower', 'No nodes yet', '<p>Add the node number and password from your AllStarLink portal account, or create a private node.</p>', B('Add node', { v: 'primary', act: 'addNode', arg: 'first' })));
  return head('Nodes', 'AllStar nodes on this server. Changes are written to rpt.conf and the related interface, registration and dialplan files.', { actions: B('Add node', { v: 'primary', act: 'addNode', icon: 'plus' }) }) + `<section class="page-body">${body}</section>`;
}

function pageNode(num) {
  const n = S.nodes.find((x) => x.num === num);
  if (!n || S.sim.firstRun) return head('Node not found') + `<section class="page-body">${Card('', Empty('search', `Node ${esc(num)} is not configured`, '', B('Back to nodes', { act: 'nav', arg: 'nodes' })))}</section>`;
  const tabsList = [['general', 'General'], ['interface', 'Radio interface'], ['tuning', 'Tuning'], ['access', 'Access control'], ['customizations', 'Customizations']];
  const tab = S.tab.node;
  let body = '';
  if (tab === 'general') body = nodeGeneral(n);
  else if (tab === 'interface') body = nodeInterface(n);
  else if (tab === 'tuning') body = nodeTuning(n);
  else if (tab === 'access') body = nodeAccess(n);
  else body = nodeCustoms(n);
  return head(`Node ${n.num}`, '', {
    crumb: Breadcrumb([['Nodes', 'nodes'], [n.num]]),
    labels: `${regLabel(n)}${L(IFACES[n.iface].name, 'blue')}${L(n.call, 'purple')}`,
    actions: B('Remove node', { act: 'removeNode', arg: n.num, danger: true, icon: 'trash' }),
    tabs: Tabs('node', tabsList, tab),
  }) + `<section class="page-body">${body}</section>`;
}
function nodeGeneral(n) {
  const priv = Number(n.num) < 2000;
  const edit = (label, act) => B(label, { v: 'link', inline: true, act, arg: n.num });
  return Card('Node settings', DL([
    ['Node number', `<span class="num"><b>${n.num}</b>${priv ? ' <span class="muted small">(private)</span>' : ''}</span>${edit('Rename', 'renameNode')}`],
    ['Node password', priv ? '<span class="muted">Not used — private nodes do not register</span>' : `<span class="mono" id="pw-${n.num}">••••••••</span>${edit('Show', 'showPw')}${edit('Change', 'changePw')}`],
    ['Callsign', `<span>${n.call}</span>${edit('Change', 'changeCall')}`],
    ['Duplex', `<span>${duplexLabel(n)}</span>${edit('Change', 'changeDuplex')}`],
    ['Status posting', `${Sw('sw-statpost-' + n.num, n.statpost ? 'Posting to stats.allstarlink.org' : 'Off', n.statpost, 'toggleStatpost', { dis: priv })}${priv ? '<span class="small muted">Not available for private nodes.</span>' : ''}`],
  ], { cls: 'edit-dl' }), { footer: '<span class="small muted">Each change is checked against the current file, saved with a snapshot of the previous version, and takes effect when Asterisk restarts.</span>' });
}
function nodeInterface(n) {
  const opts = Object.entries(IFACES).map(([k, v]) => Chk('if-' + k, `<b>${v.name}</b>`, k === n.iface, v.desc, { radio: true, name: 'iface', value: k })).join('');
  const chan = n.iface === 'SimpleUSB'
    ? Card('SimpleUSB channel settings', DL([['Section', '<span class="mono">[63001](node-main,shari-pixx)</span> in simpleusb.conf'], ['USB device', '<span class="mono">1-1.4:1.0</span> (C-Media CM108)'], ['Carrier from', 'usbinvert'], ['CTCSS from', 'usbinvert'], ['Pre/de-emphasis', 'off / off'], ['TX mix A / B', 'voice / no']]), { footer: B('Tune interface', { v: 'link', act: 'tab', arg: 'node:tuning', icon: 'sliders-h' }) })
    : '';
  return `<div class="cards">${Card('Radio interface', `<form class="pf-v6-c-form" novalidate>${FG('', opts, '', { stack: true })}</form>`,
    { footer: `<div class="row">${B('Apply', { v: 'primary', act: 'applyIface', arg: n.num })}<span class="small muted">Shows the file changes before anything is written.</span></div>` })}${chan}</div>`;
}
function nodeTuning(n) {
  if (!['SimpleUSB', 'USBRadio'].includes(n.iface)) return Card('', Empty('sliders-h', n.iface === 'Pseudo' ? 'No tuning needed' : `Tuning ${IFACES[n.iface].name} is not supported here`, n.iface === 'Pseudo' ? '<p>This node has no radio interface.</p>' : '<p>Use Manual Config Edit for this interface type.</p>'));
  const t = S.tune;
  const slider = (id, label, v, help) => `<div class="slider-row"><label for="${id}">${label}<br><span class="small muted">${help}</span></label><input type="range" id="${id}" min="0" max="999" value="${v}" data-input="tune"><output for="${id}" id="${id}-out">${v}</output></div>`;
  const lock = S.sim.tuiRunning
    ? Al('warning', 'simpleusb-tune-menu is running in an SSH session', '<p>Process 4321, started by <b>pi</b> at 14:02. Both tools change the same driver settings, so tuning here could overwrite changes made there.</p>', B('Take over tuning', { v: 'link', inline: true, act: 'takeOver' }))
    : Al('info', `You are tuning node ${n.num} · SimpleUSB device 1-1.4:1.0`, '<p>Other web sessions cannot tune SimpleUSB interfaces until you leave this tab.</p>', '', { plain: true });
  const st = (label, on, off) => `<div class="stack" style="gap:.25rem;justify-items:start"><span class="small muted">${label}</span>${on ? L('Keyed', 'green', 'circle') : L(off || 'Clear', '')}</div>`;
  const live = Card('Live status', `<div class="row" style="gap:1.5rem" id="live-status">${st('COS input', S.tune.cos)}${st('CTCSS input', false, t.ctcssfrom === 'no' ? 'Off' : 'Clear')}${st('COS to app_rpt', S.tune.cos)}${st('PTT output', t.tx)}</div>`);
  return `${lock}${S.sim.restart ? Al('info', 'Interface changes are pending a restart', '<p>Tuning talks to the running channel driver. If you just changed the interface type, restart Asterisk first.</p>') : ''}
  ${live}
  <div class="cards">
    ${Card('Receive', `<div class="stack">
      <p class="small muted">Transmit a steady signal into the node’s receiver, then adjust the RX level so the peaks reach the marker.</p>
      <div><div class="row spread small"><b>RX audio level</b><span class="num"><span id="rx-meter-val">0</span> / 100</span></div>
        <div class="meter" aria-hidden="true"><div class="fill" id="rx-meter" style="width:0%"></div><div class="target"></div></div>
        <div class="meter-scale"><span>0</span><span>target</span><span>clip</span></div></div>
      ${slider('rxmixerset', 'RX level (rxmixerset)', t.rxmixerset, 'Receive audio gain, 0–999')}
      <div class="row">${Sw('sw-rxboost', 'RX boost (+20 dB)', t.rxboost, 'tuneFlag')}</div>
    </div>`)}
    ${Card('Transmit', `<div class="stack">
      ${slider('txmixaset', 'TX level A (txmixaset)', t.txmixaset, 'Left channel transmit audio')}
      ${slider('txmixbset', 'TX level B (txmixbset)', t.txmixbset, 'Right channel transmit audio')}
      <div class="row">${t.tx ? `<span class="tx-live">${ic('circle')} Transmitting test tone</span>${B('Stop', { v: 'primary', danger: true, act: 'txTone' })}` : B('Send test tone', { act: 'txTone', icon: 'broadcast-tower' })}<span class="small muted">Keys the transmitter for up to 30 seconds.</span></div>
    </div>`)}
    ${Card('Signaling', `<form class="pf-v6-c-form" novalidate>
      ${FG('Carrier detect from', Sel('carrierfrom', [['no', 'None'], ['usb', 'USB input'], ['usbinvert', 'USB input, inverted'], ['dsp', 'Noise squelch (DSP)']], t.carrierfrom, { act: 'tuneFlag' }), '', { for: 'carrierfrom' })}
      ${FG('CTCSS detect from', Sel('ctcssfrom', [['no', 'None'], ['usb', 'USB input'], ['usbinvert', 'USB input, inverted']], t.ctcssfrom, { act: 'tuneFlag' }), '', { for: 'ctcssfrom' })}
    </form>`)}
  </div>
  <div class="row spread"><div class="row" id="tune-bar">${tuneBar()}</div>${B('Open classic tune menu', { v: 'link', icon: 'terminal', act: 'classicTune' })}</div>`;
}
function tuneBar() {
  const t = S.tune;
  return `${B('Save to simpleusb.conf', { v: 'primary', act: 'tuneSave', dis: !t.dirty })}${B('Revert', { v: 'link', act: 'tuneRevert', dis: !t.dirty })}<span class="small muted">${t.dirty ? 'Changes are live on the radio but not saved yet.' : 'Saved settings match the running driver.'}</span>`;
}
function nodeAccess(n) {
  const a = n.access;
  const modeOpts = [['open', 'Open', 'Any node may connect.'], ['allow', 'Allow only listed nodes', 'Only the nodes or callsigns below may connect.'], ['deny', 'Block listed nodes', 'All nodes may connect except those below.']];
  const locked = a.list.length > 0;
  const modes = modeOpts.map(([k, l, d]) => Chk('acc-' + k, l, a.mode === k, d, { radio: true, name: 'accmode', value: k, act: 'accMode', dis: locked && a.mode !== k })).join('');
  const listName = a.mode === 'allow' ? 'Allowed' : 'Blocked';
  return Card('Who can connect to node ' + n.num, `<div class="stack">
      <form class="pf-v6-c-form" novalidate>${FG('', modes, locked ? HT(`To switch modes, remove all ${listName.toLowerCase()} entries first. Only one list can be active.`) : '', { stack: true })}</form>
      ${a.mode === 'open' ? '' : `
        ${a.list.length ? T(['Node or callsign', 'Reason', ''], a.list.map((e, i) => [`<b class="num">${esc(e.id)}</b>`, e.reason ? esc(e.reason) : '<span class="muted">—</span>', B('Remove', { v: 'link', inline: true, act: 'accRemove', arg: `${n.num}:${i}` })]), { label: listName, compact: true }) : `<p class="muted">No ${listName.toLowerCase()} nodes yet.</p>`}
        <form class="pf-v6-c-form" data-submit="accAdd" novalidate><div class="row" style="align-items:flex-end">
          <div style="flex:0 1 12rem">${FG('Node or callsign', In('acc-id', '', { ph: 'e.g. 2000 or W1XYZ' }), '', { for: 'acc-id' })}</div>
          <div style="flex:1 1 16rem">${FG('Reason (optional)', In('acc-reason', ''), '', { for: 'acc-reason' })}</div>
          ${B('Add', { act: 'accAdd', arg: n.num, icon: 'plus' })}
        </div><div id="acc-err"></div></form>
        ${a.list.length > 1 ? B(`Remove all ${listName.toLowerCase()}`, { v: 'link', inline: true, danger: true, act: 'accClear', arg: n.num }) : ''}`}
    </div>`, { footer: '<span class="small muted">Stored in the Asterisk database (allowlist/denylist). Takes effect immediately, without a restart.</span>' });
}
function nodeCustoms(n) {
  const ifaceOnes = CUSTOMS.filter((c) => c.kind === 'iface' && c.iface === n.iface);
  const opts = CUSTOMS.filter((c) => c.kind === 'opt');
  if (n.iface === 'Pseudo') return Card('', Empty('puzzle-piece', 'No customizations for hub nodes', '<p>Customizations apply to radio interfaces.</p>'));
  return Card('Customizations', `<form class="pf-v6-c-form" novalidate>
      <p class="small muted">Customizations are ready-made settings shipped in /etc/asterisk/custom. Selecting one adds it to the node’s template list, for example <span class="mono">[63001](node-main,shari-pixx)</span>.</p>
      ${FG('Interface hardware (choose one)', Chk('cu-none', 'None', !n.customs.some((c) => ifaceOnes.find((x) => x.id === c)), '', { radio: true, name: 'cu-iface', value: '' }) + ifaceOnes.map((c) => Chk('cu-' + c.id, c.label, n.customs.includes(c.id), `Sets ${c.files} · duplex ${c.duplex}`, { radio: true, name: 'cu-iface', value: c.id })).join(''), '', { stack: true })}
      ${FG('Options', opts.map((c) => Chk('cu-' + c.id, c.label, n.customs.includes(c.id), c.files)).join(''), '', { stack: true })}
    </form>`, { footer: `<div class="row">${B('Review changes', { v: 'primary', act: 'applyCustoms', arg: n.num })}</div>` });
}

function pageAsterisk() {
  const tab = S.tab.asterisk;
  let body;
  if (tab === 'status') {
    body = `<div class="cards">${Card('Service', `<div class="stack">${DL([['Status', S.sim.stopped ? L('Stopped', 'red', 'times-circle') : L('Running', 'green', 'check-circle')], ['Started', S.sim.stopped ? '—' : 'Oct 10, 2026 09:14 (3 days, 5 hours)'], ['Version', '22.5.2+asl3-3.5.5-1.deb13'], ['Service', '<span class="mono">asterisk.service</span>']])}</div>`,
      { footer: `<div class="row">${S.sim.stopped ? B('Start', { v: 'primary', act: 'startAsterisk', icon: 'play' }) : B('Restart', { act: 'restartAsterisk', icon: 'redo' }) + B('Stop', { act: 'stopAsterisk', icon: 'stop', danger: true })}</div>` })}
      ${Card('Registrations', S.sim.stopped ? '<p class="muted">Asterisk is not running.</p>' : `<div class="stack"><h3 class="small">AllStarLink (HTTP)</h3>${T(['Node', 'Server', 'Your address', 'Refresh', 'State'], [['<b>63001</b>', '162.248.92.131:443', '203.0.113.24:4569', '179 s', L('Registered', 'green', 'check-circle')]], { compact: true, label: 'HTTP registrations' })}<h3 class="small">IAX2</h3><p class="muted small">No IAX2 registrations. ASL3 registers over HTTP.</p></div>`, { actions: B('', { v: 'plain', icon: 'sync', act: 'refreshRegs', aria: 'Refresh' }) })}</div>`;
  } else if (tab === 'settings') {
    body = `<div class="cards">${Card('Manager interface (AMI)', `<div class="stack">${DL([['AMI user', '<span class="mono">admin</span>'], ['Secret', `<span class="mono" id="ami-secret">••••••••••••</span>${B('Show', { v: 'link', inline: true, act: 'showAmi' })}`]])}<p class="small muted">Allmon3, Supermon and other tools use this secret to monitor and control your nodes.</p></div>`, { footer: B('Change secret', { act: 'changeAmi' }) })}
      ${Card('IAX port', `<div class="stack">${DL([['UDP port', `<span class="num">${S.iaxPort}</span>${S.iaxPort === 4569 ? ' <span class="muted small">(default)</span>' : ''}`]])}<p class="small muted">Other nodes connect to yours on this port. Your router must forward it to this server.</p></div>`, { footer: B('Change port', { act: 'changePort' }) })}</div>`;
  } else {
    body = Card('Asterisk console', `<div class="stack"><div class="term" id="term" role="log" aria-live="polite">${S.console.map(([k, t]) => k === 'in' ? `<span class="prompt">asl-node*CLI&gt; </span>${esc(t)}\n` : k === 'err' ? `<span class="err">${esc(t)}</span>\n` : esc(t) + '\n').join('')}<form class="term-input" data-submit="cli"><span class="prompt">asl-node*CLI&gt;</span><input id="cli-in" autocomplete="off" spellcheck="false" aria-label="Asterisk command" placeholder="try: rpt show registrations"></form></div><p class="small muted">Equivalent to <span class="mono">asterisk -r</span>, running as the asterisk user. There is no system shell in the web UI.</p></div>`);
  }
  return head('Asterisk', 'The Asterisk service that runs app_rpt and your nodes.', { tabs: Tabs('asterisk', [['status', 'Status'], ['settings', 'Settings'], ['console', 'Console']], tab) }) + `<section class="page-body">${body}</section>`;
}

const DIAGS = [
  ['ping', 'Internet connectivity', 'Pings 8.8.8.8 four times.'],
  ['version', 'Asterisk version', '<span class="mono">core show version</span>'],
  ['nodelist', 'Node list updates', 'Status of the <span class="mono">asl3-update-nodelist</span> service and timer.'],
];
/* asl-node-auth-check results, as its proposed --json output would describe them */
function authResults() {
  const pf = S.sim.portFail, down = S.sim.stopped;
  const r = (lvl, msg, hint) => ({ lvl, msg, hint });
  const groups = [
    { title: 'Configuration', items: [
      r('ok', 'rpt.conf configures node 63001'),
      r('info', 'Private node 1001 is skipped: private nodes do not register'),
      r('ok', 'Registration found for 63001 in rpt_http_registrations.conf (HTTP)'),
    ] },
    { title: 'Your public address', items: [
      r('ok', 'All 3 HTTP probes see 203.0.113.24'),
      r('ok', 'All 3 IAX (UDP) probes see 203.0.113.24'),
    ] },
  ];
  const node = { title: 'Node 63001', items: [r('ok', 'Registration settings are well-formed'), r('ok', 'register.allstarlink.org is reachable over HTTPS')] };
  if (down) {
    node.items.push(r('error', 'No HTTP registration attempt for node 63001', 'Asterisk is not running. Start Asterisk, wait a minute, and run the check again.'));
    node.items.push(r('info', 'Further node checks skipped: results would be unreliable without a registration'));
  } else {
    node.items.push(
      r('ok', 'HTTP registration state is Registered'),
      r('ok', 'Other nodes see this server at 203.0.113.24:4569'),
      r('ok', 'Registered to reg-east.allstarlink.org (162.248.92.131)'),
      pf ? r('error', 'Registered UDP port 4570 does not match bindport 4569 in iax.conf', 'This can be fine if your router forwards external port 4570 to internal 4569. The inbound connection test below shows whether it works.') : r('ok', 'Registered UDP port matches bindport 4569 in iax.conf'),
      r('ok', 'Registered within the last 10 minutes (2026-10-13 18:17:42 UTC)'),
      r('info', 'Public IP last changed 2026-09-30 04:12 UTC'),
      pf ? r('error', 'Other nodes cannot connect to this node over IAX', 'Forward UDP port 4569 on your router to this server, and allow it through any firewall. Then run the check again.') : r('ok', 'Other nodes can connect to this node over IAX (round trip 42 ms)'),
    );
  }
  groups.push(node);
  return groups;
}
function authCheckCard() {
  const a = S.authcheck;
  const icons = { ok: ['check-circle', 'st-ok'], info: ['info-circle', 'st-info'], warning: ['exclamation-triangle', 'st-warn'], error: ['times-circle', 'st-fail'] };
  let body;
  if (a.st === 'run') {
    body = `<div class="stack"><div class="row">${Spinner('md')}<span>${a.step}</span></div>${Progress('Node connectivity check', a.pct)}</div>`;
  } else {
    const groups = authResults();
    const all = groups.flatMap((g) => g.items);
    const errs = all.filter((i) => i.lvl === 'error').length, warns = all.filter((i) => i.lvl === 'warning').length;
    const summary = errs ? L(`${errs} error${errs > 1 ? 's' : ''}`, 'red', 'times-circle') : warns ? L(`${warns} warning${warns > 1 ? 's' : ''}`, 'orange', 'exclamation-triangle') : L('No problems found', 'green', 'check-circle');
    body = `<div class="stack"><div class="row">${summary}<span class="small muted">Last run today at ${a.when}</span></div>
      ${groups.map((g) => `<div><h3 class="small" style="margin:.25rem 0 .5rem">${g.title}</h3><ul class="health-list">${g.items.map((i) => `<li><span class="${icons[i.lvl][1]}">${ic(icons[i.lvl][0])}</span><span>${i.msg}${i.hint ? `<br><span class="small muted">${i.hint}</span>` : ''}</span></li>`).join('')}</ul></div>`).join('')}
      ${a.raw ? `<pre class="pf-v6-c-code-block__pre small mono" style="white-space:pre-wrap">${esc(authRaw())}</pre>` : ''}</div>`;
  }
  return Card('Node connectivity check', `<div class="stack"><p class="small muted">Runs <span class="mono">asl-node-auth-check</span>. It checks your registrations, how the internet sees your address, port forwarding, and whether other nodes can reach yours. It takes about 30 seconds and contacts AllStarLink servers.</p>${body}</div>`,
    { actions: B('Run check', { v: 'primary', act: 'runAuth', icon: 'play', dis: a.st === 'run' }), footer: a.st === 'run' ? '' : B(a.raw ? 'Hide raw output' : 'Show raw output', { v: 'link', act: 'authRaw' }) });
}
function authRaw() {
  const lvl = { ok: 'OK', info: 'Info', warning: 'Warning', error: 'Error' };
  return '-----===== AllStarLink Node Authentication Check =====-----\n\n' + authResults().map((g) => `${g.title}:\n` + g.items.map((i) => `${lvl[i.lvl].padStart(10)}: ${i.msg.replace(/<[^>]*>/g, '')}`).join('\n')).join('\n\n');
}
function pageDiagnostics() {
  const st = { ok: L('Passed', 'green', 'check-circle'), warn: L('Warning', 'orange', 'exclamation-triangle'), fail: L('Failed', 'red', 'times-circle'), run: `<span class="row">${Spinner('sm')} Running…</span>` };
  const rows = DIAGS.map(([id, name, what]) => {
    const d = S.diag[id];
    return [`<b>${name}</b><br><span class="small muted">${what}</span>`, st[d.st], `<span class="small">${d.st === 'run' ? '' : d.sum}</span>${d.open && d.st !== 'run' ? `<pre class="pf-v6-c-code-block__pre small mono" style="white-space:pre-wrap;margin-top:.5rem">${esc(d.out)}</pre>` : ''}`,
      `<div class="row">${B('Run', { sm: true, act: 'runDiag', arg: id, dis: d.st === 'run' })}${B(d.open ? 'Hide output' : 'Output', { v: 'link', sm: true, act: 'diagOut', arg: id })}${id === 'nodelist' ? B('Restart service', { v: 'link', sm: true, act: 'restartNodelist' }) : ''}</div>`];
  });
  return head('Diagnostics', 'Checks for the most common reasons a node is not working.', { actions: B('Run all checks', { v: 'secondary', act: 'runAll', icon: 'play' }) }) + `<section class="page-body">${authCheckCard()}${Card('Basic checks', T(['Check', 'Result', 'Details', 'Actions'], rows, { label: 'Basic checks' }))}</section>`;
}

function pageBackups() {
  const tab = S.tab.backups;
  let body;
  if (tab === 'local') {
    body = Card('Backups on this server', `<div class="stack"><p class="small muted">Stored in <span class="mono">/var/asl-backups</span>. A backup holds every path listed under Settings, including /etc/asterisk and the Asterisk database.</p>${T(['Backup', 'Created', 'Size', ''], S.backups.map((b) => [`<span class="mono">${b.name}</span>`, b.when, b.size, `<div class="row">${B('Restore', { sm: true, act: 'restoreLocal', arg: b.name })}${B('Download', { v: 'link', sm: true, act: 'nyi', arg: 'Download' })}${B('Delete', { v: 'link', sm: true, danger: true, act: 'deleteBackup', arg: b.name })}</div>`]), { label: 'Local backups' })}</div>`,
      { actions: `<div class="row">${B('Upload backup', { v: 'secondary', icon: 'upload', act: 'uploadBackup' })}${B('Create backup', { v: 'primary', icon: 'plus', act: 'createBackup' })}</div>` });
  } else if (tab === 'cloud') {
    body = Card('Backups on backup.allstarlink.org', `<div class="stack">${Al('info', 'Using node 63001’s credentials from savenode.conf', '', B('Use different credentials', { v: 'link', inline: true, act: 'cloudCreds' }), { plain: true })}${T(['Backup', 'Created', 'Size', ''], S.cloud.map((b) => [`<span class="mono">${b.name}</span>`, b.when, b.size, B('Restore', { sm: true, act: 'restoreCloud', arg: b.name })]), { label: 'Cloud backups' })}<p class="small muted">Uploads are limited to 2 MB. Cloud backups are available only for registered nodes (2000 and above, not starting with 1).</p></div>`);
  } else {
    body = `<div class="stack">${Card('Files included in backups', `<div class="stack"><p class="small muted">One path per line. Lines starting with # are ignored. Stored in <span class="mono">/var/asl-backups/asl-backup-files</span>.</p><div class="editor" style="height:18rem"><div class="gutter">${Array.from({ length: 22 }, (_, i) => i + 1).join('\n')}</div><textarea aria-label="Backup include list" spellcheck="false">#\n# Paths included in ASL backups\n#\n/etc/asterisk\n\n# Asterisk database (node access lists)\n/var/lib/asterisk/astdb.sqlite3\n\n/var/asl-backups/asl-backup-files\n\n# SA818 radio module\n/etc/sa818.conf\n\n# Allmon3\n/etc/allmon3/allmon3.ini\n/etc/allmon3/custom.css\n/etc/allmon3/menu.ini\n/etc/allmon3/user-restrictions\n/etc/allmon3/users\n/etc/allmon3/web.ini\n\n# Add other configuration files below</textarea></div></div>`, { footer: B('Save', { v: 'primary', act: 'nyi', arg: 'Save include list' }) })}
      ${Card('Danger zone', `<div class="danger-zone"><h3>Restore the ASL3 default configuration</h3><p class="small">Reinstalls the asl3-asterisk-config package, overwriting every .conf file in /etc/asterisk with the defaults. Your nodes, registrations and customizations are lost; the AMI secret is kept. A backup is created first.</p><div>${B('Restore defaults…', { danger: true, v: 'primary', act: 'factoryReset' })}</div></div>`)}</div>`;
  }
  return head('Backups', 'Save and restore your node configuration.', { tabs: Tabs('backups', [['local', 'This server'], ['cloud', 'AllStarLink cloud'], ['settings', 'Settings']], tab) }) + `<section class="page-body">${body}</section>`;
}

function pageConfig() {
  const rows = FILES.map(([f, what]) => {
    const root = S.sim.rootOwned && f === 'voter.conf';
    const probs = f === 'rpt.conf' ? lintRpt(rptText()) : [];
    return [`<a href="#edit-${f}" class="mono"><b>${f}</b></a>`, `<span class="small">${what}</span>`, f === 'rpt.conf' ? 'Today 14:02' : f === 'simpleusb.conf' ? 'Today 14:02' : 'Oct 1 09:30',
      root ? `${L('root', 'orange', 'exclamation-triangle')}` : '<span class="mono small">asterisk</span>',
      root ? B('Fix permissions', { v: 'link', inline: true, act: 'fixPerms' }) : `<span class="row">${probLabels(probs)}</span>`];
  });
  return head('Manual Config Edit', '', { actions: '' }) + `<section class="page-body">
    ${Al('danger', 'For experienced users only', `<p>These are the raw Asterisk and app_rpt configuration files. A mistake here can take your node off the air or stop Asterisk from starting.</p><p>Almost everything can be changed safely on the <a href="#nodes">Nodes</a>, <a href="#asterisk">Asterisk</a> and <a href="#backups">Backups</a> pages. If you continue, <b>create a backup first</b>. Every save also keeps a snapshot of the previous version.</p>`, B('Create backup now', { v: 'link', inline: true, act: 'createBackup' }))}
    ${Card('Configuration files in /etc/asterisk', T(['File', 'Contains', 'Modified', 'Owner', 'Status'], rows, { label: 'Configuration files' }))}
  </section>`;
}
function pageEdit(file) {
  if (!S.editor || S.editor.file !== file) { const text = file === 'rpt.conf' ? rptConf() : stubConf(file); S.editor = { file, orig: text, text }; }
  const ed = S.editor;
  const lines = ed.text.split('\n');
  const probs = file === 'rpt.conf' ? lintRpt(ed.text) : [];
  const sevAt = {}; probs.forEach((p) => { if (sevAt[p.line] !== 'error') sevAt[p.line] = p.sev; });
  const dirty = ed.text !== ed.orig;
  const readonly = S.sim.rootOwned && file === 'voter.conf';
  return head(file, '', { crumb: Breadcrumb([['Manual Config Edit', 'config'], [file]]) }) + `<section class="page-body">
    ${readonly ? Al('warning', 'voter.conf is owned by root, so the web UI cannot save it', '<p>This usually happens when the file was edited with <span class="mono">sudo</span>. Fix permissions to return ownership to the asterisk user.</p>', B('Fix permissions', { v: 'link', inline: true, act: 'fixPerms' })) : ''}
    <div class="editor-bar"><span class="file">/etc/asterisk/${file}</span>${dirty ? L('Unsaved changes', 'orange') : ''}<span class="spacer" style="flex:1"></span>${B('Revert', { v: 'link', act: 'edRevert', dis: !dirty })}${B('Download', { v: 'secondary', icon: 'download', act: 'nyi', arg: 'Download' })}${B('Save…', { v: 'primary', act: 'edSave', dis: !dirty || readonly })}</div>
    <div class="editor"><div class="gutter" id="ed-gutter">${lines.map((_, i) => sevAt[i + 1] ? `<span class="bad ${sevAt[i + 1]}">${sevAt[i + 1] === 'error' ? '✖' : '▲'}${i + 1}</span>` : i + 1).join('\n')}</div><textarea id="ed-text" data-input="edText" aria-label="Contents of ${file}" spellcheck="false" ${readonly ? 'readonly' : ''}>${esc(ed.text)}</textarea></div>
    <div class="problems"><h3 class="row">${probs.length ? probLabels(probs) : `${ic('check-circle', 'st-ok')} No problems found`}</h3>${probs.length ? `<ul>${probs.map((p) => `<li><span class="${p.sev === 'error' ? 'st-fail' : 'st-warn'}">${ic(p.sev === 'error' ? 'times-circle' : 'exclamation-triangle')}</span>${B('Line ' + p.line, { v: 'link', inline: true, act: 'edGoto', arg: p.line })}<span style="flex:1 1 20rem;min-width:0">${p.msg}<br><span class="small muted">${p.why}</span></span></li>`).join('')}</ul>` : ''}</div>
    <p class="small muted">The product uses the CodeMirror 6 editor here, with syntax highlighting, search, and problem markers in the gutter.</p>
  </section>`;
}
function rptConf() { return RPT_CONF.replace('[1001](node-main)', S.sim.rptError ? '[1001](node-mian)' : '[1001](node-main)'); }
function rptText() { return S.editor && S.editor.file === 'rpt.conf' ? S.editor.text : rptConf(); }
const MULTI = new Set(['register', 'load', 'noload', 'preload', 'require', 'exten', 'include', 'allow', 'disallow']);
const WHY_REJECT = (loc) => `Asterisk rejects the entire file at this line (main/${loc}). The next time app_rpt loads rpt.conf it disables every node. On app_rpt 3.10.5 that includes a reload, which still reports success. Verified against the installed packages.`;
function lev(a, b) { const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]); for (let j = 1; j <= b.length; j++) d[0][j] = j; for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); return d[a.length][b.length]; }
function lintRpt(text) {
  const probs = []; const defined = new Set(); const firstDef = {}; let section = null; let seen = {};
  const lines = text.split('\n');
  lines.forEach((raw, i) => { const m = raw.replace(/;.*/, '').trim().match(/^\[([^\]]+)\]/); if (m && !firstDef[m[1]]) firstDef[m[1]] = i + 1; });
  lines.forEach((raw, i) => {
    const ln = i + 1; const line = raw.replace(/;.*/, '').trim();
    if (!line) return;
    if (line.startsWith('#')) { if (/custom\/rpt\//.test(line)) CUSTOMS.forEach((c) => defined.add(c.id)); return; }
    if (line.startsWith('[')) {
      const m = line.match(/^\[([^\]]*)\](.*)$/);
      if (!m) { probs.push({ sev: 'error', line: ln, msg: 'Missing closing <span class="mono">]</span> in a section header.', why: WHY_REJECT('config.c:2049') }); return; }
      section = m[1]; seen = {};
      const rest = m[2].trim();
      if (rest.startsWith('(')) {
        const close = rest.indexOf(')');
        if (close < 0) probs.push({ sev: 'error', line: ln, msg: 'Missing closing <span class="mono">)</span> after the template list.', why: WHY_REJECT('config.c:2076') });
        else rest.slice(1, close).split(',').map((x) => x.trim()).forEach((t) => {
          if (!t || t === '!' || t.startsWith('+') || defined.has(t)) return;
          const later = firstDef[t] && firstDef[t] > ln;
          const near = [...defined].find((d) => lev(d, t) <= 2);
          probs.push({ sev: 'error', line: ln, msg: later
            ? `<span class="mono">[${esc(section)}]</span> uses template <span class="mono">${esc(t)}</span> before it is defined on line ${firstDef[t]}. Templates must be defined first.`
            : `<span class="mono">[${esc(section)}]</span> uses template <span class="mono">${esc(t)}</span>, which is not defined in this file or its includes.${near ? ` Did you mean <span class="mono">${esc(near)}</span>?` : ''}`, why: WHY_REJECT('config.c:2112') });
        });
      }
      defined.add(section); return;
    }
    const kv = line.match(/^([^=]+?)\s*=>?/);
    if (!kv) { probs.push({ sev: 'warning', line: ln, msg: 'This line has no <span class="mono">=</span>, so Asterisk ignores it.', why: 'Asterisk skips the line and loads the rest of the file (main/config.c:2330).' }); return; }
    const k = kv[1].trim();
    if (!section || MULTI.has(k)) return;
    if (seen[k]) probs.push({ sev: 'warning', line: ln, msg: `<span class="mono">${esc(k)}</span> is set twice in <span class="mono">[${esc(section)}]</span>. Line ${ln} wins; the value on line ${seen[k]} is ignored.`, why: 'ASL’s Asterisk uses the last value for a key (ASL patch config_c_fix_template_inheritance_overrides, ASTERISK-30370). Overriding a template value in a node stanza is normal and is not flagged. Only repeats within the stanza itself are.' });
    else seen[k] = ln;
  });
  return probs.sort((a, b) => (a.sev === b.sev ? a.line - b.line : a.sev === 'error' ? -1 : 1));
}
function probCounts(probs) { return { e: probs.filter((p) => p.sev === 'error').length, w: probs.filter((p) => p.sev === 'warning').length }; }
function probLabels(probs) {
  const { e, w } = probCounts(probs);
  if (!e && !w) return L('OK', 'green', 'check-circle');
  return (e ? L(`${e} error${e > 1 ? 's' : ''}`, 'red', 'times-circle') : '') + (w ? ' ' + L(`${w} warning${w > 1 ? 's' : ''}`, 'orange', 'exclamation-triangle') : '');
}
function pagePlanned(id) {
  const p = PLANNED[id];
  return head(p.title, '', { labels: L('Planned', 'purple') }) + `<section class="page-body">${Card('', Empty(p.icon, `${p.title} is planned for a later phase`, `<p>${p.body}</p>`))}</section>`;
}

/* ===================== render ===================== */
function render() {
  const app = $('#app');
  if (!S.authed) { app.innerHTML = renderLogin(); renderNotes(); return; }
  const r = S.route;
  let page;
  if (r === 'overview') page = pageOverview();
  else if (r === 'nodes') page = pageNodes();
  else if (r.startsWith('node-')) page = pageNode(r.slice(5));
  else if (r === 'asterisk') page = pageAsterisk();
  else if (r === 'diagnostics') page = pageDiagnostics();
  else if (r === 'backups') page = pageBackups();
  else if (r === 'config') page = pageConfig();
  else if (r.startsWith('edit-')) page = pageEdit(r.slice(5));
  else if (r.startsWith('planned-')) page = pagePlanned(r.slice(8));
  else page = pageOverview();
  app.innerHTML = renderShell(page);
  if (r.startsWith('node-') && S.tab.node === 'tuning') startMeter(); else stopTimers();
  const term = $('#term'); if (term) term.scrollTop = term.scrollHeight;
  const fm = $('.fixed-menu');
  if (fm) { const b = fm.previousElementSibling.getBoundingClientRect(); fm.style.top = `${b.bottom + 4}px`; fm.style.left = `${Math.max(8, b.right - fm.offsetWidth)}px`; }
  renderNotes();
}

/* ===================== wizard ===================== */
const WSTEPS = [['number', 'Node number'], ['password', 'Password'], ['preset', 'Configuration'], ['iface', 'Radio interface'], ['call', 'Callsign'], ['customs', 'Customizations'], ['review', 'Review']];
const PRESETS = [
  { id: 'manual', group: '', label: 'Manual', desc: 'Start from the defaults and set everything yourself.' },
  { id: 'hs-tel', group: 'Common configurations', label: 'Half-duplex node (hotspot) with telemetry tones', duplex: 1 },
  { id: 'hs-notel', group: 'Common configurations', label: 'Half-duplex node (hotspot) without telemetry tones', duplex: 0 },
  { id: 'fd', group: 'Common configurations', label: 'Full-duplex node (repeater or hotspot)', duplex: 2 },
  { id: 'fd-norep', group: 'Common configurations', label: 'Full-duplex node that does not repeat audio', duplex: 3 },
  { id: 'hub', group: 'Common configurations', label: 'Hub node with no radio interface', duplex: 2, iface: 'Pseudo' },
  ...CUSTOMS.filter((c) => c.kind === 'iface').map((c) => ({ id: 'dev-' + c.id, group: 'Device configurations', label: c.label, duplex: c.duplex, iface: c.iface, custom: c.id })),
];
function startWizard(mode) {
  S.wiz = { mode, step: 0, num: '', pw: '', preset: 'hs-tel', iface: 'SimpleUSB', call: '', customs: [], err: '', done: false };
  renderWizard();
}
function wizSkipped(i) { const w = S.wiz; const id = WSTEPS[i][0]; if (id === 'password') return w.num && Number(w.num) < 2000; if (id === 'iface') return !!presetObj().iface; if (id === 'customs') return w.preset === 'hub'; return false; }
function presetObj() { return PRESETS.find((p) => p.id === S.wiz.preset); }
function validateNum(v, current) {
  if (!/^\d{4,6}$/.test(v)) return 'Node numbers have 4 to 6 digits.';
  if (Number(v) < 1000) return 'Private node numbers start at 1000.';
  if (Number(v) >= 2000 && v.startsWith('1')) return 'Registered node numbers cannot start with 1.';
  if (v !== current && S.nodes.some((n) => n.num === v) && !S.sim.firstRun) return `Node ${v} is already configured.`;
  return '';
}
function wizBody() {
  const w = S.wiz, id = WSTEPS[w.step][0];
  const err = w.err ? `<div class="pf-v6-c-helper-text">${HT(w.err, 'error')}</div>` : '';
  if (w.done) {
    const tune = ['SimpleUSB', 'USBRadio'].includes(w.iface) && presetObj().id !== 'hub';
    return Empty('check-circle', `Node ${w.num} is set up`, `<p>The configuration files were updated and the previous versions saved as a snapshot. Restart Asterisk to bring the node on the air${tune ? ', then tune the radio interface' : ''}.</p>`,
      B('Restart Asterisk now', { v: 'primary', act: 'wizRestart' }) + (tune ? B('Tune interface', { act: 'wizTune' }) : '') + B('Close', { v: 'link', act: 'wizClose' }));
  }
  if (id === 'number') return `<form class="pf-v6-c-form" data-submit="wizNext" novalidate>${w.mode === 'first' ? '<p>The template node 1999 will be renamed to your node number.</p>' : ''}${FG('Node number', In('wz-num', w.num, { inputmode: 'numeric', err: !!w.err, ph: 'e.g. 63002' }), w.err ? HT(w.err, 'error') : HT('Use the number assigned in your AllStarLink portal account, or 1000–1999 for a private node.'), { for: 'wz-num', req: true })}</form>`;
  if (id === 'password') return `<form class="pf-v6-c-form" data-submit="wizNext" novalidate>${FG('Node password', In('wz-pw', w.pw, { err: !!w.err }), w.err ? HT(w.err, 'error') : HT('From allstarlink.org: Portal → Node Settings. Letters, numbers, _ and -, at least 6 characters.'), { for: 'wz-pw', req: true })}</form>`;
  if (id === 'preset') {
    let html = ''; let g = null;
    PRESETS.forEach((p) => { if (p.group !== g) { g = p.group; if (g) html += `<h3 class="small" style="margin:1rem 0 .25rem">${g}</h3>`; } html += Chk('wp-' + p.id, p.label, w.preset === p.id, p.desc || (p.iface ? `${IFACES[p.iface].name} · duplex ${p.duplex}` : `Duplex ${p.duplex}`), { radio: true, name: 'wz-preset', value: p.id }); });
    return `<form class="pf-v6-c-form" novalidate><p>How will node ${w.num} be used?</p>${FG('', html, '', { stack: true })}</form>`;
  }
  if (id === 'iface') return `<form class="pf-v6-c-form" novalidate>${FG('', Object.entries(IFACES).map(([k, v]) => Chk('wi-' + k, `<b>${v.name}</b>`, w.iface === k, v.desc, { radio: true, name: 'wz-iface', value: k })).join(''), '', { stack: true })}</form>`;
  if (id === 'call') return `<form class="pf-v6-c-form" data-submit="wizNext" novalidate>${FG('Callsign', In('wz-call', w.call, { err: !!w.err, ph: 'e.g. W1XYZ' }), w.err ? HT(w.err, 'error') : HT('Used for the node’s voice ID.'), { for: 'wz-call', req: true })}</form>`;
  if (id === 'customs') {
    const opts = CUSTOMS.filter((c) => c.kind === 'opt');
    return `<form class="pf-v6-c-form" novalidate><p>Optional extras from /etc/asterisk/custom. You can change these later on the node’s Customizations tab.</p>${FG('', opts.map((c) => Chk('wc-' + c.id, c.label, w.customs.includes(c.id), c.files)).join(''), '', { stack: true })}</form>`;
  }
  const p = presetObj(); const iface = p.iface || w.iface;
  return `<div class="stack">${DL([['Node', `<b>${w.num}</b>${Number(w.num) < 2000 ? ' (private)' : ''}`], ['Password', Number(w.num) < 2000 ? '—' : '••••••••'], ['Configuration', p.label], ['Radio interface', IFACES[iface].name], ['Duplex', p.duplex != null ? `${p.duplex} — ${DUPLEX[p.duplex][0]}` : 'from template'], ['Callsign', w.call], ['Customizations', [p.custom ? CUSTOMS.find((c) => c.id === p.custom).label : null, ...w.customs.map((c) => CUSTOMS.find((x) => x.id === c).label)].filter(Boolean).join(', ') || 'None'], ['Status posting', Number(w.num) >= 2000 ? 'On' : 'Off (private node)']])}
    <h3 class="small">Changes to be written</h3>${DiffView(addNodeDiff(w.num, iface, p.duplex ?? 1, w.call, p.custom))}</div>`;
}
function renderWizard() {
  const w = S.wiz;
  const nav = WSTEPS.map(([id, label], i) => {
    const skip = wizSkipped(i), cur = i === w.step, dis = w.done || skip || i > w.maxStep || (i > w.step && !w.maxStep);
    return `<li class="pf-v6-c-wizard__nav-item"><button type="button" class="pf-v6-c-wizard__nav-link${cur ? ' pf-m-current' : ''}${dis ? ' pf-m-disabled' : ''}" ${cur ? 'aria-current="step"' : ''} ${dis ? 'disabled' : ''} data-act="wizGoto" data-arg="${i}"><span class="pf-v6-c-wizard__nav-link-main">${label}${skip ? ' <span class="small">(not needed)</span>' : ''}</span></button></li>`;
  }).join('');
  const last = w.step === WSTEPS.length - 1;
  const footer = w.done ? '' : `<footer class="pf-v6-c-wizard__footer"><div class="row">${B(last ? (w.mode === 'first' ? 'Set up node' : 'Add node') : 'Next', { v: 'primary', act: 'wizNext' })}${B('Back', { act: 'wizBack', dis: w.step === 0 })}<span style="flex:1"></span>${B('Cancel', { v: 'link', act: 'closeModal' })}</div></footer>`;
  S.modal = `<div class="pf-v6-c-backdrop"><div class="pf-v6-l-bullseye"><div class="pf-v6-c-modal-box pf-m-lg" role="dialog" aria-modal="true" aria-labelledby="wiz-title">
    <div class="pf-v6-c-wizard">
      <div class="pf-v6-c-wizard__header"><div class="pf-v6-c-wizard__close">${B('', { v: 'plain', icon: 'times', act: 'closeModal', aria: 'Close' })}</div><div class="pf-v6-c-wizard__title"><h2 class="pf-v6-c-wizard__title-text" id="wiz-title">${w.mode === 'first' ? 'Set up your node' : 'Add node'}</h2></div><div class="pf-v6-c-wizard__description">Step ${w.step + 1} of ${WSTEPS.length}: ${WSTEPS[w.step][1]}</div></div>
      <div class="pf-v6-c-wizard__outer-wrap"><div class="pf-v6-c-wizard__inner-wrap">
        <nav class="pf-v6-c-wizard__nav" aria-label="Steps"><ol class="pf-v6-c-wizard__nav-list">${nav}</ol></nav>
        <main class="pf-v6-c-wizard__main"><div class="pf-v6-c-wizard__main-body">${wizBody()}</div></main>
      </div>${footer}</div>
    </div></div></div></div>`;
  renderModal();
  const f = $('#modal-root .pf-v6-c-wizard__main input:not([type=radio]):not([type=checkbox])'); if (f) f.focus();
}
function wizCollect() {
  const w = S.wiz, id = WSTEPS[w.step][0];
  if (id === 'number') w.num = val('wz-num');
  if (id === 'password') w.pw = val('wz-pw');
  if (id === 'preset') { const p = document.querySelector('input[name=wz-preset]:checked'); if (p) w.preset = p.value; const po = presetObj(); if (po.iface) w.iface = po.iface; }
  if (id === 'iface') { const p = document.querySelector('input[name=wz-iface]:checked'); if (p) w.iface = p.value; }
  if (id === 'call') w.call = val('wz-call').toUpperCase();
  if (id === 'customs') w.customs = CUSTOMS.filter((c) => c.kind === 'opt' && checked('wc-' + c.id)).map((c) => c.id);
}
function wizValidate() {
  const w = S.wiz, id = WSTEPS[w.step][0];
  if (id === 'number') return validateNum(w.num, w.mode === 'first' ? '1999' : null);
  if (id === 'password') return /^[0-9A-Za-z_-]{6,}$/.test(w.pw) ? '' : 'Use at least 6 characters: letters, numbers, _ and -.';
  if (id === 'call') return /^[0-9A-Za-z/-]{3,}$/.test(w.call) ? '' : 'Callsigns have at least 3 characters: letters, numbers, / and -.';
  return '';
}
function addNodeDiff(num, iface, duplex, call, custom) {
  const I = IFACES[iface];
  const files = [
    { file: 'rpt.conf', lines: [['@', '@@ [nodes] @@'], [' ', '63001 = radio@127.0.0.1/63001,NONE'], [' ', '1001 = radio@127.0.0.1/1001,NONE'], ['+', `${num} = radio@127.0.0.1/${num},NONE`], ['@', '@@ end of file @@'], [' ', 'idrecording = |iN0CALL'], ['+', ''], ['+', `[${num}](node-main${custom ? ',' + custom : ''})`], ['+', `rxchannel = ${I.ch(num)}`], ['+', `duplex = ${duplex}`], ...(Number(num) >= 2000 ? [['+', 'statpost_url = http://stats.allstarlink.org/uhandler']] : []), ['+', `idrecording = |i${call || 'N0CALL'}`]] },
  ];
  if (Number(num) >= 2000) {
    files.push({ file: 'rpt_http_registrations.conf', lines: [['@', '@@ [registrations] @@'], [' ', 'register => 63001:Xk29fLq7@register.allstarlink.org'], ['+', `register => ${num}:••••••••@register.allstarlink.org`]] });
    files.push({ file: 'iax.conf', lines: [['@', '@@ [general] @@'], [' ', ';register => 63001:Xk29fLq7@register.allstarlink.org'], ['+', `;register => ${num}:••••••••@register.allstarlink.org`]] });
  }
  if (I.mod && iface !== 'SimpleUSB') files.push({ file: 'modules.conf', lines: [['@', '@@ [modules] @@'], ['-', `noload => ${I.mod}.so`], ['+', `load => ${I.mod}.so`]] });
  if (I.file && iface !== 'Voter') files.push({ file: I.file, lines: [['@', '@@ end of file @@'], ['+', ''], ['+', `[${num}](node-main${custom ? ',' + custom : ''})`], ['+', ''], ['+', ';;;;; Tune settings ;;;;;'], ['+', 'devstr ='], ['+', 'rxmixerset = 500'], ['+', 'txmixaset = 500'], ['+', 'txmixbset = 500']] });
  return files;
}
function renameDiff(o, n) {
  return [
    { file: 'rpt.conf', lines: [['@', '@@ [nodes] @@'], ['-', `${o} = radio@127.0.0.1/${o},NONE`], ['+', `${n} = radio@127.0.0.1/${n},NONE`], ['@', '@@ node stanza @@'], ['-', `[${o}](node-main,shari-pixx)`], ['+', `[${n}](node-main,shari-pixx)`], ['-', `rxchannel = SimpleUSB/${o}`], ['+', `rxchannel = SimpleUSB/${n}`], ['-', `events = events-${o}`], ['+', `events = events-${n}`], ['-', `[events-${o}](events-main,keyed-gpio4)`], ['+', `[events-${n}](events-main,keyed-gpio4)`]] },
    { file: 'rpt_http_registrations.conf', lines: [['-', `register => ${o}:Xk29fLq7@register.allstarlink.org`], ['+', `register => ${n}:Xk29fLq7@register.allstarlink.org`]] },
    { file: 'iax.conf', lines: [['-', `;register => ${o}:Xk29fLq7@register.allstarlink.org`], ['+', `;register => ${n}:Xk29fLq7@register.allstarlink.org`]] },
    { file: 'extensions.conf', lines: [['@', '@@ [globals] @@'], ['-', `NODE = ${o}`], ['+', `NODE = ${n}`]] },
    { file: 'savenode.conf', lines: [['-', `NODE=${o}`], ['+', `NODE=${n}`]] },
    { file: 'simpleusb.conf', lines: [['-', `[${o}](node-main,shari-pixx)`], ['+', `[${n}](node-main,shari-pixx)`]] },
    { path: '/etc/allmon3/allmon3.ini', note: '(via privileged helper; Allmon3 restarts)', lines: [['-', `[${o}]`], ['+', `[${n}]`]] },
    { path: 'Asterisk database', note: '(allow/deny entries move to the new number)', lines: [['-', `/denylist/${o}/2000 : Test node, blocked while debugging`], ['+', `/denylist/${n}/2000 : Test node, blocked while debugging`]] },
  ];
}

/* ===================== actions ===================== */
const A = {
  nav: (r) => go(r),
  toggleNav: () => { S.navOpen = !S.navOpen; render(); },
  menu: (m) => { S.menu = S.menu === m ? null : m; render(); },
  tab: (arg) => { const [k, t] = arg.split(':'); S.tab[k] = t; S.nodesMenu = null; render(); },
  toggleNotes: () => { S.notesOpen = !S.notesOpen; renderNotes(); },
  closeModal: () => closeModal(),
  nyi: (what) => toast('info', `${what} is not part of this mockup`),
  extDocs: () => { S.menu = null; render(); window.open('https://allstarlink.github.io/', '_blank', 'noopener'); },
  extForum: () => { S.menu = null; render(); window.open('https://community.allstarlink.org/', '_blank', 'noopener'); },
  about: () => { S.menu = null; render(); openModal(M('About ASL Web UI', DL([['Version', '0.1.0 (mockup)'], ['License', 'AGPL-3.0'], ['Design system', 'PatternFly 6'], ['Project', 'AllStarLink']]), B('Close', { v: 'primary', act: 'closeModal' }), { size: 'sm' })); },

  login: () => {
    if (S.loginStep === 'password') {
      if (!val('login-pw')) { S.loginErr = 'Enter your password.'; render(); return; }
      S.keepSignedIn = checked('login-keep');
      if (S.sim.mfa) { S.loginStep = 'mfa'; S.loginErr = ''; render(); return; }
    }
    S.authed = true; S.loginStep = 'password'; S.loginErr = ''; S.lastAuth = Date.now(); go(S.route || 'overview');
    toast('success', 'Signed in as operator', S.keepSignedIn ? 'You will stay signed in on this browser for up to 30 days.' : 'This session ends after 30 minutes of inactivity.');
  },
  loginRestart: () => { S.loginStep = 'password'; render(); },
  logout: () => { S.authed = false; S.menu = null; S.lastAuth = 0; history.replaceState(null, '', location.pathname); S.route = 'overview'; render(); },
  reauth: () => {
    if (!val('reauth-pw')) { $('#reauth-err').innerHTML = `<div class="pf-v6-c-helper-text">${HT('Enter your password.', 'error')}</div>`; return; }
    S.lastAuth = Date.now(); const fn = S.pending; S.pending = null; closeModal(); if (fn) fn();
  },

  restartAsterisk: () => restartGate() || openModal(M('Restart Asterisk?', '<p>All links on every node disconnect for about 10 seconds while Asterisk restarts. Configuration changes take effect after the restart.</p>', B('Restart', { v: 'primary', act: 'doRestart' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'warning', size: 'sm' })),
  doRestart: () => {
    openModal(M('Restarting Asterisk', `<div class="row">${Spinner('md')}<span>Stopping, starting, and waiting for registrations…</span></div>`, '', { size: 'sm' }));
    setTimeout(() => { closeModal(); S.sim.restart = false; S.sim.stopped = false; S.rptDown = false; toast('success', 'Asterisk restarted', 'Node 63001 registered again after 4 seconds.'); render(); }, 1800);
  },
  doRestartAnyway: () => {
    openModal(M('Restarting Asterisk', `<div class="row">${Spinner('md')}<span>Stopping and starting…</span></div>`, '', { size: 'sm' }));
    setTimeout(() => { closeModal(); S.sim.restart = false; S.sim.stopped = false; S.rptDown = true; toast('danger', 'Asterisk restarted, but app_rpt rejected rpt.conf', 'All nodes are off the air until rpt.conf is fixed.'); render(); }, 1800);
  },
  fixRpt: (line) => { closeModal(); go('edit-rpt.conf'); setTimeout(() => A.edGoto(line), 50);
  },
  stopAsterisk: () => requireAuth('Stopping Asterisk takes every node off the air.', () => openModal(M('Stop Asterisk?', '<p>All nodes go off the air and links are dropped until Asterisk is started again.</p>', B('Stop', { v: 'primary', danger: true, act: 'doStop' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'danger', size: 'sm' }))),
  doStop: () => { closeModal(); S.sim.stopped = true; toast('warning', 'Asterisk stopped'); render(); },
  startAsterisk: () => { S.sim.stopped = false; S.sim.restart = false; toast('success', 'Asterisk started'); render(); },
  changedFiles: () => openModal(M('Files changed since Asterisk started', T(['File', 'Modified', 'By'], [['<span class="mono">rpt.conf</span>', 'Today 14:02', 'asl-web-ui (operator)'], ['<span class="mono">simpleusb.conf</span>', 'Today 14:02', 'asl-web-ui (operator)']], { compact: true, label: 'Changed files' }) + '<p class="small muted" style="margin-top:1rem">Detected by comparing file modification times with when Asterisk started, so edits made outside the web UI show up here too. “By” is known only for changes made through the web UI.</p>', B('Restart Asterisk', { v: 'primary', act: 'restartAsterisk' }) + B('Close', { v: 'link', act: 'closeModal' }))),
  reboot: () => requireAuth('Rebooting interrupts every node.', () => openModal(M('Reboot asl-node?', '<p>All nodes go off the air until the server is back up, usually within a minute or two.</p>', B('Reboot', { v: 'primary', danger: true, act: 'doPower', arg: 'Rebooting' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'warning', size: 'sm' }))),
  shutdown: () => requireAuth('Shutting down turns the server off.', () => openModal(M('Shut down asl-node?', `<p>The server powers off. <b>Someone must have physical access to turn it back on.</b></p><form class="pf-v6-c-form" novalidate>${FG('Type the hostname to confirm', In('confirm-host', '', { ph: 'asl-node' }), '', { for: 'confirm-host' })}</form>`, B('Shut down', { v: 'primary', danger: true, act: 'doPower', arg: 'Shutting down' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'danger', size: 'sm' }))),
  doPower: (what) => { if (what === 'Shutting down' && val('confirm-host') !== 'asl-node') { toast('danger', 'The hostname does not match'); return; } closeModal(); toast('info', `${what}… (mockup: nothing happens)`); },

  addNode: (mode) => startWizard(mode === 'first' || S.sim.firstRun ? 'first' : 'add'),
  wizNext: () => {
    const w = S.wiz; if (!w) return;
    if (WSTEPS[w.step][0] === 'review') { w.done = true; if (!S.sim.firstRun) S.nodes.push({ num: w.num, call: w.call, iface: presetObj().iface || w.iface, duplex: presetObj().duplex ?? 1, linktolink: 'no', statpost: Number(w.num) >= 2000, pw: w.pw, reg: Number(w.num) >= 2000 ? 'Pending restart' : 'Private', access: { mode: 'open', list: [] }, customs: w.customs, needTune: true }); else { S.sim.firstRun = false; S.nodes[0].num = w.num; S.nodes[0].call = w.call; } S.sim.restart = true; render(); renderWizard(); return; }
    wizCollect(); w.err = wizValidate(); if (w.err) { renderWizard(); return; }
    let s = w.step + 1; while (s < WSTEPS.length - 1 && wizSkipped(s)) s++;
    w.step = s; w.maxStep = Math.max(w.maxStep || 0, s); renderWizard();
  },
  wizBack: () => { const w = S.wiz; wizCollect(); w.err = ''; let s = w.step - 1; while (s > 0 && wizSkipped(s)) s--; w.step = Math.max(0, s); renderWizard(); },
  wizGoto: (i) => { const w = S.wiz; wizCollect(); w.err = ''; w.step = Number(i); renderWizard(); },
  wizClose: () => { const n = S.wiz.num; closeModal(); go('node-' + (S.nodes.find((x) => x.num === n) ? n : S.nodes[0].num)); },
  wizRestart: () => { closeModal(); A.restartAsterisk(); },
  wizTune: () => { const n = S.wiz.num; closeModal(); S.tab.node = 'tuning'; go('node-' + n); },

  nodeMenu: (num) => { S.nodesMenu = S.nodesMenu === num ? null : num; render(); },
  removeNode: (num) => { S.nodesMenu = null; requireAuth(`Removing node ${num} changes several configuration files.`, () => openModal(M(`Remove node ${num}?`, `<div class="stack"><p>Node ${num} is removed from these files. A snapshot of each file is saved first, and you can also restore from a backup.</p>${DiffView([{ file: 'rpt.conf', lines: [['-', `${num} = radio@127.0.0.1/${num},NONE`], ['-', `[${num}](node-main)`], ['-', 'rxchannel = Local/pseudo'], ['-', 'duplex = 2']] }, { file: 'extensions.conf', lines: [[' ', 'NODE = 63001'], [' ', '(unchanged: primary node is still 63001)']] }])}</div>`, B('Remove node', { v: 'primary', danger: true, act: 'doRemove', arg: num }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'danger', size: 'md' }))); },
  doRemove: (num) => { closeModal(); S.nodes = S.nodes.filter((n) => n.num !== num); needRestart(`Node ${num} removed`); go('nodes'); },
  renameNode: (num) => { S.nodesMenu = null; S.rename = { from: num, to: '', step: 'form', err: '' }; renderRename(); },
  renamePreview: () => { const r = S.rename; r.to = val('rn-to'); r.err = validateNum(r.to, r.from) || (r.to === r.from ? 'Enter a different number.' : ''); if (!r.err) r.step = 'diff'; renderRename(); },
  renameBack: () => { S.rename.step = 'form'; renderRename(); },
  doRename: () => { const r = S.rename; const n = S.nodes.find((x) => x.num === r.from); n.num = r.to; closeModal(); needRestart(`Node ${r.from} renamed to ${r.to}`); go('node-' + r.to); },
  showPw: (num) => { const n = S.nodes.find((x) => x.num === num); $('#pw-' + num).textContent = n.pw; },
  changePw: (num) => openModal(M(`Change password for node ${num}`, `<form class="pf-v6-c-form" data-submit="savePw" novalidate>${FG('New password', In('pw-new', ''), HT('From allstarlink.org: Portal → Node Settings.'), { for: 'pw-new' })}<p class="small muted">Updates rpt_http_registrations.conf, iax.conf, and savenode.conf (used for cloud backups).</p></form>`, B('Save', { v: 'primary', act: 'savePw', arg: num }) + B('Cancel', { v: 'link', act: 'closeModal' }))),
  savePw: (num) => { const v = val('pw-new'); if (!/^[0-9A-Za-z_-]{6,}$/.test(v)) { toast('danger', 'Use at least 6 characters: letters, numbers, _ and -.'); return; } S.nodes.find((x) => x.num === (num || S.route.slice(5))).pw = v; closeModal(); needRestart('Password changed'); },
  changeCall: (num) => { const n = S.nodes.find((x) => x.num === num); openModal(M(`Callsign for node ${num}`, `<form class="pf-v6-c-form" data-submit="saveCall" novalidate>${FG('Callsign', In('call-new', n.call), HT('Sets the voice ID (idrecording).'), { for: 'call-new' })}</form>`, B('Save', { v: 'primary', act: 'saveCall', arg: num }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm' })); },
  saveCall: (num) => { const v = val('call-new').toUpperCase(); if (!/^[0-9A-Z/-]{3,}$/.test(v)) { toast('danger', 'Callsigns have at least 3 characters: letters, numbers, / and -.'); return; } S.nodes.find((x) => x.num === (num || S.route.slice(5))).call = v; closeModal(); needRestart('Callsign changed'); },
  changeDuplex: (num) => {
    const n = S.nodes.find((x) => x.num === num);
    openModal(M(`Duplex for node ${num}`, `<form class="pf-v6-c-form" novalidate>${FG('', DUPLEX.map(([l, d], i) => Chk('dx-' + i, `${i} — ${l}`, n.duplex === i, d, { radio: true, name: 'dx', value: i, act: 'dxPick' })).join(''), '', { stack: true })}
      <div id="dx-sub" ${n.duplex === 0 ? '' : 'hidden'}>${FG('For duplex 0', Chk('l2l-no', 'Half duplex', n.linktolink !== 'yes', '', { radio: true, name: 'l2l', value: 'no' }) + Chk('l2l-yes', 'Full duplex (for external repeater controllers)', n.linktolink === 'yes', '', { radio: true, name: 'l2l', value: 'yes' }), '', { stack: true })}</div>
      <p class="small muted">Some changes also adjust related settings, as the text menu does: hang time is set to 100 ms for duplex 0 and 400 ms for duplex 1 when it is still at a default value.</p></form>`,
      B('Save', { v: 'primary', act: 'saveDuplex', arg: num }) + B('Cancel', { v: 'link', act: 'closeModal' })));
  },
  saveDuplex: (num) => { const n = S.nodes.find((x) => x.num === num); const p = document.querySelector('input[name=dx]:checked'); n.duplex = Number(p.value); const l = document.querySelector('input[name=l2l]:checked'); if (l) n.linktolink = l.value; closeModal(); needRestart('Duplex changed'); },
  applyIface: (num) => {
    const n = S.nodes.find((x) => x.num === num); const p = document.querySelector('input[name=iface]:checked'); const to = p.value;
    if (to === n.iface) { toast('info', 'No change', `Node ${num} already uses ${IFACES[to].name}.`); return; }
    const I = IFACES[to], O = IFACES[n.iface];
    const files = [{ file: 'rpt.conf', lines: [['@', `@@ [${num}] @@`], ['-', `rxchannel = ${O.ch(num)}`], ['+', `rxchannel = ${I.ch(num)}`]] }, { file: 'modules.conf', lines: [...(O.mod ? [['-', `load => ${O.mod}.so`], ['+', `noload => ${O.mod}.so`]] : []), ...(I.mod ? [['-', `noload => ${I.mod}.so`], ['+', `load => ${I.mod}.so`]] : [])] }];
    if (I.file) files.push({ file: I.file, lines: [['@', '@@ end of file @@'], ['+', `[${num}](node-main)`], ['+', ';;;;; Tune settings ;;;;;'], ['+', 'devstr ='], ['+', 'rxmixerset = 500']] });
    S.ifacePending = { num, to };
    openModal(M(`Change node ${num} to ${I.name}?`, `<div class="stack"><p>These changes will be written. The old ${O.name} section is left in place so its settings are not lost.</p>${DiffView(files)}</div>`, B('Apply changes', { v: 'primary', act: 'doIface' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'lg' }));
  },
  doIface: () => { const { num, to } = S.ifacePending; S.nodes.find((x) => x.num === num).iface = to; closeModal(); needRestart(`Node ${num} now uses ${IFACES[to].name}`); },
  applyCustoms: (num) => openModal(M(`Customizations for node ${num}`, `<div class="stack"><p>The node’s template list changes as follows.</p>${DiffView([{ file: 'rpt.conf', lines: [['-', `[${num}](node-main,shari-pixx)`], ['+', `[${num}](node-main,shari-pixx,audio-archiving)`]] }])}</div>`, B('Apply changes', { v: 'primary', act: 'doCustoms' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'lg' })),
  doCustoms: () => { closeModal(); needRestart('Customizations updated'); },

  accAdd: (num) => {
    num = num || S.route.slice(5); const n = S.nodes.find((x) => x.num === num); const id = val('acc-id').toUpperCase();
    const err = !/^(\d+|[0-9A-Z/-]{3,})$/.test(id) ? 'Enter a node number or a callsign.' : id === num ? `Node ${num} cannot ${n.access.mode === 'allow' ? 'allow' : 'block'} itself.` : n.access.list.some((e) => e.id === id) ? `${id} is already listed.` : '';
    if (err) { $('#acc-err').innerHTML = `<div class="pf-v6-c-helper-text">${HT(err, 'error')}</div>`; return; }
    n.access.list.push({ id, reason: val('acc-reason') }); toast('success', `${id} ${n.access.mode === 'allow' ? 'allowed' : 'blocked'}`, 'Takes effect immediately.'); render();
  },
  accRemove: (arg) => { const [num, i] = arg.split(':'); const n = S.nodes.find((x) => x.num === num); const e = n.access.list.splice(Number(i), 1)[0]; toast('success', `${e.id} removed from the list`); render(); },
  accClear: (num) => openModal(M('Remove all entries?', `<p>Node ${num} becomes open to all nodes unless you add entries again.</p>`, B('Remove all', { v: 'primary', danger: true, act: 'doAccClear', arg: num }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm', variant: 'warning' })),
  doAccClear: (num) => { const n = S.nodes.find((x) => x.num === num); n.access.list = []; closeModal(); render(); },

  txTone: () => { S.tune.tx = !S.tune.tx; render(); if (S.tune.tx) setTimeout(() => { if (S.tune.tx) { S.tune.tx = false; render(); } }, 30000); },
  tuneSave: () => {
    const t = S.tune; t.dirty = false; render();
    openModal(M('Saved to simpleusb.conf', `<div class="stack"><p>The SimpleUSB driver wrote its current settings to the file. These lines changed. A snapshot of the previous file was kept.</p>${DiffView([{ file: 'simpleusb.conf', lines: [['@', '@@ [63001](node-main,shari-pixx) @@'], ['-', 'rxmixerset = 520'], ['+', `rxmixerset = ${t.rxmixerset}`], ['-', 'txmixaset = 480'], ['+', `txmixaset = ${t.txmixaset}`]] }])}<p class="small muted">No restart is needed: the driver is already using these values.</p></div>`,
      B('Done', { v: 'primary', act: 'closeModal' }) + B('Undo', { act: 'tuneUndo' }), { size: 'lg' }));
  },
  tuneUndo: () => { closeModal(); A.tuneRevert(); toast('success', 'simpleusb.conf restored from the snapshot', 'The driver was set back to the previous values.'); },
  takeOver: () => openModal(M('Take over tuning?', '<p>The SSH session’s tune menu keeps running, but its next change may overwrite yours. Ask that user to exit the menu if you can.</p>', B('Take over', { v: 'primary', act: 'doTakeOver' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm', variant: 'warning' })),
  doTakeOver: () => { S.sim.tuiRunning = false; closeModal(); render(); },
  classicTune: () => openModal(M('Classic tune menu', `<div class="term" style="height:22rem">Running simpleusb-tune-menu -n 63001 as user asterisk

Active Device: 63001

1) Select active USB device
2) Set Rx Voice Level using display (currently '${S.tune.rxmixerset}')
3) Set Transmit A Level (currently '${S.tune.txmixaset}')
4) Set Transmit B Level (currently '${S.tune.txmixbset}')
B) Toggle RX Boost (currently '${S.tune.rxboost ? 'enabled' : 'disabled'}')
C) Toggle Pre-emphasis (currently 'disabled')
D) Toggle De-emphasis (currently 'disabled')
E) Toggle Echo Mode (currently 'disabled')
F) Flash (Toggle PTT and Tone output several times)
G) Toggle PL Filter (currently 'enabled')
H) Toggle PTT mode (currently 'ground')
I) Change Carrier From (currently 'usbinvert')
J) Change CTCSS From (currently 'usbinvert')
K) Change RX On Delay (currently '0')
L) Change TX Off Delay (currently '0')
P) Print Current Parameter Values
R) View Rx Audio Statistics
S) Swap Current USB device with another USB device
T) Toggle Transmit Test Tone/Keying (currently 'disabled')
V) View COS, CTCSS and PTT Status
W) Write (Save) Current Parameter Values
X) View Tx Audio Statistics
0) Exit Menu

Please enter your selection now: <span class="prompt">▌</span></div><p class="small muted" style="margin-top:.5rem">The text-based menu from asl3-menu, for settings this page does not cover. It runs only the tune menu, not a shell. A snapshot is taken first, so changes saved here can be undone too.</p>`, B('Close', { v: 'primary', act: 'closeModal' }), { size: 'lg' })),
  tuneRevert: () => { Object.assign(S.tune, { rxmixerset: 520, txmixaset: 480, txmixbset: 500, rxboost: false, carrierfrom: 'usbinvert', ctcssfrom: 'usbinvert', dirty: false }); render(); },

  showAmi: () => { $('#ami-secret').textContent = S.amiSecret; },
  changeAmi: () => requireAuth('Changing the AMI secret affects Allmon3 and other tools.', () => openModal(M('Change AMI secret', `<form class="pf-v6-c-form" novalidate>${FG('New secret', `<div class="row" style="flex-wrap:nowrap">${In('ami-new', '', { mono: true })}${B('Generate', { act: 'genAmi' })}</div>`, HT('At least 12 characters: letters, numbers, _ and -.'), { for: 'ami-new' })}${Al('info', 'Allmon3 is updated too', '<p>The secret in /etc/allmon3/allmon3.ini is changed to match, and Allmon3 is restarted. Update Supermon or other tools yourself.</p>', '', { plain: true })}</form>`, B('Save', { v: 'primary', act: 'saveAmi' }) + B('Cancel', { v: 'link', act: 'closeModal' })))),
  genAmi: () => { const c = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'; const a = new Uint32Array(16); crypto.getRandomValues(a); document.getElementById('ami-new').value = Array.from(a, (x) => c[x % c.length]).join(''); },
  saveAmi: () => { const v = val('ami-new'); if (!/^[0-9A-Za-z_-]{12,}$/.test(v)) { toast('danger', 'The secret needs at least 12 characters: letters, numbers, _ and -.'); return; } S.amiSecret = v; closeModal(); needRestart('AMI secret changed; Allmon3 updated'); },
  changePort: () => openModal(M('Change IAX port', `<form class="pf-v6-c-form" novalidate>${FG('UDP port', In('port-new', String(S.iaxPort), { inputmode: 'numeric' }), HT('Default 4569. Your router’s port forwarding must match.'), { for: 'port-new' })}<p class="small muted">Updates <span class="mono">bindport</span> in iax.conf and the port in each node’s [nodes] entry in rpt.conf.</p></form>`, B('Save', { v: 'primary', act: 'savePort' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm' })),
  savePort: () => { const p = Number(val('port-new')); if (!(p > 0 && p < 65536)) { toast('danger', 'Enter a port from 1 to 65535.'); return; } S.iaxPort = p; closeModal(); needRestart(`IAX port set to ${p}`); },
  refreshRegs: () => toast('info', 'Registrations refreshed'),
  cli: () => {
    const v = val('cli-in'); if (!v) return;
    if (RELOAD_RE.test(v) && !S.cliForce) {
      const errs = lintRpt(rptText()).filter((p) => p.sev === 'error');
      if (errs.length) {
        S.cliPending = v;
        openModal(M(`rpt.conf has ${errs.length} error${errs.length > 1 ? 's' : ''}`,
          `<div class="stack"><p><span class="mono">${esc(v)}</span> makes app_rpt load rpt.conf again. With these errors, app_rpt 3.10.5 <b>disables every node</b> and still reports that the reload succeeded.</p>
            <ul class="health-list">${errs.map((p) => `<li><span class="st-fail">${ic('times-circle')}</span><span>Line ${p.line}: ${p.msg}</span></li>`).join('')}</ul></div>`,
          B('Fix in editor', { v: 'primary', act: 'fixRpt', arg: errs[0].line }) + B('Run anyway', { v: 'secondary', danger: true, act: 'cliForce' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'danger' }));
        return;
      }
    }
    S.cliForce = false;
    S.console.push(['in', v]);
    if (RELOAD_RE.test(v)) {
      const bad = lintRpt(rptText()).some((p) => p.sev === 'error');
      if (bad) { S.rptDown = true; S.console.push(['out', "Module 'app_rpt' reloaded successfully."]); S.console.push(['err', '[14:22:07] ERROR[4411]: app_rpt.c: Errors detected in the radio repeater configuration rpt.conf.  Radio Repeater disabled.']); }
      else { S.rptDown = false; S.sim.restart = false; S.console.push(['out', "Module 'app_rpt' reloaded successfully."]); }
      render(); const i = $('#cli-in'); if (i) i.focus(); return;
    }
    const out = { 'rpt show registrations': S.diag.regs.out.split('\n\n')[0], 'core show uptime': 'System uptime: 3 days, 5 hours, 8 minutes, 12 seconds\nLast reload: 3 days, 5 hours, 8 minutes, 12 seconds', 'help': 'Common commands: rpt show registrations · rpt stats 63001 · rpt fun 63001 *3<node> · core show uptime · module reload app_rpt\n(Full Asterisk CLI help in the product.)', 'rpt stats 63001': 'Node 63001 — keyups today: 14, TX time today: 00:09:42, links: 2 (2000 [Blocked], 41520)' }[v.toLowerCase()];
    S.console.push(out ? ['out', out] : ['err', `No such command '${v}' (type 'help' for help)`]); render(); const i = $('#cli-in'); if (i) i.focus();
  },

  cliForce: () => { closeModal(); S.cliForce = true; const i = $('#cli-in'); if (i) i.value = S.cliPending; A.cli(); },
  runDiag: (id) => { S.diag[id].prev = S.diag[id].st; S.diag[id].st = 'run'; render(); setTimeout(() => { S.diag[id].st = S.diag[id].prev === 'run' ? 'ok' : (S.diag[id].prev || 'ok'); if (S.sim.stopped && ['version', 'regs'].includes(id)) { S.diag[id].st = 'fail'; S.diag[id].sum = 'Asterisk is not running'; } render(); }, 900 + Math.random() * 900); },
  runAll: () => { DIAGS.forEach(([id]) => A.runDiag(id)); A.runAuth(); },
  runAuth: () => {
    const a = S.authcheck; if (a.st === 'run') return;
    const steps = ['Reading rpt.conf and registration files…', 'Asking 3 HTTP probes how they see your address…', 'Sending UDP probes to 3 IAX test servers…', 'Checking node 63001 registration…', 'Comparing with stats.allstarlink.org…', 'Testing inbound IAX connection (nodeping)…'];
    a.st = 'run'; a.pct = 0; a.step = steps[0]; render();
    let i = 0;
    const tick = setInterval(() => {
      i++;
      if (i >= steps.length) { clearInterval(tick); a.st = 'done'; a.when = '14:21'; render(); const errs = authResults().flatMap((g) => g.items).filter((x) => x.lvl === 'error').length; toast(errs ? 'danger' : 'success', errs ? `Connectivity check found ${errs} error${errs > 1 ? 's' : ''}` : 'Connectivity check passed'); return; }
      a.step = steps[i]; a.pct = Math.round((i / steps.length) * 100); if (S.route === 'diagnostics') render();
    }, 700);
  },
  authRaw: () => { S.authcheck.raw = !S.authcheck.raw; render(); },
  diagOut: (id) => { S.diag[id].open = !S.diag[id].open; render(); },
  restartNodelist: () => { toast('success', 'asl3-update-nodelist restarted'); },

  createBackup: () => openModal(M('Create backup', `<form class="pf-v6-c-form" novalidate><p>Saves the paths listed under Backups → Settings to <span class="mono">/var/asl-backups/ASL_2026-10-13_1420.tgz</span>.</p>${FG('', Chk('bk-cloud', 'Also upload to backup.allstarlink.org', true, 'Uses node 63001’s credentials. Limit 2 MB.'))}</form>`, B('Create', { v: 'primary', act: 'doBackup' }) + B('Cancel', { v: 'link', act: 'closeModal' }))),
  doBackup: () => { const cloud = checked('bk-cloud'); closeModal(); S.backups.unshift({ name: 'ASL_2026-10-13_1420.tgz', when: 'Oct 13, 2026 14:20', size: '48 KB' }); if (cloud) S.cloud.unshift({ name: '20261013142004.tgz', when: 'Oct 13, 2026 14:20', size: '48 KB' }); toast('success', 'Backup created', cloud ? 'Saved locally and uploaded to backup.allstarlink.org.' : 'Saved locally.'); if (S.route === 'backups') render(); },
  uploadBackup: () => openModal(M('Upload a backup', `<div class="stack"><p>Upload a .tgz backup created by ASL (for example one you downloaded earlier). It is checked before anything can be restored.</p><input type="file" accept=".tgz,application/gzip" aria-label="Backup file"></div>`, B('Upload', { v: 'primary', act: 'closeModal' }) + B('Cancel', { v: 'link', act: 'closeModal' }))),
  restoreLocal: (name) => requireAuth('Restoring overwrites configuration files.', () => restorePreview(name)),
  restoreCloud: (name) => requireAuth('Restoring overwrites configuration files.', () => restorePreview(name.replace(/^(\d{4})(\d\d)(\d\d)(\d{4})\d\d\.tgz$/, 'ASL_$1-$2-$3_$4.tgz') + ' (from the cloud)')),
  doRestore: () => { closeModal(); needRestart('Backup restored'); },
  deleteBackup: (name) => openModal(M('Delete backup?', `<p><span class="mono">${esc(name)}</span> is deleted permanently.</p>`, B('Delete', { v: 'primary', danger: true, act: 'doDelete', arg: name }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm', variant: 'danger' })),
  doDelete: (name) => { S.backups = S.backups.filter((b) => b.name !== name); closeModal(); toast('success', 'Backup deleted'); render(); },
  cloudCreds: () => openModal(M('Cloud backup credentials', `<form class="pf-v6-c-form" novalidate>${FG('Node number', In('cc-node', '63001'), '', { for: 'cc-node' })}${FG('Node password', In('cc-pw', '', { type: 'password' }), HT('Used only for this session; savenode.conf is not changed.'), { for: 'cc-pw' })}</form>`, B('Use these', { v: 'primary', act: 'closeModal' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm' })),
  factoryReset: () => requireAuth('Restoring defaults erases your configuration.', () => openModal(M('Restore ASL3 defaults?', `<div class="stack"><p>Every .conf file in /etc/asterisk is replaced with the version from the asl3-asterisk-config package. Your nodes, registrations and customizations are removed. The AMI secret is kept.</p><p>A backup is created first: <span class="mono">ASL_2026-10-13_1420.tgz</span>.</p><form class="pf-v6-c-form" novalidate>${FG('Type <b>RESET</b> to confirm', In('reset-confirm', ''), '', { for: 'reset-confirm' })}</form></div>`, B('Restore defaults', { v: 'primary', danger: true, act: 'doReset' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { variant: 'danger' }))),
  doReset: () => { if (val('reset-confirm') !== 'RESET') { toast('danger', 'Type RESET to confirm'); return; } openModal(M('Restoring defaults', `<pre class="pf-v6-c-code-block__pre small mono" style="white-space:pre-wrap">Creating backup ASL_2026-10-13_1420.tgz… done\nReading package lists… done\nPreparing to unpack …/asl3-asterisk-config_3.5.5-1_all.deb …\nUnpacking asl3-asterisk-config (3.5.5-1) over (3.5.5-1) …\nSetting up asl3-asterisk-config (3.5.5-1) …\nRestoring AMI secret… done</pre>`, B('Close', { v: 'primary', act: 'closeModal' }))); S.sim.firstRun = true; S.sim.restart = true; render(); },

  fixPerms: () => requireAuth('Fixing permissions runs as root.', () => openModal(M('Fix file ownership?', '<p><span class="mono">/etc/asterisk/voter.conf</span> is owned by <b>root:root</b>. It will be changed to <b>asterisk:asterisk</b>, the owner of /etc/asterisk. The file contents are not changed.</p>', B('Fix permissions', { v: 'primary', act: 'doFixPerms' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'sm' }))),
  doFixPerms: () => { S.sim.rootOwned = false; closeModal(); toast('success', 'voter.conf ownership fixed'); render(); },
  edRevert: () => { S.editor.text = S.editor.orig; render(); },
  edSave: () => { const ed = S.editor; openModal(M(`Save ${ed.file}?`, `<div class="stack">${DiffView([{ file: ed.file, lines: lineDiff(ed.orig, ed.text) }])}<p class="small muted">The file is checked again just before saving. If it changed on disk since you opened it, nothing is written and you are asked to reload.</p></div>`, B('Save', { v: 'primary', act: 'edDoSave' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'lg' })); },
  edDoSave: () => { S.editor.orig = S.editor.text; closeModal(); needRestart(`${S.editor.file} saved`); },
  edGoto: (line) => { const ta = $('#ed-text'); const lines = ta.value.split('\n'); let pos = 0; for (let i = 0; i < Number(line) - 1; i++) pos += lines[i].length + 1; ta.focus(); ta.setSelectionRange(pos, pos + lines[Number(line) - 1].length); ta.scrollTop = (Number(line) - 5) * parseFloat(getComputedStyle(ta).lineHeight); },
};
function renderRename() {
  const r = S.rename;
  if (r.step === 'form') openModal(M(`Rename node ${r.from}`, `<form class="pf-v6-c-form" data-submit="renamePreview" novalidate>${FG('New node number', In('rn-to', r.to, { inputmode: 'numeric', err: !!r.err }), r.err ? HT(r.err, 'error') : HT('Renaming updates up to 8 files plus the Asterisk database and Allmon3. You will see every change before it is applied.'), { for: 'rn-to' })}</form>`, B('Preview changes', { v: 'primary', act: 'renamePreview' }) + B('Cancel', { v: 'link', act: 'closeModal' })));
  else openModal(M(`Rename node ${r.from} to ${r.to}`, `<div class="stack"><p>All of these changes are applied together. If any file cannot be written, none of them are.</p>${DiffView(renameDiff(r.from, r.to))}</div>`, B('Apply changes', { v: 'primary', act: 'doRename' }) + B('Back', { act: 'renameBack' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'lg' }));
}
function restorePreview(name) {
  openModal(M('Restore backup?', `<div class="stack"><p>Restoring <span class="mono">${esc(name)}</span>.</p>
    ${T(['Contents', 'Action'], [['<span class="mono">/etc/asterisk/</span> (31 files)', L('Restore', 'blue')], ['<span class="mono">/var/lib/asterisk/astdb.sqlite3</span>', L('Restore', 'blue')], ['<span class="mono">/etc/allmon3/</span> (5 files)', L('Restore', 'blue')], ['<span class="mono">/etc/cron.d/evil</span>', L('Skipped: not in the backup paths', 'orange', 'exclamation-triangle')], ['<span class="mono">../../root/.ssh/authorized_keys</span>', L('Rejected: unsafe path', 'red', 'times-circle')]], { compact: true, label: 'Archive contents' })}
    <p class="small muted">Only paths listed in your backup settings are restored. Absolute paths, “..”, and links pointing outside those paths are rejected. A snapshot of the current files is taken first. (The skipped and rejected rows are examples of what the check catches.)</p></div>`,
    B('Restore', { v: 'primary', act: 'doRestore' }) + B('Cancel', { v: 'link', act: 'closeModal' }), { size: 'lg', variant: 'warning' }));
}

/* ===================== events ===================== */
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) { if (S.menu || S.nodesMenu) { if (!e.target.closest('.tb-menu, .fixed-menu')) { S.menu = null; S.nodesMenu = null; render(); } } return; }
  if (el.disabled) return;
  const act = el.getAttribute('data-act'); const fn = A[act];
  if (act !== 'menu' && act !== 'nodeMenu' && (S.menu || S.nodesMenu) && !el.closest('.tb-menu, .fixed-menu')) { S.menu = null; S.nodesMenu = null; }
  if (fn) { e.preventDefault(); fn(el.getAttribute('data-arg')); }
});
document.addEventListener('submit', (e) => { const f = e.target.closest('[data-submit]'); if (!f) return; e.preventDefault(); const fn = A[f.getAttribute('data-submit')]; if (fn) fn(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { if (S.modal) closeModal(); else if (S.menu || S.nodesMenu || S.navOpen) { S.menu = null; S.nodesMenu = null; S.navOpen = false; render(); } else if (S.notesOpen) A.toggleNotes(); }
  if (e.key === 'Enter' && e.target.matches('input:not([type=radio]):not([type=checkbox]):not([type=range])')) {
    const f = e.target.closest('form[data-submit]');
    if (f) { e.preventDefault(); const fn = A[f.getAttribute('data-submit')]; if (fn) fn(); return; }
    if (e.target.closest('#modal-root')) { const p = $('#modal-root .pf-v6-c-modal-box__footer .pf-m-primary, #modal-root .pf-v6-c-wizard__footer .pf-m-primary'); if (p) { e.preventDefault(); p.click(); } }
  }
});
document.addEventListener('input', (e) => {
  const k = e.target.getAttribute('data-input');
  if (k === 'navSearch') { S.navQ = e.target.value; render(); const i = $('.nav-search input'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
  if (k === 'tune') { const was = S.tune.dirty; S.tune[e.target.id] = Number(e.target.value); S.tune.dirty = true; const o = document.getElementById(e.target.id + '-out'); if (o) o.textContent = e.target.value; if (!was) { const bar = $('#tune-bar'); if (bar) bar.innerHTML = tuneBar(); } }
  if (k === 'edText') { S.editor.text = e.target.value; const g = $('#ed-gutter'); const n = e.target.value.split('\n').length; if (g) g.textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n'); }
});
document.addEventListener('change', (e) => {
  const k = e.target.getAttribute('data-change');
  if (k === 'toggleStatpost') { const num = e.target.id.replace('sw-statpost-', ''); const n = S.nodes.find((x) => x.num === num); n.statpost = e.target.checked; needRestart(n.statpost ? 'Status posting enabled' : 'Status posting disabled'); }
  if (k === 'tuneFlag') { const id = e.target.id === 'sw-rxboost' ? 'rxboost' : e.target.id; S.tune[id] = e.target.type === 'checkbox' ? e.target.checked : e.target.value; S.tune.dirty = true; render(); }
  if (k === 'accMode') { const n = S.nodes.find((x) => x.num === S.route.slice(5)); n.access.mode = e.target.value; render(); }
  if (k === 'dxPick') { const sub = $('#dx-sub'); if (sub) sub.hidden = e.target.value !== '0'; }
  if (e.target.closest('#mock-panel') && e.target.dataset.sim) { S.sim[e.target.dataset.sim] = e.target.checked; if (e.target.dataset.sim === 'http' || e.target.dataset.sim === 'mfa') { S.loginStep = 'password'; } if (e.target.dataset.sim === 'rptError' && S.editor && S.editor.file === 'rpt.conf') S.editor = null; render(); }
});
document.addEventListener('scroll', (e) => { if (S.nodesMenu && e.target.classList && e.target.classList.contains('main')) { S.nodesMenu = null; render(); return; } if (e.target.id === 'ed-text') { const g = $('#ed-gutter'); if (g) g.scrollTop = e.target.scrollTop; } }, true);

/* ===================== mockup notes panel ===================== */
const NOTES = {
  login: ['PAM login runs in a small root helper. The web service itself runs as the asterisk user.', 'Only members of the <code>asl-web-ui</code> group can log in. Root cannot log in by default.', 'Full PAM conversation: turn on “Account has 2FA” to see the second prompt. The prompt text comes from PAM.', '“Keep me signed in”: 30 days, 7-day idle limit. Unchecked: 8 hours, 30-minute idle limit. Sessions end if the service restarts.', 'Turn on “Plain HTTP” to see the HTTPS-required screen.'],
  overview: ['Cockpit-style landing page. Reboot and Shut down are here, as in Cockpit.', 'The restart banner and the “Restart needed” button in the top bar come from comparing config file times with when Asterisk started, so hand edits count too.', 'Turn on “First run” to see the setup screen shown when only template node 1999 exists.'],
  nodes: ['Replaces node-setup’s node select menu. Add node opens the wizard.', 'The row menu offers Rename and Remove. Remove asks for your password again if it is more than 10 minutes old.'],
  node: ['Tabs replace the “AllStar Node Setup Menu” items 1–8 and C.', 'Every write shows a diff first, or a clear summary for simple values, and is applied all-or-nothing.', 'Tuning is native: sliders and a live level meter. The CLI commands behind it (the <code>susb tune</code> / <code>radio tune</code> families) still need to be confirmed against the tune menus.', 'Access control writes the AstDB allowlist/denylist and needs no restart. As in node-setup, only one list type can be active at a time.', 'Tuning sends <code>susb tune menu-support</code> commands. Settings are read from the stable CSV form (<code>menu-support 0+4</code>). The live meter and status come from the driver’s display loops, streamed and parsed. Proposed upstream: numeric “once” variants, like the existing <code>Y</code>.', 'One tuning session per driver: the driver has a single global active device. Turn on “Tune menu running over SSH” to see the conflict warning.', 'Save calls the driver’s own save (<code>menu-support j</code>), then shows what changed, with Undo from a snapshot. USBRadio nodes also get guided calibration steps for noise, CTCSS and voice.', 'Open classic tune menu runs only the text tune menu, as the asterisk user, for anything this page does not cover.'],
  asterisk: ['Status, settings (AMI secret, IAX port) and an Asterisk-only console. There is no system shell, as decided.', 'Before running <code>module reload</code>, <code>core reload</code>, <code>rpt restart</code> or <code>core restart …</code>, the console checks rpt.conf and warns if app_rpt would disable every node. Try <code>module reload app_rpt</code>.', 'Changing the AMI secret also updates allmon3.ini through the privileged helper.'],
  diagnostics: ['“Node connectivity check” runs <code>asl-node-auth-check</code> as the asterisk user. No privilege is needed. The grouped results assume a proposed <code>--json</code> mode.', 'It runs only on demand, because it takes about 30 seconds and calls rate-limited AllStarLink services. The last result is cached and shown on the Overview page.', 'It replaces asl-menu’s “Check registration server” and “Show registrations” items, because it covers both in more depth.', 'Turn on “Port forwarding broken” to see failures with fix-it hints.'],
  backups: ['Restore shows what will happen to each archive entry before anything is written. The red and orange rows are examples of the safety checks.', 'Upload backup goes beyond asl3-menu’s features. Removing it is fine.', 'The --post-exec hook is deliberately not exposed in the web UI.'],
  config: ['Named “Manual Config Edit” and placed under an “Expert” badge to discourage casual use.', 'The editor in this mockup is a plain textarea. The product uses CodeMirror 6.', 'Status levels follow what Asterisk actually does. <b>Error</b>: Asterisk rejects the whole file (main/config.c returns −1), or a node cannot come up. <b>Warning</b>: the file loads, but something is ignored. Every rule cites its source and is checked by a conformance test against real Asterisk.', 'The rpt.conf sample has an error, the misspelled template <code>node-mian</code>, and a warning, <code>duplex</code> set twice. Toggle “rpt.conf has an error” to remove the error.', 'Restart Asterisk always checks rpt.conf first. With errors present it offers <b>Fix in editor</b> before <b>Restart anyway</b>.', 'Turn on “voter.conf owned by root” to see detection and Fix permissions.'],
  planned: ['Placeholders showing where the planned modules fit. They are not built in phase 1.'],
};
function notesKey() { if (!S.authed) return 'login'; const r = S.route; if (r.startsWith('node-')) return 'node'; if (r.startsWith('edit-')) return 'config'; if (r.startsWith('planned-')) return 'planned'; return NOTES[r] ? r : 'overview'; }
function renderNotes() {
  const p = $('#mock-panel'); p.hidden = !S.notesOpen;
  $('#mock-fab').innerHTML = S.notesOpen ? `${ic('times')} Close notes` : `${ic('sticky-note')} Mockup notes`;
  if (!S.notesOpen) return;
  const sims = [['restart', 'Restart pending'], ['stopped', 'Asterisk stopped'], ['portFail', 'Port forwarding broken'], ['rptError', 'rpt.conf has an error'], ['tuiRunning', 'Tune menu running over SSH'], ['firstRun', 'First run (template node only)'], ['rootOwned', 'voter.conf owned by root'], ['mfa', 'Account has 2FA (login)'], ['http', 'Plain HTTP (login)']];
  p.innerHTML = `<div><span class="tag">MOCKUP</span><h2 style="margin-top:.5rem">ASL Web UI · phase 1 screens</h2><p class="small">Clickable design mockup. All data is made up, and nothing connects to a real node. This panel is not part of the product.</p></div>
    <div><h3>On this screen</h3><ul>${(NOTES[notesKey()] || []).map((n) => `<li>${n}</li>`).join('')}</ul></div>
    <div><h3>Scenarios</h3><div class="sim">${sims.map(([k, l]) => `<label><input type="checkbox" data-sim="${k}" ${S.sim[k] ? 'checked' : ''}> ${l}</label>`).join('')}</div></div>
    <div><h3>Shortcuts</h3><div class="row">${B('Log out', { sm: true, act: 'logout' })}${B('Expire password window', { sm: true, act: 'expireAuth' })}</div></div>`;
}
A.expireAuth = () => { S.lastAuth = 0; toast('info', 'The next protected action will ask for your password'); };

render();
