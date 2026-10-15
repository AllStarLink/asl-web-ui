import { useCallback, useEffect, useRef, useState } from "react";
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
import { Allmon3File, Allmon3Finding, checkAllmon3File, deleteAllmon3File, planAllmon3File, readAllmon3File } from "./allmon3Api";
import { Findings, useAllmon3Review } from "./Allmon3Review";
import { asteriskConf } from "./asteriskConf";
import { editorTheme, highlight } from "./ConfigEditor";
import { useLeaveGuard } from "./useRoute";

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

export function Allmon3Editor({ name }: { name: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const [file, setFile] = useState<Allmon3File | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [findings, setFindings] = useState<Allmon3Finding[]>([]);
  const [notice, setNotice] = useState<{ variant: "success" | "danger" | "warning"; text: string } | null>(null);
  const [reviewElement, review] = useAllmon3Review();

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const f = await readAllmon3File(name);
      setFile(f);
      setFindings(f.findings);
      setDirty(false);
    } catch (err) {
      setLoadError(message(err));
    }
  }, [name]);

  useEffect(() => {
    void load();
  }, [load]);

  const stays = useCallback((r: string) => r === `allmon3/files/${name}`, [name]);
  useLeaveGuard(dirty ? stays : null);

  useEffect(() => {
    if (!file || !host.current) return;
    const start = file.exists ? file.content : name === "menu.ini" ? MENU_STARTER : "";
    const lint = linter(async (v) => {
      const doc = v.state.doc;
      try {
        const res = await checkAllmon3File(name, doc.toString());
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
          ...(name === "custom.css" ? [] : [asteriskConf, syntaxHighlighting(highlight)]),
          editorTheme, lintGutter(), lint,
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
  }, [file, name]);

  const save = async () => {
    if (!view.current || !file) return;
    setNotice(null);
    try {
      const applied = await review(planAllmon3File(name, view.current.state.doc.toString(), file.hash));
      if (!applied) return;
      setNotice(applied.warnings.length ? { variant: "warning", text: applied.warnings.join(" ") }
        : { variant: "success", text: `${name} saved and Allmon3 restarted.` });
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

  const remove = async () => {
    if (!file) return;
    try {
      const res = await deleteAllmon3File(name, file.hash);
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
          <BreadcrumbItem to="#/allmon3/files">Allmon3</BreadcrumbItem>
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
                {HELP[name] && <Content component="p" className="asl-sub">{HELP[name]}</Content>}
                {!file.exists && name === "menu.ini" && (
                  <Alert variant="info" isInline title="There is no custom menu yet">
                    Allmon3 lists every node in its sidebar. Saving this file replaces that list with your menu.
                  </Alert>
                )}
                {!file.exists && name !== "menu.ini" && (
                  <Alert variant="warning" isInline title={`${file.path} does not exist`}>Is Allmon3 installed?</Alert>
                )}
                {notice && <Alert variant={notice.variant} isInline title={notice.text} />}
                <div className="asl-editor-bar">
                  <code>{file.path}</code>
                  {dirty && <Label color="orange">Unsaved changes</Label>}
                  <span className="asl-spacer" />
                  {file.exists && file.optional && (
                    <Button variant="link" isDanger onClick={remove}>Remove the custom menu</Button>
                  )}
                  <Button variant="link" onClick={revert} isDisabled={!dirty || !file.exists}>Revert</Button>
                  <Button onClick={save} isDisabled={!dirty || (!file.exists && !file.optional)}>Save…</Button>
                </div>
                <div ref={host} className="asl-codemirror" />
                {findings.length > 0 ? <Findings findings={findings} />
                  : <Label color="green">No problems found</Label>}
              </div>
            </CardBody>
          </Card>
        )}
      </PageSection>
      {reviewElement}
    </>
  );
}
