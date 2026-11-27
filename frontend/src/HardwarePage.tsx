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

// Looks for supported serial radios on the serial ports when the page opens (the server
// keeps the answer until asked to look again).
function useHardware(): Hardware {
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

// Radio hardware attached to the server, one tab for each kind (issue #33).
// Preserve old hardware/sa818 links; the visible page is module-neutral.
export function HardwarePage() {
  const hardware = useHardware();
  const { detect, error, scanning, scan } = hardware;
  const [anyway, setAnyway] = useState(false);
  const head = (tabs: boolean) => (
    <PageSection className="asl-page-head">
      <Title headingLevel="h1">Hardware</Title>
      <Content component="p">Radio hardware attached to this server.</Content>
      {tabs && (
        <Tabs activeKey="radio" onSelect={(_e, key) => go(`hardware/${key}`)} className="asl-head-tabs">
          <Tab eventKey="radio" title={<TabTitleText>Radio programming</TabTitleText>} />
        </Tabs>
      )}
    </PageSection>
  );

  if (!detect && !error) {
    return (
      <>
        {head(false)}
        <PageSection>
          <Spinner size="md" aria-label="Looking" /> <span className="asl-sub">Looking for SA818-compatible or SR110U modules on the serial ports…</span>
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
              No supported serial radio module answered on{" "}
              {detect.probed.length ? detect.probed.join(", ") : "this server's serial ports (there are none)"}. If one is
              connected, check its cable and power, then look again.
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button onClick={() => void scan(true)} isLoading={scanning} isDisabled={scanning}>Look again</Button>
                <Button variant="link" onClick={() => setAnyway(true)}>Set up a radio anyway</Button>
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
          <Alert variant="warning" isInline title={`Could not look for radio modules: ${error}`} />
        </PageSection>
      )}
      <SA818Tab hardware={hardware} />
    </>
  );
}
