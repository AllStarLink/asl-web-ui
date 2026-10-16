import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Card,
  CardBody,
  Content,
  Label,
  PageSection,
  Spinner,
  Title,
} from "@patternfly/react-core";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { syntaxHighlighting } from "@codemirror/language";
import { linter, lintGutter } from "@codemirror/lint";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { EditorState } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";

import { message } from "./api";
import {
  Allmon3Applied,
  Allmon3File,
  Allmon3Finding,
  Allmon3Plan,
  Allmon3Unchanged,
  checkAllmon3File,
  deleteAllmon3File,
  planAllmon3File,
  readAllmon3File,
} from "./allmon3Api";
import { Findings, ReviewTarget, useAllmon3Review } from "./Allmon3Review";
import { asteriskConf } from "./asteriskConf";
import { editorTheme, highlight } from "./ConfigEditor";
import { applySA818FilePlan, checkSA818File, planSA818File, readSA818File } from "./sa818Api";
import { useLeaveGuard } from "./useRoute";

// Files outside /etc/asterisk, read and written through the privileged
// helper: Allmon3's (opened from the Allmon3 page or Manual Config Edit) and
// the SA818 settings (Manual Config Edit).
type Source = {
  name: string;
  read: () => Promise<Allmon3File>;
  check: (content: string) => Promise<{ findings: Allmon3Finding[] }>;
  plan: (content: string, hash: string) => Promise<Allmon3Plan | Allmon3Unchanged>;
  remove?: (hash: string) => Promise<Allmon3Applied>;
  target?: ReviewTarget;
  crumb: { label: string; to: string };
  route: string; // this page, for the leave guard
  saved: string;
  missing: string; // what to say when the file does not exist
  readOnly: string; // why a file cannot be changed here
  help?: string;
  starter?: string;
  highlight: boolean;
};

// What a new menu.ini starts from: Allmon3's own example, ready to edit.
const MENU_STARTER = `; Allmon3's sidebar menu. Without this file, every node in allmon3.ini is listed.
;
; [ TITLE ]          the label of a menu
; type = menu        a drop-down menu of the entries below
; type = single      only the first entry, as a plain link
; LABEL = TARGET     TARGET is a node number, several nodes (#1999,1998),
;                    or a web address (add _blank at the end to open it in
;                    a new tab)

[ My nodes ]
type = menu
Hub = 1999

[ AllStarLink ]
type = single
Community = https://community.allstarlink.org/_blank
`;

const HELP: Record<string, string> = {
  "web.ini": "The [syscmds] section lists the commands offered in Allmon3's command dialog as COMMAND = LABEL; " +
    "@ stands for the node the dialog was opened from and % for the node selected in its table. [syscmds-NODE] " +
    "adds commands for one node. [node-overrides] replaces a node's description (NODE = TEXT), " +
    "[voter-titles] names voters. The four sections must exist, even if empty.",
  "menu.ini": "Each [ TITLE ] is a menu in Allmon3's sidebar; type = menu makes it a drop-down, type = single a " +
    "plain link. LABEL = TARGET entries point at a node number, several nodes (#1999,1998) or a web address.",
  "user-restrictions": "One line per user who may send commands only to some nodes: USER | NODE,NODE. Users " +
    "not listed may command every node. Lines starting with # are comments.",
  "allmon3.ini": "One [NODE] section per node: host, port, user and pass of its Asterisk manager (AMI). The " +
    "Nodes tab edits these for you.",
  "custom.css": "CSS rules added to Allmon3's pages.",
};

const SEVERITY = { error: "error", warning: "warning", info: "info" } as const;

export function Allmon3Editor({ name, from }: { name: string; from?: "config" }) {
  const source = useMemo<Source>(() => ({
    name,
    read: () => readAllmon3File(name),
    check: (content) => checkAllmon3File(name, content),
    plan: (content, hash) => planAllmon3File(name, content, hash),
    remove: name === "menu.ini" ? (hash) => deleteAllmon3File(name, hash) : undefined,
    crumb: from === "config" ? { label: "Manual Config Edit", to: "#/config" } : { label: "Allmon3", to: "#/allmon3/files" },
    route: from === "config" ? `config/~allmon3/${encodeURIComponent(name)}` : `allmon3/files/${name}`,
    saved: `${name} saved and Allmon3 restarted.`,
    missing: "Is Allmon3 installed?",
    readOnly: "Allmon3 does not read this file, so it is shown for reference only. Some of these files are web "
      + "server configuration, which the web interface may not change.",
    help: HELP[name],
    starter: name === "menu.ini" ? MENU_STARTER : undefined,
    highlight: name !== "custom.css" && name !== "Makefile",
  }), [name, from]);
  return <SystemFileEditor source={source} />;
}

const SA818_TARGET: ReviewTarget = {
  apply: applySA818FilePlan,
  dir: "/etc",
  note: "The module keeps its old settings until you program it again on the SA818 page.",
  errorsBlock: true,
  errorsTitle: "sa818-menu runs this file as root, so it can hold only the settings",
};

export function SA818FileEditor() {
  const source = useMemo<Source>(() => ({
    name: "sa818.conf",
    read: readSA818File,
    check: checkSA818File,
    plan: planSA818File,
    target: SA818_TARGET,
    crumb: { label: "Manual Config Edit", to: "#/config" },
    route: "config/~sa818",
    saved: "sa818.conf saved. Program the module on the SA818 page to use the new settings.",
    missing: "Save the settings on the SA818 page first.",
    readOnly: "",
    help: "The SA818 page's settings as sa818-menu stores them: one KEY=VALUE line each. sa818-menu loads this file "
      + "as a shell script as root, so only these settings, comments (#) and blank lines can be saved.",
    highlight: true,
  }), []);
  return <SystemFileEditor source={source} />;
}

function SystemFileEditor({ source }: { source: Source }) {
  const name = source.name;
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const [file, setFile] = useState<Allmon3File | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [findings, setFindings] = useState<Allmon3Finding[]>([]);
  const [notice, setNotice] = useState<{ variant: "success" | "danger" | "warning"; text: string } | null>(null);
  const [reviewElement, review] = useAllmon3Review(source.target);
  const editable = file !== null && file.writable;

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const f = await source.read();
      setFile(f);
      setFindings(f.findings);
      setDirty(false);
    } catch (err) {
      setLoadError(message(err));
    }
  }, [source]);

  useEffect(() => {
    void load();
  }, [load]);

  const stays = useCallback((r: string) => r === source.route, [source]);
  useLeaveGuard(dirty ? stays : null);

  useEffect(() => {
    if (!file || !host.current) return;
    const start = file.exists ? file.content : source.starter ?? "";
    const lint = linter(async (v) => {
      const doc = v.state.doc;
      try {
        const res = await source.check(doc.toString());
        setFindings(res.findings);
        return res.findings.filter((f) => f.line !== null && f.line <= doc.lines).map((f) => {
          const line = doc.line(f.line as number);
          return { from: line.from, to: line.to, severity: SEVERITY[f.severity], message: f.message };
        });
      } catch {
        return [];
      }
    }, { delay: 600 });
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: start,
        extensions: [
          lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(), drawSelection(), history(),
          search({ top: true }), highlightSelectionMatches(),
          keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]),
          ...(source.highlight ? [asteriskConf, syntaxHighlighting(highlight)] : []),
          editorTheme, lintGutter(), lint,
          EditorState.readOnly.of(!file.writable),
          EditorView.editable.of(file.writable),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) setDirty(u.state.doc.toString() !== (file.exists ? file.content : ""));
          }),
        ],
      }),
    });
    view.current = v;
    if (!file.exists) setDirty(start !== "");
    return () => {
      v.destroy();
      view.current = null;
    };
  }, [file, source]);

  const save = async () => {
    if (!view.current || !file) return;
    setNotice(null);
    try {
      const applied = await review(source.plan(view.current.state.doc.toString(), file.hash));
      if (!applied) return;
      setNotice(applied.warnings.length ? { variant: "warning", text: applied.warnings.join(" ") }
        : { variant: "success", text: source.saved });
      await load();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  const revert = () => {
    const v = view.current;
    if (!v || !file) return;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: file.content } });
  };

  const download = () => {
    const v = view.current;
    if (!v) return;
    const url = URL.createObjectURL(new Blob([v.state.doc.toString()], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const remove = async () => {
    if (!file || !source.remove) return;
    try {
      const res = await source.remove(file.hash);
      setNotice(res.warnings.length ? { variant: "warning", text: res.warnings.join(" ") }
        : { variant: "success", text: "The custom menu is removed; Allmon3 lists every node again." });
      await load();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  return (
    <>
      <PageSection className="asl-page-head">
        <Breadcrumb>
          <BreadcrumbItem to={source.crumb.to}>{source.crumb.label}</BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
        </Breadcrumb>
        <Title headingLevel="h1">{name}</Title>
      </PageSection>
      <PageSection>
        {loadError && <Alert variant="danger" isInline title={loadError} />}
        {!file && !loadError && <Spinner aria-label="Loading" />}
        {file && (
          <Card>
            <CardBody>
              <div className="asl-stack">
                {source.help && <Content component="p" className="asl-sub">{source.help}</Content>}
                {!file.writable && <Alert variant="info" isInline title="Read-only">{source.readOnly}</Alert>}
                {!file.exists && name === "menu.ini" && (
                  <Alert variant="info" isInline title="There is no custom menu yet">
                    Allmon3 lists every node in its sidebar. Saving this file replaces that list with your menu.
                  </Alert>
                )}
                {!file.exists && name !== "menu.ini" && (
                  <Alert variant="warning" isInline title={`${file.path} does not exist`}>{source.missing}</Alert>
                )}
                {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
                <div className="asl-editor-bar">
                  <code>{file.path}</code>
                  {dirty && <Label color="orange">Unsaved changes</Label>}
                  <span className="asl-spacer" />
                  {file.exists && file.optional && source.remove && (
                    <Button variant="link" isDanger onClick={remove}>Remove the custom menu</Button>
                  )}
                  {editable ? (
                    <>
                      <Button variant="link" onClick={revert} isDisabled={!dirty || !file.exists}>Revert</Button>
                      <Button onClick={save} isDisabled={!dirty || (!file.exists && !file.optional)}>Save…</Button>
                    </>
                  ) : (
                    <Button variant="secondary" onClick={download}>Download</Button>
                  )}
                </div>
                <div ref={host} className="asl-codemirror" />
                {findings.length > 0 ? <Findings findings={findings} errorsTitle={source.target?.errorsTitle} />
                  : editable && <Label color="green">No problems found</Label>}
              </div>
            </CardBody>
          </Card>
        )}
      </PageSection>
      {reviewElement}
    </>
  );
}
