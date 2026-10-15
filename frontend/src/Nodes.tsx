import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardBody,
  Content,
  EmptyState,
  EmptyStateActions,
  EmptyStateBody,
  EmptyStateFooter,
  Label,
  PageSection,
  Spinner,
  Title,
} from "@patternfly/react-core";
import { ActionsColumn, Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import PlusIcon from "@patternfly/react-icons/dist/esm/icons/plus-icon";
import WrenchIcon from "@patternfly/react-icons/dist/esm/icons/wrench-icon";

import { message, Status } from "./api";
import { useChange } from "./ChangeReview";
import { INTERFACE_NAMES, listNodes, NodeList } from "./nodesApi";
import { NodeWizard, WizardResult } from "./NodeWizard";
import { RegistrationLabel } from "./Overview";
import { go } from "./useRoute";

export function useNodeList(): [NodeList | null, string | null, () => Promise<void>] {
  const [list, setList] = useState<NodeList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setList(await listNodes());
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return [list, error, load];
}

// The Add node wizard and the change review behind it.
export function useNodeWizard(list: NodeList | null, reload: () => Promise<void>) {
  const [open, setOpen] = useState<"add" | "first_run" | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [changeElement, propose] = useChange();

  const onReview = async (r: WizardResult) => {
    setReviewing(true);
    try {
      const applied = await propose(open ?? "add", { ...r });
      if (applied) {
        // Stay here, so the "restart now?" prompt that follows stays visible.
        setOpen(null);
        await reload();
      }
    } finally {
      setReviewing(false);
    }
  };

  const element = (
    <>
      {changeElement}
      {open && list && (
        <NodeWizard list={list} firstRun={open === "first_run"} hidden={reviewing} onClose={() => setOpen(null)}
                    onReview={onReview} />
      )}
    </>
  );
  return { element, start: setOpen };
}

export function FirstRun({ onStart }: { onStart: () => void }) {
  return (
    <EmptyState titleText="Set up your node" headingLevel="h2" icon={WrenchIcon}>
      <EmptyStateBody>
        This server still has the sample node 1999. Enter your node number, password and call sign, choose the radio
        interface, and the configuration is written for you.
      </EmptyStateBody>
      <EmptyStateFooter>
        <EmptyStateActions>
          <Button onClick={onStart}>Set up node</Button>
        </EmptyStateActions>
      </EmptyStateFooter>
    </EmptyState>
  );
}

export function Nodes({ status }: { status: Status | null }) {
  const [list, error, reload] = useNodeList();
  const wizard = useNodeWizard(list, reload);
  const [changeElement, propose] = useChange();
  const [actionError, setActionError] = useState<string | null>(null);

  const remove = async (number: string) => {
    setActionError(null);
    try {
      if (await propose("remove", { node: number })) await reload();
    } catch (err) {
      setActionError(message(err));
    }
  };

  const registration = (n: string) => status?.nodes.find((s) => s.node === n);

  return (
    <>
      <PageSection className="asl-page-head">
        <div className="asl-title-row">
          <div>
            <Title headingLevel="h1">Nodes</Title>
            <Content component="p">The AllStarLink nodes on this server.</Content>
          </div>
          {list && !list.first_run && (
            <Button icon={<PlusIcon />} onClick={() => wizard.start("add")}>
              Add node
            </Button>
          )}
        </div>
      </PageSection>
      <PageSection>
        {error && <Alert variant="danger" isInline title={error} />}
        {actionError && <Alert variant="danger" isInline title={actionError} className="asl-gap" />}
        {list && list.rpt_errors > 0 && (
          <Alert variant="danger" isInline title="rpt.conf has errors" className="asl-gap"
                 actionLinks={<Button variant="link" isInline onClick={() => go("config/rpt.conf")}>Open rpt.conf</Button>}>
            Asterisk rejects the file as it is. Fix it in Manual Config Edit before changing nodes here.
          </Alert>
        )}
        {!list && !error && <Spinner aria-label="Loading" />}
        {list && (
          <Card className="asl-gap">
            <CardBody>
              {list.first_run ? (
                <FirstRun onStart={() => wizard.start("first_run")} />
              ) : list.nodes.length === 0 ? (
                <EmptyState titleText="No nodes" headingLevel="h2">
                  <EmptyStateBody>Add a node to get on the air.</EmptyStateBody>
                </EmptyState>
              ) : (
                <Table aria-label="Nodes" variant="compact">
                  <Thead>
                    <Tr>
                      <Th>Node</Th>
                      <Th>Call sign</Th>
                      <Th>Radio interface</Th>
                      <Th>Duplex</Th>
                      <Th>Registration</Th>
                      <Th screenReaderText="Actions" />
                    </Tr>
                  </Thead>
                  <Tbody>
                    {list.nodes.map((n) => {
                      const reg = registration(n.number);
                      return (
                        <Tr key={n.number}>
                          <Td dataLabel="Node">
                            <a href={`#/nodes/${n.number}`}><b>{n.number}</b></a>
                          </Td>
                          <Td dataLabel="Call sign">{n.callsign ?? <span className="asl-sub">Not set</span>}</Td>
                          <Td dataLabel="Radio interface">{INTERFACE_NAMES[n.interface ?? ""] ?? n.rxchannel ?? "—"}</Td>
                          <Td dataLabel="Duplex">{n.duplex ?? "—"}</Td>
                          <Td dataLabel="Registration">
                            {reg ? <RegistrationLabel node={reg} /> : n.private ? <Label>Private</Label> :
                              <Label color="grey">Not running</Label>}
                          </Td>
                          <Td isActionCell>
                            <ActionsColumn items={[
                              { title: "Open", onClick: () => go(`nodes/${n.number}`) },
                              { isSeparator: true },
                              { title: "Remove node…", isDanger: true, onClick: () => void remove(n.number) },
                            ]} />
                          </Td>
                        </Tr>
                      );
                    })}
                  </Tbody>
                </Table>
              )}
            </CardBody>
          </Card>
        )}
      </PageSection>
      {wizard.element}
      {changeElement}
    </>
  );
}
