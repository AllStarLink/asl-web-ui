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
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Spinner,
  Title,
} from "@patternfly/react-core";
import ExclamationTriangleIcon from "@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon";
import TimesCircleIcon from "@patternfly/react-icons/dist/esm/icons/times-circle-icon";
import InfoCircleIcon from "@patternfly/react-icons/dist/esm/icons/info-circle-icon";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Diagnostic, linter, lintGutter } from "@codemirror/lint";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { EditorState } from "@codemirror/state";
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import { ApiError, message as errorText } from "./api";
import { fixOwnership } from "./backupsApi";
import { useReauth } from "./Reauth";
import { asteriskConf } from "./asteriskConf";
import { applyPlan, checkFile, FileContent, Finding, Plan, planFile, readFile } from "./configApi";
import { CountLabels } from "./ConfigFiles";
import { DiffView } from "./DiffView";

// Colors come from CSS variables so they follow the light/dark theme.
export const highlight = HighlightStyle.define([
  { tag: tags.comment, color: "var(--asl-hl-comment)" },
  { tag: tags.heading, color: "var(--asl-hl-section)", fontWeight: "600" },
  { tag: tags.keyword, color: "var(--asl-hl-directive)" },
  { tag: tags.propertyName, color: "var(--asl-hl-key)" },
  { tag: tags.string, color: "var(--asl-hl-value)" },
  { tag: tags.operator, color: "var(--asl-hl-comment)" },
]);

export const editorTheme = EditorView.theme({
  "&": { height: "min(62vh, 40rem)", fontSize: "0.85rem" },
  ".cm-scroller": { fontFamily: '"Red Hat Mono", "DejaVu Sans Mono", monospace' },
});

const SEVERITY: Record<Finding["severity"], Diagnostic["severity"]> = { error: "error", warning: "warning", info: "info" };

function icon(severity: Finding["severity"]) {
  if (severity === "error") return <TimesCircleIcon className="asl-err" />;
  if (severity === "warning") return <ExclamationTriangleIcon className="asl-warn" />;
  return <InfoCircleIcon className="asl-info" />;
}

export function ConfigEditor({ name }: { name: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const [file, setFile] = useState<FileContent | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ variant: "success" | "danger" | "warning"; text: string } | null>(null);
  const [reauthElement, withReauth] = useReauth();

  const fix = async () => {
    try {
      if (await withReauth(() => fixOwnership([name]))) {
        setMessage({ variant: "success", text: `${name} belongs to the asterisk user again.` });
        await load();
      }
    } catch (err) {
      setMessage({ variant: "danger", text: errorText(err) });
    }
  };

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const f = await readFile(name);
      setFile(f);
      setFindings(f.findings);
      setDirty(false);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : String(e));
    }
  }, [name]);

  useEffect(() => {
    void load();
  }, [load]);

  // Build the editor whenever a (re)loaded file arrives.
  useEffect(() => {
    if (!file || !host.current) return;
    const readOnly = !file.writable || !file.utf8;
    const lint = linter(
      async (v) => {
        const doc = v.state.doc;
        try {
          const res = await checkFile(name, doc.toString());
          setFindings(res.findings);
          return res.findings
            .filter((f) => f.file === name && f.line !== null && f.line <= doc.lines)
            .map((f) => {
              const line = doc.line(f.line as number);
              return { from: line.from, to: line.to, severity: SEVERITY[f.severity], message: `${f.message}\n${f.why}` };
            });
        } catch {
          return [];
        }
      },
      { delay: 700 },
    );
    const state = EditorState.create({
      doc: file.content,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        drawSelection(),
        history(),
        search({ top: true }),
        highlightSelectionMatches(),
        keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]),
        asteriskConf,
        syntaxHighlighting(highlight),
        editorTheme,
        lintGutter(),
        lint,
        EditorState.readOnly.of(readOnly),
        EditorView.editable.of(!readOnly),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) setDirty(u.state.doc.toString() !== file.content);
        }),
      ],
    });
    const v = new EditorView({ state, parent: host.current });
    view.current = v;
    return () => {
      v.destroy();
      view.current = null;
    };
  }, [file, name]);

  const goToLine = (line: number) => {
    const v = view.current;
    if (!v || line > v.state.doc.lines) return;
    const pos = v.state.doc.line(line).from;
    v.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
    v.focus();
  };

  const review = async () => {
    if (!view.current || !file) return;
    setBusy(true);
    setMessage(null);
    try {
      setPlan(await planFile(name, view.current.state.doc.toString(), file.hash));
    } catch (e) {
      setMessage({ variant: "danger", text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const save = async (confirmErrors: boolean) => {
    if (!plan) return;
    setBusy(true);
    try {
      await applyPlan(plan.id, confirmErrors);
      setPlan(null);
      setMessage({ variant: "success", text: `${name} saved. A snapshot of the previous version was kept.` });
      await load();
    } catch (e) {
      setPlan(null);
      setMessage({ variant: "danger", text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
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

  const counts = {
    error: findings.filter((f) => f.severity === "error").length,
    warning: findings.filter((f) => f.severity === "warning").length,
    info: findings.filter((f) => f.severity === "info").length,
  };

  return (
    <>
      {reauthElement}
      <PageSection className="asl-page-head">
        <Breadcrumb>
          <BreadcrumbItem to="#/config">Manual Config Edit</BreadcrumbItem>
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
                {!file.utf8 && (
                  <Alert variant="warning" isInline title={`${name} is not valid UTF-8, so it is shown read-only`}>
                    Editing it in the browser would change bytes you cannot see. Edit it over SSH instead.
                  </Alert>
                )}
                {file.utf8 && !file.writable && (
                  <Alert variant="warning" isInline title={`${name} is owned by ${file.owner}, so the web interface cannot change it`}
                         actionLinks={<Button variant="link" isInline onClick={fix}>Fix permissions</Button>}>
                    This usually happens after editing it with sudo.
                  </Alert>
                )}
                {message && <Alert variant={message.variant} isInline title={message.text} />}
                <div className="asl-editor-bar">
                  <code>/etc/asterisk/{name}</code>
                  {dirty && <Label color="orange">Unsaved changes</Label>}
                  <span className="asl-spacer" />
                  <Button variant="link" onClick={revert} isDisabled={!dirty}>
                    Revert
                  </Button>
                  <Button variant="secondary" onClick={download}>
                    Download
                  </Button>
                  <Button onClick={review} isDisabled={!dirty || busy} isLoading={busy && !plan}>
                    Save…
                  </Button>
                </div>
                <div ref={host} className="asl-codemirror" />
                <div className="asl-problems">
                  <div className="asl-problems-head">
                    {findings.length ? <CountLabels counts={counts} /> : <Label color="green">No problems found</Label>}
                  </div>
                  {findings.length > 0 && (
                    <ul>
                      {findings.map((f, i) => (
                        <li key={i}>
                          {icon(f.severity)}
                          {f.file === name && f.line ? (
                            <Button variant="link" isInline onClick={() => goToLine(f.line as number)}>
                              Line {f.line}
                            </Button>
                          ) : (
                            <span className="asl-sub">
                              {f.file}
                              {f.line ? `:${f.line}` : ""}
                            </span>
                          )}
                          <span className="asl-problem-text">
                            {f.message}
                            <span className="asl-sub">{f.why}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </CardBody>
          </Card>
        )}
      </PageSection>

      <Modal isOpen={plan !== null} onClose={() => setPlan(null)} variant="large" aria-labelledby="save-title">
        <ModalHeader title={`Save ${name}?`} labelId="save-title" titleIconVariant={plan?.counts.error ? "danger" : undefined} />
        <ModalBody>
          {plan && (
            <div className="asl-stack">
              {plan.stale && (
                <Alert variant="warning" isInline title="The file changed on disk since you opened it">
                  Saving will fail. Reload the file to see the current version.
                </Alert>
              )}
              {plan.counts.error > 0 && (
                <Alert variant="danger" isInline title={`Asterisk would reject ${name}`}>
                  <ul>
                    {plan.findings
                      .filter((f) => f.severity === "error")
                      .map((f, i) => (
                        <li key={i}>
                          {f.line ? `Line ${f.line}: ` : ""}
                          {f.message}
                        </li>
                      ))}
                  </ul>
                  <p>{plan.findings.find((f) => f.severity === "error")?.why}</p>
                </Alert>
              )}
              {plan.unchanged ? <Content component="p">No changes.</Content> : <DiffView diff={plan.diff} />}
              <Content component="p" className="asl-sub">
                The file is checked again just before saving; if it changed on disk, nothing is written.
              </Content>
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          {plan && plan.counts.error > 0 ? (
            <Button variant="danger" onClick={() => save(true)} isLoading={busy} isDisabled={busy}>
              Save anyway
            </Button>
          ) : (
            <Button onClick={() => save(false)} isLoading={busy} isDisabled={busy || plan?.unchanged}>
              Save
            </Button>
          )}
          <Button variant="link" onClick={() => setPlan(null)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
