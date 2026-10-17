import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Card,
  CardBody,
  CardTitle,
  Content,
  Label,
  PageSection,
  Spinner,
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import CheckCircleIcon from "@patternfly/react-icons/dist/esm/icons/check-circle-icon";
import ExclamationTriangleIcon from "@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon";
import FolderIcon from "@patternfly/react-icons/dist/esm/icons/folder-icon";
import TimesCircleIcon from "@patternfly/react-icons/dist/esm/icons/times-circle-icon";

import { ApiError, message } from "./api";
import { size } from "./backupsApi";
import { Counts, FileSummary, listFiles, listSystemFiles, listTree, SystemFile, SystemFiles, TreeEntry } from "./configApi";
import { PlainTextInput } from "./PlainInput";

export function CountLabels({ counts }: { counts: Counts | null }) {
  if (!counts) return null;
  if (!counts.error && !counts.warning) return <Label color="green" icon={<CheckCircleIcon />}>OK</Label>;
  return (
    <span className="asl-labels">
      {counts.error > 0 && (
        <Label color="red" icon={<TimesCircleIcon />}>
          {counts.error} error{counts.error > 1 ? "s" : ""}
        </Label>
      )}
      {counts.warning > 0 && (
        <Label color="orange" icon={<ExclamationTriangleIcon />}>
          {counts.warning} warning{counts.warning > 1 ? "s" : ""}
        </Label>
      )}
    </span>
  );
}

function when(epoch: number | null): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function Owner({ owner, writable }: { owner: string | null; writable: boolean }) {
  if (owner && !writable) {
    return <Label color="orange" icon={<ExclamationTriangleIcon />}>{owner}: read-only</Label>;
  }
  return <code className="asl-sub">{owner ?? "—"}</code>;
}

// The folder part of a path ("" for the top level) and the file name.
function split(path: string): [string, string] {
  const i = path.lastIndexOf("/");
  return i < 0 ? ["", path] : [path.slice(0, i + 1), path.slice(i + 1)];
}

function readBy(f: TreeEntry) {
  if (f.link) return <span className="asl-sub">Link to {f.link}</span>;
  if (f.read_by.length === 0) return <span className="asl-sub">—</span>;
  if (f.read_by[0] === "Asterisk") return "Asterisk";
  return <span>Included by {f.read_by.join(", ")}</span>;
}

function AsteriskTree({ files, filter }: { files: TreeEntry[]; filter: string }) {
  const groups = useMemo(() => {
    const out = new Map<string, TreeEntry[]>();
    const want = filter.toLowerCase();
    for (const f of files) {
      if (want && !f.name.toLowerCase().includes(want)) continue;
      const [folder] = split(f.name);
      out.set(folder, [...(out.get(folder) ?? []), f]);
    }
    return [...out.entries()];
  }, [files, filter]);
  if (!groups.length) return <Content component="p" className="asl-sub">No file matches.</Content>;
  return (
    <Table aria-label="Files in /etc/asterisk" variant="compact">
      <Thead>
        <Tr>
          <Th>File</Th>
          <Th>Read by</Th>
          <Th>Size</Th>
          <Th>Modified</Th>
          <Th>Owner</Th>
        </Tr>
      </Thead>
      <Tbody>
        {groups.map(([folder, entries]) => (
          <Fragment key={folder}>
            {folder && (
              <Tr className="asl-folder-row">
                <Td colSpan={5}><FolderIcon /> <code>{folder}</code></Td>
              </Tr>
            )}
            {entries.map((f) => (
              <Tr key={f.name}>
                <Td dataLabel="File" className={folder ? "asl-indent" : undefined}>
                  {f.link ? (
                    <code className="asl-sub">{split(f.name)[1]}</code>
                  ) : (
                    <a href={`#/config/${encodeURIComponent(f.name)}`}><code>{split(f.name)[1]}</code></a>
                  )}
                </Td>
                <Td dataLabel="Read by">{readBy(f)}</Td>
                <Td dataLabel="Size">{f.link ? "—" : size(f.size)}</Td>
                <Td dataLabel="Modified">{when(f.modified)}</Td>
                <Td dataLabel="Owner">{f.link ? "—" : <Owner owner={f.owner} writable={f.writable} />}</Td>
              </Tr>
            ))}
          </Fragment>
        ))}
      </Tbody>
    </Table>
  );
}

function SystemTable({ label, files, filter }: { label: string; files: SystemFile[]; filter: string }) {
  const want = filter.toLowerCase();
  const shown = files.filter((f) => !want || f.path.toLowerCase().includes(want));
  if (!shown.length) return <Content component="p" className="asl-sub">No file matches.</Content>;
  const link = (f: SystemFile) =>
    f.path === "/etc/sa818.conf" ? "#/config/~sa818" : `#/config/~allmon3/${encodeURIComponent(split(f.path)[1])}`;
  return (
    <Table aria-label={label} variant="compact">
      <Thead>
        <Tr>
          <Th>File</Th>
          <Th>Access</Th>
          <Th>Size</Th>
          <Th>Modified</Th>
          <Th>Owner</Th>
        </Tr>
      </Thead>
      <Tbody>
        {shown.map((f) => (
          <Tr key={f.path}>
            <Td dataLabel="File">
              {f.readable ? <a href={link(f)}><code>{split(f.path)[1]}</code></a> : <code className="asl-sub">{split(f.path)[1]}</code>}
            </Td>
            <Td dataLabel="Access">
              {!f.readable ? (
                <span className="asl-sub">
                  Password hashes: manage the users on <a href="#/allmon3/users">Allmon3 › Users</a>
                </span>
              ) : f.writable ? "Editable" : <span className="asl-sub">Read-only (not read by Allmon3)</span>}
            </Td>
            <Td dataLabel="Size">{size(f.size)}</Td>
            <Td dataLabel="Modified">{when(f.modified)}</Td>
            <Td dataLabel="Owner"><code className="asl-sub">{f.owner}</code></Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

function AllFiles() {
  const [tab, setTab] = useState<string | number>("asterisk");
  const [filter, setFilter] = useState("");
  const [tree, setTree] = useState<{ files: TreeEntry[]; truncated: boolean } | null>(null);
  const [system, setSystem] = useState<SystemFiles | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [systemError, setSystemError] = useState<string | null>(null);

  useEffect(() => {
    listTree().then(setTree, (e) => setTreeError(message(e)));
    listSystemFiles().then(setSystem, (e) => setSystemError(message(e)));
  }, []);

  const count = (n: number | undefined) => (n === undefined ? "" : ` (${n})`);
  return (
    <Card className="asl-gap">
      <CardTitle>All files</CardTitle>
      <CardBody>
        <div className="asl-stack">
          <Tabs activeKey={tab} onSelect={(_e, key) => setTab(key)} aria-label="Configuration folders">
            <Tab eventKey="asterisk" title={<TabTitleText>/etc/asterisk{count(tree?.files.length)}</TabTitleText>} />
            <Tab eventKey="allmon3" title={<TabTitleText>/etc/allmon3{count(system?.allmon3?.length)}</TabTitleText>} />
            <Tab eventKey="sa818" title={<TabTitleText>SA818</TabTitleText>} />
          </Tabs>
          {tab !== "sa818" && (
            <PlainTextInput aria-label="Filter by name" placeholder="Filter by name" value={filter}
                            onChange={(_e, v) => setFilter(v)} className="asl-filter" type="search" />
          )}
          {tab === "asterisk" && (
            <>
              {treeError && <Alert variant="danger" isInline title={treeError} />}
              {!tree && !treeError && <Spinner aria-label="Loading" />}
              {tree?.truncated && (
                <Alert variant="warning" isInline isPlain title="Only the first files are listed" />
              )}
              {tree && <AsteriskTree files={tree.files} filter={filter} />}
              <Content component="p" className="asl-sub">
                Files under custom/ are read when one of the main files includes them (#tryinclude), and are
                checked as part of that file. Files Asterisk does not read are not checked.
              </Content>
            </>
          )}
          {tab !== "asterisk" && systemError && <Alert variant="danger" isInline title={systemError} />}
          {tab !== "asterisk" && !system && !systemError && <Spinner aria-label="Loading" />}
          {tab === "allmon3" && system && (
            system.allmon3 ? (
              <>
                <SystemTable label="Files in /etc/allmon3" files={system.allmon3} filter={filter} />
                <Content component="p" className="asl-sub">
                  Saving one of Allmon3's files restarts Allmon3. Most of its settings are also on the{" "}
                  <a href="#/allmon3">Allmon3</a> page.
                </Content>
              </>
            ) : (
              <Content component="p" className="asl-sub">Allmon3 is not installed (/etc/allmon3 does not exist).</Content>
            )
          )}
          {tab === "sa818" && system && (
            system.sa818 ? (
              <>
                <SystemTable label="SA818 settings" files={[system.sa818]} filter="" />
                <Content component="p" className="asl-sub">
                  The settings of an SA818 radio module, as sa818-menu and the <a href="#/hardware/sa818">Hardware</a> page store
                  them. Saving the file does not program the module.
                </Content>
              </>
            ) : (
              <Content component="p" className="asl-sub">
                /etc/sa818.conf does not exist. It is created when you save settings on the SA818 tab of the
                Hardware page.
              </Content>
            )
          )}
        </div>
      </CardBody>
    </Card>
  );
}

export function ConfigFiles() {
  const [files, setFiles] = useState<FileSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listFiles().then((r) => setFiles(r.files), (e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Manual Config Edit</Title>
      </PageSection>
      <PageSection>
        <Alert variant="danger" isInline title="For experienced users only">
          <p>
            These are the raw Asterisk, app_rpt, Allmon3 and SA818 configuration files. A mistake here can take your
            node off the air or stop Asterisk from starting.
          </p>
          <p>
            Every save of a file in /etc/asterisk keeps a snapshot of the previous version. Problems Asterisk or
            Allmon3 would refuse are shown before you save.
          </p>
        </Alert>
      </PageSection>
      <PageSection>
        <Card>
          <CardTitle>Main configuration files</CardTitle>
          <CardBody>
            {error && <Alert variant="danger" isInline title={error} />}
            {!files && !error && <Spinner aria-label="Loading" />}
            {files && (
              <Table aria-label="Configuration files" variant="compact">
                <Thead>
                  <Tr>
                    <Th>File</Th>
                    <Th>Contains</Th>
                    <Th>Modified</Th>
                    <Th>Owner</Th>
                    <Th>Status</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {files.map((f) => (
                    <Tr key={f.name}>
                      <Td dataLabel="File">
                        {f.exists ? (
                          <a href={`#/config/${encodeURIComponent(f.name)}`}>
                            <code>{f.name}</code>
                          </a>
                        ) : (
                          <code className="asl-sub">{f.name}</code>
                        )}
                      </Td>
                      <Td dataLabel="Contains">{f.purpose}</Td>
                      <Td dataLabel="Modified">{f.exists ? when(f.modified) : "Not present"}</Td>
                      <Td dataLabel="Owner">
                        {f.exists ? <Owner owner={f.owner} writable={f.writable} /> : <code className="asl-sub">—</code>}
                      </Td>
                      <Td dataLabel="Status">{f.exists && <CountLabels counts={f.counts} />}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </CardBody>
        </Card>
        <Content component="p" className="asl-sub asl-gap">
          Most settings can be changed safely on the other pages. Files are in /etc/asterisk.
        </Content>
        <AllFiles />
      </PageSection>
    </>
  );
}
