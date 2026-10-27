import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Content,
  EmptyState,
  EmptyStateActions,
  EmptyStateBody,
  EmptyStateFooter,
  PageSection,
  Spinner,
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import BroadcastTowerIcon from "@patternfly/react-icons/dist/esm/icons/broadcast-tower-icon";

import { message } from "./api";
import { SA818Tab } from "./SA818Page";
import { detectSA818, SA818Detect } from "./sa818Api";
import { go } from "./useRoute";

export type Hardware = {
  detect: SA818Detect | null;
  error: string | null;
  scanning: boolean;
  scan: (again?: boolean) => Promise<void>;
};

// Looks for an SA818 on the serial ports once per visit (the server keeps
// the answer); App shares it with the navigation, which shows Hardware only
// when a module answered or its settings are saved (issue #47).
export function useHardware(): Hardware {
  const [detect, setDetect] = useState<SA818Detect | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const scan = useCallback(async (again = false) => {
    setScanning(true);
    try {
      setDetect(await detectSA818(again));
      setError(null);
    } catch (err) {
      setError(message(err));
    } finally {
      setScanning(false);
    }
  }, []);
  useEffect(() => {
    void scan();
  }, [scan]);
  return { detect, error, scanning, scan };
}

// Whether the navigation offers Hardware. If looking failed, it does: better
// a page to explain the failure than settings that cannot be reached.
export const showsHardware = (h: Hardware) => h.error !== null || (!!h.detect && (h.detect.found.length > 0 || h.detect.saved));

// Radio hardware attached to the server, one tab for each kind (issue #33).
// SA818 is the only one so far, so #/hardware shows it.
export function HardwarePage({ hardware }: { hardware: Hardware }) {
  const { detect, error, scanning, scan } = hardware;
  const [anyway, setAnyway] = useState(false);
  const head = (tabs: boolean) => (
    <PageSection className="asl-page-head">
      <Title headingLevel="h1">Hardware</Title>
      <Content component="p">Radio hardware attached to this server.</Content>
      {tabs && (
        <Tabs activeKey="sa818" onSelect={(_e, key) => go(`hardware/${key}`)} className="asl-head-tabs">
          <Tab eventKey="sa818" title={<TabTitleText>SA818 radio</TabTitleText>} />
        </Tabs>
      )}
    </PageSection>
  );

  if (!detect && !error) {
    return (
      <>
        {head(false)}
        <PageSection>
          <Spinner size="md" aria-label="Looking" /> <span className="asl-sub">Looking for an SA818 module on the serial ports…</span>
        </PageSection>
      </>
    );
  }
  if (detect && detect.found.length === 0 && !detect.saved && !anyway) {
    return (
      <>
        {head(false)}
        <PageSection>
          <EmptyState titleText="No radio hardware found" headingLevel="h2" icon={BroadcastTowerIcon}>
            <EmptyStateBody>
              No SA818 radio module answered on{" "}
              {detect.probed.length ? detect.probed.join(", ") : "this server's serial ports (there are none)"}. If one is
              connected, check its cable and power, then look again.
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button onClick={() => void scan(true)} isLoading={scanning} isDisabled={scanning}>Look again</Button>
                <Button variant="link" onClick={() => setAnyway(true)}>Set up an SA818 anyway</Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        </PageSection>
      </>
    );
  }
  return (
    <>
      {head(true)}
      {error && (
        <PageSection>
          <Alert variant="warning" isInline title={`Could not look for an SA818 module: ${error}`} />
        </PageSection>
      )}
      <SA818Tab hardware={hardware} />
    </>
  );
}
