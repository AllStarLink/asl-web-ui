import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  Form,
  FormGroup,
  FormHelperText,
  Gallery,
  HelperText,
  HelperTextItem,
  Spinner,
  TextInput,
} from "@patternfly/react-core";

import { message } from "./api";
import { useChange } from "./ChangeReview";
import { asteriskSettings, AsteriskSettings as Settings } from "./nodesApi";

function SettingForm({ title, children, onSubmit, valid, help }: {
  title: string; children: React.ReactNode; onSubmit: () => Promise<unknown>; valid: boolean; help: React.ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      <CardBody>
        <Form onSubmit={submit}>
          <Content component="p">{help}</Content>
          {children}
          {error && <Alert variant="danger" isInline isPlain title={error} />}
          <ActionGroup>
            <Button type="submit" isDisabled={!valid || busy} isLoading={busy}>
              Review change
            </Button>
          </ActionGroup>
        </Form>
      </CardBody>
    </Card>
  );
}

// node-setup's main-menu settings: the AMI secret and the IAX port.
export function AsteriskSettings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [port, setPort] = useState("");
  const [changeElement, propose] = useChange();

  const load = useCallback(async () => {
    try {
      const s = await asteriskSettings();
      setSettings(s);
      setPort(String(s.iax_port));
    } catch (err) {
      setError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <Alert variant="danger" isInline title={error} />;
  if (!settings) return <Spinner aria-label="Loading" />;
  const secretOk = /^[0-9a-zA-Z_-]{12,}$/.test(secret);
  const portOk = /^[0-9]+$/.test(port) && Number(port) > 0 && Number(port) < 65536 && Number(port) !== settings.iax_port;
  const others = settings.ami_users.filter((u) => u.toLowerCase() !== "admin");
  return (
    <>
      <Gallery hasGutter minWidths={{ default: "100%", xl: "32rem" }}>
        <SettingForm
          title="AMI secret"
          valid={secretOk && settings.ami_admin}
          onSubmit={async () => {
            if (await propose("ami_secret", { secret })) setSecret("");
          }}
          help={<>The password of the Asterisk Manager Interface user <code>admin</code>, which Allmon3, Supermon and
            similar tools use to watch and control the node.{others.length > 0 && ` Other AMI users (${others.join(", ")}) are not changed.`}</>}
        >
          {!settings.ami_admin && <Alert variant="warning" isInline isPlain title="manager.conf has no [admin] user." />}
          <FormGroup label="New AMI secret" fieldId="ami-secret">
            <TextInput id="ami-secret" type="password" value={secret} onChange={(_e, v) => setSecret(v)} autoComplete="new-password" />
            <FormHelperText>
              <HelperText>
                <HelperTextItem variant={secret && !secretOk ? "error" : "default"}>
                  Letters, numbers, underscore and dash; at least 12 characters.
                </HelperTextItem>
              </HelperText>
            </FormHelperText>
          </FormGroup>
        </SettingForm>
        <SettingForm
          title="IAX port"
          valid={portOk}
          onSubmit={async () => {
            if (await propose("iax_port", { port: Number(port) })) await load();
          }}
          help={<>The UDP port other nodes use to connect to this server. The default is 4569. The local nodes' entries
            in rpt.conf follow the new port.</>}
        >
          <FormGroup label="UDP port" fieldId="iax-port">
            <TextInput id="iax-port" value={port} onChange={(_e, v) => setPort(v.trim())} inputMode="numeric" />
          </FormGroup>
        </SettingForm>
      </Gallery>
      {changeElement}
    </>
  );
}
