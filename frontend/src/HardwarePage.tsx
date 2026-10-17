import { Content, PageSection, Tab, Tabs, TabTitleText, Title } from "@patternfly/react-core";

import { SA818Tab } from "./SA818Page";
import { go } from "./useRoute";

// Radio hardware attached to the server, one tab for each kind (issue #33).
// SA818 is the only one so far, so #/hardware shows it.
export function HardwarePage() {
  return (
    <>
      <PageSection className="asl-page-head">
        <Title headingLevel="h1">Hardware</Title>
        <Content component="p">Radio hardware attached to this server.</Content>
        <Tabs activeKey="sa818" onSelect={(_e, key) => go(`hardware/${key}`)} className="asl-head-tabs">
          <Tab eventKey="sa818" title={<TabTitleText>SA818 radio</TabTitleText>} />
        </Tabs>
      </PageSection>
      <SA818Tab />
    </>
  );
}
