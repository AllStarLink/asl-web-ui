import { useMemo, useState } from "react";
import {
  Alert,
  Checkbox,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Form,
  FormGroup,
  FormHelperText,
  HelperText,
  HelperTextItem,
  Modal,
  ModalVariant,
  Radio,
  TextInput,
  Title,
  Wizard,
  WizardHeader,
  WizardStep,
} from "@patternfly/react-core";

import { ApiError, message } from "./api";
import { CustomOption, INTERFACE_NAMES, NodeList } from "./nodesApi";

export type WizardResult = {
  number: string;
  password: string;
  interface: string | null;
  duplex: number | null;
  callsign: string;
  statpost: boolean;
  customizations: string[];
};

type Props = {
  list: NodeList;
  firstRun: boolean;
  hidden: boolean; // while the change review is shown on top
  onClose: () => void;
  onReview: (result: WizardResult) => Promise<void>; // rejects with the planning error
};

const NUMBER = /^[0-9]{4,6}$/;
const PASSWORD = /^[0-9a-zA-Z_-]{6,}$/;
const CALLSIGN = /^[0-9A-Za-z/-]{3,}$/;

export function numberProblem(n: string, existing: string[], allow?: string): string | null {
  if (!NUMBER.test(n)) return "The node number must have 4 to 6 digits.";
  if (Number(n) < 1000) return "Private node numbers start at 1000.";
  if (Number(n) >= 2000 && n.startsWith("1")) return 'Registered node numbers cannot start with a "1".';
  if (n !== allow && existing.includes(n)) return `Node ${n} is already defined.`;
  return null;
}

// What the "Configuration" step offers: manual, common, or a device.
type Choice = { id: string; label: string; duplex: number | null; interface: string | null; custom?: string };

function Field({ id, label, value, onChange, problem, hint, type = "text" }: {
  id: string; label: string; value: string; onChange: (v: string) => void; problem: string | null; hint?: string;
  type?: "text" | "password";
}) {
  return (
    <FormGroup label={label} fieldId={id} isRequired>
      <TextInput id={id} type={type} value={value} onChange={(_e, v) => onChange(v)}
                 validated={value && problem ? "error" : "default"} autoComplete="off" />
      <FormHelperText>
        <HelperText>
          <HelperTextItem variant={value && problem ? "error" : "default"}>{(value && problem) || hint}</HelperTextItem>
        </HelperText>
      </FormHelperText>
    </FormGroup>
  );
}

export function NodeWizard({ list, firstRun, hidden, onClose, onReview }: Props) {
  const existing = list.nodes.map((n) => n.number);
  const [number, setNumber] = useState("");
  const [password, setPassword] = useState("");
  const [choiceId, setChoiceId] = useState("manual");
  const [iface, setIface] = useState("SimpleUSB");
  const [callsign, setCallsign] = useState("");
  const [statpost, setStatpost] = useState(true);
  const [extras, setExtras] = useState<string[]>([]);
  const [error, setError] = useState<{ text: string; field?: string } | null>(null);

  const choices: Choice[] = useMemo(() => [
    { id: "manual", label: "Manual configuration: choose the interface yourself", duplex: null, interface: null },
    ...list.presets.common.map((p) => ({ id: p.id, label: p.label, duplex: p.duplex, interface: p.interface })),
    ...list.presets.devices.map((d) => ({
      id: `device:${d.name}`, label: d.description.replace(/\*/g, ""), duplex: d.duplex, interface: d.interface,
      custom: d.name,
    })),
  ], [list]);
  const choice = choices.find((c) => c.id === choiceId) ?? choices[0];
  const isPublic = NUMBER.test(number) && Number(number) >= list.private_limit;
  const chosenInterface = choice.interface ?? iface;
  const interfaceOptions = choice.id === "manual" ? list.interfaces : list.interfaces.filter((i) => ["SimpleUSB", "USBRadio"].includes(i.id));
  const custom = list.customize[(chosenInterface === "SimpleUSB" || chosenInterface === "USBRadio") ? chosenInterface : "other"];
  const channel = chosenInterface === "SimpleUSB" ? "simpleusb" : chosenInterface === "USBRadio" ? "usbradio" : null;
  const offered: CustomOption[] = custom.reason ? [] : custom.options.filter(
    (o) => !o.device && (o.files.includes("rpt") || (channel !== null && o.files.includes(channel))),
  );
  const customizations = [...(choice.custom ? [choice.custom] : []), ...extras.filter((e) => offered.some((o) => o.name === e))];

  const numberError = number ? numberProblem(number, existing, firstRun ? "1999" : undefined) : "required";
  const passwordError = isPublic && !PASSWORD.test(password)
    ? "Letters, numbers, underscore and dash; at least 6 characters." : null;
  const callsignError = !CALLSIGN.test(callsign.trim()) ? "Letters, numbers, / and -; at least 3 characters." : null;

  const fieldError = (field: string) => (error?.field === field ? error.text : null);

  const review = async () => {
    setError(null);
    try {
      await onReview({
        number, password: isPublic ? password : "", interface: chosenInterface, duplex: choice.duplex,
        callsign: callsign.trim(), statpost: isPublic && statpost, customizations,
      });
    } catch (err) {
      setError({ text: message(err), field: err instanceof ApiError ? (err.data.field as string) : undefined });
    }
  };

  const title = firstRun ? "Set up your node" : "Add a node";
  return (
    <Modal isOpen={!hidden} onEscapePress={onClose} variant={ModalVariant.large} aria-label={title} className="asl-wizard-modal">
      <Wizard
        header={<WizardHeader title={title} onClose={onClose} closeButtonAriaLabel="Close"
                              description={firstRun ? "Turns the sample node 1999 into your node." : undefined} />}
        onClose={onClose}
        onSave={review}
        height={560}
      >
        <WizardStep name="Node number" id="number" footer={{ isNextDisabled: numberError !== null }}>
          <Form onSubmit={(e) => e.preventDefault()}>
            <Field id="wiz-number" label="Node number" value={number} onChange={setNumber}
                   problem={fieldError("number") ?? (numberError === "required" ? null : numberError)}
                   hint="The number AllStarLink assigned to your node (from the portal), or a private number from 1000 to 1999." />
          </Form>
        </WizardStep>
        <WizardStep name="Password" id="password" isHidden={!isPublic} footer={{ isNextDisabled: passwordError !== null }}>
          <Form onSubmit={(e) => e.preventDefault()}>
            <Content component="p">
              To register node {number} with AllStarLink, enter its password from allstarlink.org: Portal, Node Settings.
            </Content>
            <Field id="wiz-password" label="Node password" value={password} onChange={setPassword}
                   problem={fieldError("password") ?? passwordError} />
          </Form>
        </WizardStep>
        <WizardStep name="Configuration" id="preset">
          <Form onSubmit={(e) => e.preventDefault()}>
            <FormGroup role="radiogroup" fieldId="wiz-preset" label="What kind of node is this?" isStack>
              <Radio id="preset-manual" name="preset" label={choices[0].label} isChecked={choiceId === "manual"}
                     onChange={() => setChoiceId("manual")}
                     description="Start from the standard settings and adjust them on the node's page." />
              <Title headingLevel="h4" size="md" className="asl-subhead">Common configurations</Title>
              {choices.filter((c) => !c.custom && c.id !== "manual").map((c) => (
                <Radio key={c.id} id={`preset-${c.id}`} name="preset" label={c.label} isChecked={choiceId === c.id}
                       onChange={() => setChoiceId(c.id)} />
              ))}
              {list.presets.devices.length > 0 && (
                <Title headingLevel="h4" size="md" className="asl-subhead">Devices</Title>
              )}
              {choices.filter((c) => c.custom).map((c) => (
                <Radio key={c.id} id={`preset-${c.id}`} name="preset" label={c.label} isChecked={choiceId === c.id}
                       onChange={() => setChoiceId(c.id)}
                       description={`${INTERFACE_NAMES[c.interface ?? ""] ?? c.interface} · duplex ${c.duplex}`} />
              ))}
            </FormGroup>
          </Form>
        </WizardStep>
        <WizardStep name="Radio interface" id="interface" isHidden={choice.interface !== null}>
          <Form onSubmit={(e) => e.preventDefault()}>
            <FormGroup role="radiogroup" fieldId="wiz-iface" label="Radio interface" isStack>
              {interfaceOptions.map((i) => (
                <Radio key={i.id} id={`iface-${i.id}`} name="iface" label={i.label} isChecked={iface === i.id}
                       onChange={() => setIface(i.id)} />
              ))}
            </FormGroup>
            <Content component="p" className="asl-sub">Most nodes use SimpleUSB.</Content>
          </Form>
        </WizardStep>
        <WizardStep name="Call sign" id="callsign" footer={{ isNextDisabled: callsignError !== null }}>
          <Form onSubmit={(e) => e.preventDefault()}>
            <Field id="wiz-callsign" label="Call sign" value={callsign} onChange={setCallsign}
                   problem={fieldError("callsign") ?? callsignError}
                   hint="The node identifies with this call sign." />
          </Form>
        </WizardStep>
        <WizardStep name="Customizations" id="customize" isHidden={offered.length === 0}>
          <Form onSubmit={(e) => e.preventDefault()}>
            <Content component="p">Optional changes for common needs. You can change them later.</Content>
            {offered.map((o) => (
              <Checkbox key={o.name} id={`custom-${o.name}`} label={o.description}
                        isChecked={extras.includes(o.name)}
                        onChange={(_e, v) => setExtras((x) => (v ? [...x, o.name] : x.filter((n) => n !== o.name)))} />
            ))}
          </Form>
        </WizardStep>
        <WizardStep name="Review" id="review" footer={{ nextButtonText: "Review changes" }}>
          <div className="asl-stack">
            {error && !["number", "password", "callsign"].includes(error.field ?? "") && (
              <Alert variant="danger" isInline title={error.text} />
            )}
            {error && ["number", "password", "callsign"].includes(error.field ?? "") && (
              <Alert variant="danger" isInline title={`${error.text} Go back to fix it.`} />
            )}
            <DescriptionList isHorizontal isCompact>
              {[
                ["Node number", `${number}${isPublic ? "" : " (private)"}`],
                ["Configuration", choice.label],
                ["Radio interface", INTERFACE_NAMES[chosenInterface] ?? chosenInterface],
                ["Call sign", callsign.trim().toUpperCase()],
                ["Customizations", customizations.length ? customizations.map((n) =>
                  (custom.options.find((o) => o.name === n)?.description ?? n).replace(/\*/g, "")).join("; ") : "None"],
              ].map(([t, d]) => (
                <DescriptionListGroup key={t}>
                  <DescriptionListTerm>{t}</DescriptionListTerm>
                  <DescriptionListDescription>{d}</DescriptionListDescription>
                </DescriptionListGroup>
              ))}
            </DescriptionList>
            {isPublic && (
              <Checkbox id="wiz-statpost" label="Post node status to stats.allstarlink.org" isChecked={statpost}
                        onChange={(_e, v) => setStatpost(v)}
                        description="Lets you and others see the node's status and connections, and its place on the map." />
            )}
            <Content component="p" className="asl-sub">
              Next you see exactly which lines change in which files, before anything is saved.
            </Content>
          </div>
        </WizardStep>
      </Wizard>
    </Modal>
  );
}
