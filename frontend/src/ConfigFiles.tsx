import { useEffect, useState } from "react";
import { Alert, Card, CardBody, CardTitle, Content, Label, PageSection, Spinner, Title } from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import CheckCircleIcon from "@patternfly/react-icons/dist/esm/icons/check-circle-icon";
import ExclamationTriangleIcon from "@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon";
import TimesCircleIcon from "@patternfly/react-icons/dist/esm/icons/times-circle-icon";

import { ApiError } from "./api";
import { Counts, FileSummary, listFiles } from "./configApi";

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
            These are the raw Asterisk and app_rpt configuration files. A mistake here can take your node off the air or
            stop Asterisk from starting.
          </p>
          <p>
            Every save keeps a snapshot of the previous version, and problems Asterisk would refuse are shown before you
            save.
          </p>
        </Alert>
      </PageSection>
      <PageSection>
        <Card>
          <CardTitle>Configuration files</CardTitle>
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
                        {f.exists && !f.writable ? (
                          <Label color="orange" icon={<ExclamationTriangleIcon />}>
                            {f.owner}: read-only
                          </Label>
                        ) : (
                          <code className="asl-sub">{f.owner ?? "—"}</code>
                        )}
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
      </PageSection>
    </>
  );
}
