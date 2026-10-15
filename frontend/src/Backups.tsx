import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Content,
  ExpandableSection,
  Form,
  FormGroup,
  List,
  ListItem,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Spinner,
  Tab,
  Tabs,
  TabTitleText,
  TextArea,
  TextInput,
  Title,
} from "@patternfly/react-core";
import { ActionsColumn, Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import UploadIcon from "@patternfly/react-icons/dist/esm/icons/upload-icon";

import { message } from "./api";
import { useAsteriskControl } from "./AsteriskControl";
import {
  BackupList, backupContents, cloudFetch, cloudList, Contents, createBackup, Credentials, deleteBackup, downloadUrl,
  factoryReset, getIncludeList, importBackup, IncludeList, listBackups, putIncludeList, restoreBackup, size,
  uploadBackup,
} from "./backupsApi";
import { useJob } from "./Job";
import { useReauth } from "./Reauth";
import { go } from "./useRoute";

function when(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// After a restore: offer the Asterisk restart that makes it take effect.
function useAfterRestore() {
  const [controlElement, control] = useAsteriskControl();
  const [open, setOpen] = useState(false);
  const element = (
    <>
      {controlElement}
      <Modal isOpen={open} onClose={() => setOpen(false)} variant="small" aria-labelledby="restored-title">
        <ModalHeader title="Restored" labelId="restored-title" titleIconVariant="success" />
        <ModalBody>Asterisk must restart to use the restored configuration.</ModalBody>
        <ModalFooter>
          <Button onClick={async () => { setOpen(false); await control("restart"); }}>Restart Asterisk now</Button>
          <Button variant="link" onClick={() => setOpen(false)}>Later</Button>
        </ModalFooter>
      </Modal>
    </>
  );
  return { element, show: () => setOpen(true) };
}

function RestoreDialog({ name, onCancel, onRestore }: { name: string; onCancel: () => void; onRestore: () => void }) {
  const [contents, setContents] = useState<Contents | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    backupContents(name).then(setContents, (e) => setError(message(e)));
  }, [name]);
  return (
    <Modal isOpen onClose={onCancel} variant="medium" aria-labelledby="restore-title">
      <ModalHeader title={`Restore ${name}?`} labelId="restore-title" titleIconVariant="warning" />
      <ModalBody>
        <div className="asl-stack">
          {error && <Alert variant="danger" isInline title={error} />}
          {!contents && !error && <Spinner size="md" aria-label="Loading" />}
          {contents && !contents.asl3 && (
            <Alert variant="danger" isInline title="This archive does not appear to have been made on an ASL3 system." />
          )}
          {contents && (
            <>
              <Content component="p">
                {contents.files.length} files are written back, replacing the current ones. The current configuration
                is saved as a backup first, so this can be undone.
              </Content>
              <ExpandableSection toggleText="Files in the backup">
                <pre className="asl-job-log">{contents.files.map((f) => "/" + f).join("\n")}</pre>
              </ExpandableSection>
              {contents.skipped.length > 0 && (
                <Alert variant="warning" isInline title={`${contents.skipped.length} entries are not restored`}>
                  <List>
                    {contents.skipped.slice(0, 20).map((s) => <ListItem key={s.name}>{s.name}: {s.reason}</ListItem>)}
                  </List>
                </Alert>
              )}
            </>
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="danger" onClick={onRestore} isDisabled={!contents?.asl3}>Restore</Button>
        <Button variant="link" onClick={onCancel}>Cancel</Button>
      </ModalFooter>
    </Modal>
  );
}

function ThisServer({ list, reload }: { list: BackupList; reload: () => Promise<void> }) {
  const [jobElement, runJob] = useJob();
  const [reauthElement, withReauth] = useReauth();
  const after = useAfterRestore();
  const [upload, setUpload] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const create = async () => {
    await runJob(upload ? "Create a backup and copy it to AllStarLink" : "Create a backup", () => createBackup(upload));
    await reload();
  };
  const restore = async (name: string) => {
    setRestoring(null);
    const res = await runJob(`Restore ${name}`, () => withReauth(() => restoreBackup(name)));
    await reload();
    if (res?.ok) after.show();
  };
  const remove = async (name: string) => {
    setDeleting(null);
    try {
      await deleteBackup(name);
    } catch (err) {
      setError(message(err));
    }
    await reload();
  };
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    try {
      await importBackup(file);
    } catch (err) {
      setError(message(err));
    }
    await reload();
  };

  return (
    <div className="asl-stack">
      {jobElement}
      {reauthElement}
      {after.element}
      <Card>
        <CardTitle>Create a backup</CardTitle>
        <CardBody>
          <Form onSubmit={(e) => { e.preventDefault(); void create(); }}>
            <Content component="p">
              Saves your node's configuration (the paths in the include list) in <code>{list.directory}</code>.
            </Content>
            <Checkbox id="backup-upload" isChecked={upload} onChange={(_e, v) => setUpload(v)}
                      isDisabled={!list.cloud.configured}
                      label={`Also copy it to the AllStarLink backup server${list.cloud.node ? ` (as node ${list.cloud.node})` : ""}`}
                      description={list.cloud.configured ? undefined : list.cloud.reason ?? undefined} />
            <ActionGroup>
              <Button type="submit">Create backup</Button>
              <Button variant="secondary" icon={<UploadIcon />} onClick={() => fileInput.current?.click()}>
                Add a backup file…
              </Button>
              <input ref={fileInput} type="file" accept=".tgz,application/gzip" hidden onChange={onFile} />
            </ActionGroup>
          </Form>
        </CardBody>
      </Card>
      {error && <Alert variant="danger" isInline title={error} />}
      <Card>
        <CardTitle>Backups on this server</CardTitle>
        <CardBody>
          {list.local.length === 0 ? (
            <Content component="p" className="asl-sub">No backups yet.</Content>
          ) : (
            <Table aria-label="Backups" variant="compact">
              <Thead>
                <Tr>
                  <Th>Backup</Th>
                  <Th>Made</Th>
                  <Th>Size</Th>
                  <Th screenReaderText="Actions" />
                </Tr>
              </Thead>
              <Tbody>
                {list.local.map((b) => (
                  <Tr key={b.name}>
                    <Td dataLabel="Backup"><code>{b.name}</code></Td>
                    <Td dataLabel="Made">{when(b.modified)}</Td>
                    <Td dataLabel="Size">{size(b.size)}</Td>
                    <Td isActionCell>
                      <ActionsColumn items={[
                        { title: "Restore…", onClick: () => setRestoring(b.name) },
                        { title: "Download", onClick: () => { window.location.href = downloadUrl(b.name); } },
                        {
                          title: "Copy to AllStarLink", isDisabled: !list.cloud.configured || b.size > list.cloud_max,
                          onClick: async () => { await runJob(`Copy ${b.name} to AllStarLink`, () => uploadBackup(b.name)); },
                        },
                        { isSeparator: true },
                        { title: "Delete…", isDanger: true, onClick: () => setDeleting(b.name) },
                      ]} />
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>
      {restoring && <RestoreDialog name={restoring} onCancel={() => setRestoring(null)} onRestore={() => restore(restoring)} />}
      <Modal isOpen={deleting !== null} onClose={() => setDeleting(null)} variant="small" aria-labelledby="del-title">
        <ModalHeader title={`Delete ${deleting}?`} labelId="del-title" titleIconVariant="warning" />
        <ModalBody>The backup file is removed from this server. Copies elsewhere are not affected.</ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={() => deleting && remove(deleting)}>Delete</Button>
          <Button variant="link" onClick={() => setDeleting(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}

function Cloud({ list, reload }: { list: BackupList; reload: () => Promise<void> }) {
  const [jobElement, runJob] = useJob();
  const [reauthElement, withReauth] = useReauth();
  const after = useAfterRestore();
  const [node, setNode] = useState("");
  const [password, setPassword] = useState("");
  const [names, setNames] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const creds: Credentials = list.cloud.configured && !node ? {} : { node, password };

  const fetchList = async () => {
    setBusy(true);
    setError(null);
    try {
      setNames((await cloudList(creds)).backups);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const fetch = async (name: string, restore: boolean) => {
    const res = await runJob(restore ? `Restore ${name}` : `Copy ${name} to this server`,
      () => (restore ? withReauth(() => cloudFetch(name, true, creds)) : cloudFetch(name, false, creds)));
    await reload();
    if (restore && res?.ok) after.show();
  };

  return (
    <div className="asl-stack">
      {jobElement}
      {reauthElement}
      {after.element}
      <Card>
        <CardTitle>AllStarLink backup server</CardTitle>
        <CardBody>
          <Form onSubmit={(e) => { e.preventDefault(); void fetchList(); }}>
            <Content component="p">
              AllStarLink keeps backups for registered nodes. {list.cloud.configured
                ? `This server uses node ${list.cloud.node}'s credentials. To see another node's backups, enter its number and password.`
                : "Enter a node number and its password to see that node's backups."}
            </Content>
            <div className="asl-form-row">
              <FormGroup label="Node number" fieldId="cloud-node">
                <TextInput id="cloud-node" value={node} onChange={(_e, v) => setNode(v.trim())}
                           placeholder={list.cloud.node ?? ""} inputMode="numeric" />
              </FormGroup>
              <FormGroup label="Node password" fieldId="cloud-password">
                <TextInput id="cloud-password" type="password" value={password} onChange={(_e, v) => setPassword(v)}
                           autoComplete="off" />
              </FormGroup>
            </div>
            {error && <Alert variant="danger" isInline isPlain title={error} />}
            <ActionGroup>
              <Button type="submit" isLoading={busy} isDisabled={busy || (!list.cloud.configured && (!node || !password))}>
                Show backups
              </Button>
            </ActionGroup>
          </Form>
        </CardBody>
      </Card>
      {names && (
        <Card>
          <CardTitle>Backups on the AllStarLink server</CardTitle>
          <CardBody>
            {names.length === 0 ? <Content component="p">There are no backups for this node.</Content> : (
              <Table aria-label="AllStarLink backups" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Backup</Th>
                    <Th screenReaderText="Actions" />
                  </Tr>
                </Thead>
                <Tbody>
                  {names.map((n) => (
                    <Tr key={n}>
                      <Td dataLabel="Backup"><code>{n}</code></Td>
                      <Td isActionCell>
                        <div className="asl-buttons asl-end">
                          <Button variant="secondary" size="sm" onClick={() => fetch(n, false)}>Copy to this server</Button>
                          <Button variant="secondary" isDanger size="sm" onClick={() => fetch(n, true)}>Restore</Button>
                        </div>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Settings() {
  const [jobElement, runJob] = useJob();
  const [reauthElement, withReauth] = useReauth();
  const after = useAfterRestore();
  const [include, setInclude] = useState<IncludeList | null>(null);
  const [text, setText] = useState("");
  const [state, setState] = useState<{ ok?: string; error?: string } | null>(null);
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = await getIncludeList();
      setInclude(l);
      setText(l.content);
    } catch (err) {
      setState({ error: message(err) });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!include) return;
    try {
      const res = await putIncludeList(text, include.hash);
      setInclude({ ...include, content: text, hash: res.hash, exists: true });
      setState({ ok: "Saved." });
    } catch (err) {
      setState({ error: message(err) });
    }
  };
  const factory = async () => {
    setConfirm(false);
    const res = await runJob("Restore the default configuration", () => withReauth(factoryReset));
    if (res?.ok) after.show();
  };

  return (
    <div className="asl-stack">
      {jobElement}
      {reauthElement}
      {after.element}
      <Card>
        <CardTitle>What a backup contains</CardTitle>
        <CardBody>
          {!include ? <Spinner size="md" aria-label="Loading" /> : (
            <Form onSubmit={(e) => { e.preventDefault(); void save(); }}>
              <Content component="p">
                One file or directory per line. Lines starting with <code>#</code> are comments. asl-backup-menu uses
                the same list.
              </Content>
              <TextArea aria-label="Include list" value={text} onChange={(_e, v) => setText(v)} rows={16}
                        className="asl-mono" resizeOrientation="vertical" />
              {state?.ok && <Alert variant="success" isInline isPlain title={state.ok} />}
              {state?.error && <Alert variant="danger" isInline isPlain title={state.error} />}
              <ActionGroup>
                <Button type="submit" isDisabled={text === include.content && include.exists}>Save</Button>
                <Button variant="link" onClick={() => setText(include.content)} isDisabled={text === include.content}>
                  Revert
                </Button>
              </ActionGroup>
            </Form>
          )}
        </CardBody>
      </Card>
      <Card className="asl-danger-zone">
        <CardTitle>Restore the default configuration</CardTitle>
        <CardBody>
          <div className="asl-stack">
            <Content component="p">
              Reinstalls AllStarLink's original configuration files, as on a new installation. Your nodes, call signs
              and passwords are removed; the AMI secret is kept. The current configuration is saved as a backup first.
            </Content>
            <div>
              <Button variant="danger" onClick={() => setConfirm(true)}>Restore default configuration…</Button>
            </div>
          </div>
        </CardBody>
      </Card>
      <Modal isOpen={confirm} onClose={() => setConfirm(false)} variant="small" aria-labelledby="factory-title">
        <ModalHeader title="Restore the default configuration?" labelId="factory-title" titleIconVariant="danger" />
        <ModalBody>
          Every node setting on this server is replaced by AllStarLink's defaults. Your nodes go off the air until
          you set them up again (or restore a backup).
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={factory}>Restore defaults</Button>
          <Button variant="link" onClick={() => setConfirm(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}

const TABS = ["local", "cloud", "settings"] as const;

export function Backups({ tab }: { tab: string }) {
  const [list, setList] = useState<BackupList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setList(await listBackups());
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  const active = (TABS as readonly string[]).includes(tab) ? tab : "local";
  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Backups</Title>
        <Content component="p">Save and restore your node's configuration.</Content>
        <Tabs activeKey={active} onSelect={(_e, key) => go(`backups/${key}`)} className="asl-head-tabs">
          <Tab eventKey="local" title={<TabTitleText>This server</TabTitleText>} />
          <Tab eventKey="cloud" title={<TabTitleText>AllStarLink cloud</TabTitleText>} />
          <Tab eventKey="settings" title={<TabTitleText>Settings</TabTitleText>} />
        </Tabs>
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {!list && !error && <Spinner aria-label="Loading" />}
        {list && active === "local" && <ThisServer list={list} reload={reload} />}
        {list && active === "cloud" && <Cloud list={list} reload={reload} />}
        {active === "settings" && <Settings />}
      </PageSection>
    </>
  );
}
