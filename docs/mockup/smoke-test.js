const fs = require('fs');
const el = () => new Proxy({ style: {}, classList: { toggle() {}, contains() { return false; } }, dataset: {} }, { get: (t, k) => (k in t ? t[k] : (typeof k === 'string' && /^(focus|setSelectionRange|addEventListener|getBoundingClientRect|click)$/.test(k) ? () => ({}) : undefined)), set: (t, k, v) => { t[k] = v; return true; } });
global.document = { documentElement: { getAttribute: () => null, classList: { toggle() {} } }, querySelector: (s) => (/^#(app|modal-root|toasts|mock-panel|mock-fab)$/.test(s) ? el() : null), getElementById: () => null, addEventListener() {} };
global.window = { addEventListener() {}, scrollTo() {}, open() {} };
global.location = { hash: '', pathname: '/' }; global.history = { replaceState() {} };
global.matchMedia = () => ({ matches: false, addEventListener() {} });
global.MutationObserver = class { observe() {} };
global.getComputedStyle = () => ({ lineHeight: '18' });
const src = fs.readFileSync(process.argv[2], 'utf8') + `
;S.authed = true;
const probs = lintRpt(rptConf());
console.log('findings:', probs.map(p => p.sev + '@' + p.line + ' ' + p.msg.replace(/<[^>]+>/g, '')).join(' | '));
S.sim.rptError = false; console.log('without error:', lintRpt(rptConf()).map(p => p.sev + '@' + p.line).join(','));
S.sim.rptError = true;
for (const r of ['overview','nodes','node-63001','node-1001','asterisk','diagnostics','backups','config','edit-rpt.conf','edit-voter.conf','planned-sounds']) {
  S.route = r; for (const t of ['general','interface','tuning','access','customizations']) { S.tab.node = t; render(); }
}
for (const t of ['status','settings','console']) { S.tab.asterisk = t; S.route='asterisk'; render(); }
for (const t of ['local','cloud','settings']) { S.tab.backups = t; S.route='backups'; render(); }
S.editor = null; A.restartAsterisk(); console.log('gate opened:', /Fix in editor/.test(S.modal));
S.sim.rptError = false; S.editor = null; A.restartAsterisk(); console.log('normal confirm:', /Restart Asterisk\\?/.test(S.modal));
startWizard('add'); console.log('wizard ok:', /pf-v6-c-wizard/.test(S.modal));
stopTimers(); console.log('ALL PAGES RENDERED');
`;
eval(src);
