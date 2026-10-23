import { useCallback, useEffect, useState } from "react";
import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
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
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Spinner,
  Switch,
  Title,
} from "@patternfly/react-core";

import { ApiError, message } from "./api";
import {
  CertInfo, enableListener, httpsStatus, HttpsStatus, installCertbot, obtainCertificate, removeHttps, renewTest,
  setRedirect, cockpitCertificate,
} from "./httpsApi";
import { useJob } from "./Job";
import { PlainTextInput } from "./PlainInput";
import { useReauth } from "./Reauth";

// HTTPS for the web server (Apache): a port 443 listener, and a Let's
// Encrypt certificate for the server's public name (issue #2).

const AGREEMENT = "https://letsencrypt.org/repository/";

function Cert({ cert }: { cert: CertInfo }) {
  return (
    <>
      {cert.self_signed ? <Label color="orange">Self-signed</Label>
        : cert.staging ? <Label color="orange">Let's Encrypt test certificate</Label>
        : <Label color="green">{cert.issuer?.match(/O\s*=\s*([^,]+)/)?.[1] ?? cert.issuer}</Label>}
      {" "}
      <span>{cert.names.length ? cert.names.join(", ") : cert.subject}</span>
      {cert.expires && <span className="asl-sub"> · expires {new Date(cert.expires).toLocaleDateString()}</span>}
    </>
  );
}

export function HttpsPage() {
  const [status, setStatus] = useState<HttpsStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ variant: "success" | "danger" | "warning" | "info"; text: string } | null>(null);
  const [jobElement, runJob] = useJob();
  const [reauthElement, withReauth] = useReauth();
  const [names, setNames] = useState("");
  const [email, setEmail] = useState("");
  const [agree, setAgree] = useState(false);
  const [staging, setStaging] = useState(true);
  const [redirect, setRedirectWanted] = useState(true);
  const [fieldError, setFieldError] = useState<{ field: string; text: string } | null>(null);
  const [removing, setRemoving] = useState(false);
  const [deleteCert, setDeleteCert] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await httpsStatus();
      setStatus(s);
      setLoadError(null);
      if (s.site) {
        setNames((n) => n || s.site!.domains.join(" "));
        setRedirectWanted(s.site.redirect);
      }
      // Once a real certificate works, getting it again needs no test run first.
      setStaging(!(s.site?.cert && s.renewal && !s.renewal.staging));
    } catch (err) {
      setLoadError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const job = async (title: string, start: () => Promise<{ job: string }>, done: string) => {
    setNotice(null);
    const res = await runJob(title, start);
    if (res?.ok) setNotice({ variant: "success", text: done });
    await load();
    return res;
  };

  const obtain = async () => {
    setFieldError(null);
    const domains = names.split(/[\s,]+/).filter(Boolean);
    const res = await job(staging ? "Get a Let's Encrypt test certificate" : "Get a Let's Encrypt certificate",
      async () => {
        try {
          return await obtainCertificate({ domains, email, agree_tos: agree, staging, redirect });
        } catch (err) {
          if (err instanceof ApiError && err.data.field) setFieldError({ field: err.data.field as string, text: err.message });
          throw err;
        }
      },
      staging ? "The test certificate is installed. When everything works, get the real one."
        : "The certificate is installed; Debian's certbot timer renews it.");
    if (res?.ok) setAgree(false);
  };

  const toggleRedirect = async (value: boolean) => {
    setNotice(null);
    try {
      await setRedirect(value);
      setNotice({ variant: "success", text: value ? "HTTP now redirects to HTTPS." : "HTTP no longer redirects." });
      await load();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  const cockpit = async () => {
    setNotice(null);
    try {
      await cockpitCertificate();
      setNotice({ variant: "success", text: "Cockpit uses the certificate too; anyone logged in to it logs in again." });
      await load();
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  const remove = async () => {
    setRemoving(false);
    setNotice(null);
    try {
      if (await withReauth(() => removeHttps(deleteCert))) {
        setNotice({ variant: "success", text: status?.vhosts === "external" ? "Apache uses its self-signed certificate again."
          : "The Let's Encrypt site is removed; Apache uses its other sites again." });
        setNames("");
        await load();
      }
    } catch (err) {
      setNotice({ variant: "danger", text: message(err) });
    }
  };

  const head = (
    <PageSection className="asl-page-head">
      <Title headingLevel="h1">HTTPS</Title>
      <Content component="p" className="asl-sub">
        Encrypted connections to this server's web pages (asl-web-ui, Allmon3), with a certificate browsers trust.
      </Content>
    </PageSection>
  );
  if (loadError || !status) {
    return (
      <>
        {head}
        <PageSection>{loadError ? <Alert variant="danger" isInline title={loadError} /> : <Spinner aria-label="Loading" />}</PageSection>
      </>
    );
  }
  if (!status.apache) {
    return (
      <>
        {head}
        <PageSection>
          <Alert variant="info" isInline title="This page manages Apache, which is not installed here">
            With nginx, get a certificate with <code>sudo apt install python3-certbot-nginx</code> and{" "}
            <code>sudo certbot --nginx</code>.
          </Alert>
        </PageSection>
      </>
    );
  }

  const site = status.site;
  const external = status.vhosts === "external";
  const fieldProblem = (f: string) => (fieldError?.field === f ? fieldError.text : null);
  return (
    <>
      {head}
      <PageSection>
        <div className="asl-stack">
          {notice && <Alert variant={notice.variant} isInline title={notice.text} />}

          <Card>
            <CardTitle>Now</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal>
                <DescriptionListGroup>
                  <DescriptionListTerm>HTTPS (port 443)</DescriptionListTerm>
                  <DescriptionListDescription>
                    {status.listening_443 ? <Label color="green">On</Label> : <Label color="orange">Off</Label>}
                    {!status.listening_443 && !external && (
                      <Button variant="link" isInline onClick={() => job("Enable HTTPS on port 443", enableListener,
                        "Apache now serves HTTPS with its self-signed certificate.")}>
                        {" "}Turn on with a self-signed certificate
                      </Button>
                    )}
                  </DescriptionListDescription>
                </DescriptionListGroup>
                {status.served && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Certificate</DescriptionListTerm>
                    <DescriptionListDescription><Cert cert={status.served} /></DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                {site?.cert && status.cockpit?.installed && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Cockpit (port 9090)</DescriptionListTerm>
                    <DescriptionListDescription>
                      {status.cockpit.letsencrypt ? (
                        <Label color="green">Uses the Let's Encrypt certificate</Label>
                      ) : (
                        <>
                          <Label color="orange">
                            {status.cockpit.uses ? `Uses ${status.cockpit.uses}` : "Uses its self-signed certificate"}
                          </Label>
                          <Button variant="link" isInline onClick={() => void cockpit()}>
                            {" "}Use the Let's Encrypt certificate
                          </Button>
                        </>
                      )}
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                <DescriptionListGroup>
                  <DescriptionListTerm>certbot</DescriptionListTerm>
                  <DescriptionListDescription>
                    {status.packages ? (
                      <>
                        <Label color="green">Installed</Label>
                        <span className="asl-sub"> · renewal timer {status.timer}</span>
                      </>
                    ) : (
                      <Button variant="link" isInline onClick={() => job("Install certbot", installCertbot,
                        "certbot is installed.")}>Install python3-certbot-apache</Button>
                    )}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
            </CardBody>
          </Card>

          <Card>
            <CardTitle>{site?.cert ? "Let's Encrypt certificate" : "Get a Let's Encrypt certificate"}</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => { e.preventDefault(); void obtain(); }}>
                <Content component="p">
                  Let's Encrypt checks that each name reaches this server: the names must be in public DNS, pointing
                  here, and port 80 must be open to the internet (forwarded, if the server is behind a router).
                  Certificates last 90 days and renew automatically.
                </Content>
                {site?.cert && status.certificate && (
                  <Alert variant={status.renewal?.staging ? "warning" : "success"} isInline isPlain
                         title={status.renewal?.staging ? "This is a test certificate: browsers do not trust it."
                           : "Browsers trust this certificate."}>
                    <Cert cert={status.certificate} />
                  </Alert>
                )}
                <FormGroup label="Names" fieldId="https-names" isRequired>
                  <PlainTextInput id="https-names" value={names} onChange={(_e, v) => setNames(v)}
                                  placeholder="node.example.org" validated={fieldProblem("domains") ? "error" : "default"} />
                  <FormHelperText><HelperText>
                    <HelperTextItem variant={fieldProblem("domains") ? "error" : "default"}>
                      {fieldProblem("domains") ?? "This server's names, separated by spaces; the first is the main one."}
                    </HelperTextItem>
                  </HelperText></FormHelperText>
                </FormGroup>
                <FormGroup label="Email" fieldId="https-email">
                  <PlainTextInput id="https-email" type="email" value={email} onChange={(_e, v) => setEmail(v)}
                                  autoComplete="email" validated={fieldProblem("email") ? "error" : "default"} />
                  <FormHelperText><HelperText>
                    <HelperTextItem variant={fieldProblem("email") ? "error" : "default"}>
                      {fieldProblem("email") ?? "Optional: Let's Encrypt writes here about problems with the account."}
                    </HelperTextItem>
                  </HelperText></FormHelperText>
                </FormGroup>
                <Checkbox id="https-staging" label="Test certificate first" isChecked={staging}
                          onChange={(_e, v) => setStaging(v)}
                          description="Not trusted by browsers, but without Let's Encrypt's limits on repeated requests. Recommended until it works." />
                {!external && (
                  <Checkbox id="https-redirect" label="Send HTTP visitors to HTTPS" isChecked={redirect}
                            onChange={(_e, v) => setRedirectWanted(v)} />
                )}
                <Checkbox id="https-agree" isChecked={agree} onChange={(_e, v) => setAgree(v)}
                          label={<>I agree to the <a href={AGREEMENT} target="_blank" rel="noopener">Let's Encrypt subscriber agreement</a></>} />
                {fieldProblem("agree_tos") && <Alert variant="danger" isInline isPlain title={fieldProblem("agree_tos")} />}
                <ActionGroup>
                  <Button type="submit" isDisabled={!status.packages || !agree || !names.trim()}>
                    {site?.cert ? "Get the certificate again" : "Get the certificate"}
                  </Button>
                  {!status.packages && <span className="asl-sub">Install certbot first.</span>}
                </ActionGroup>
              </Form>
            </CardBody>
          </Card>

          {site && (
            <Card>
              <CardTitle>Settings</CardTitle>
              <CardBody>
                <div className="asl-stack">
                  {!external && (
                    <Switch id="https-redirect-now" label={`Send HTTP visitors of ${site.domains.join(", ")} to HTTPS`}
                            isChecked={site.redirect} onChange={(_e, v) => void toggleRedirect(v)} isDisabled={!site.cert} />
                  )}
                  <div className="asl-buttons">
                    <Button variant="secondary" isDisabled={!site.cert}
                            onClick={() => job("Test the certificate renewal", renewTest, "The renewal test succeeded.")}>
                      Test the renewal
                    </Button>
                    <Button variant="link" isDanger onClick={() => { setDeleteCert(false); setRemoving(true); }}>
                      Stop using it
                    </Button>
                  </div>
                  <Content component="p" className="asl-sub">
                    {external ? (
                      <>
                        This system's web server configuration provides Apache's sites and sends HTTP visitors to
                        HTTPS; asl-web-ui gives its HTTPS site the certificate in{" "}
                        <code>/etc/asl-web-ui/apache-tls.conf</code>.
                      </>
                    ) : (
                      <>
                        asl-web-ui keeps these settings in{" "}
                        <code>/etc/apache2/sites-available/asl-web-ui-https.conf</code>; Apache's other sites are not
                        changed.
                      </>
                    )}{" "}
                    If Cockpit is installed, it gets a copy of the certificate in <code>/etc/cockpit/ws-certs.d</code>,
                    renewed with it.
                  </Content>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      </PageSection>
      <Modal isOpen={removing} onClose={() => setRemoving(false)} variant="small" aria-labelledby="https-remove-title">
        <ModalHeader title="Stop using the Let's Encrypt certificate?" labelId="https-remove-title" titleIconVariant="warning" />
        <ModalBody>
          <div className="asl-stack">
            <Content component="p">
              {external ? "Apache's HTTPS site goes back to its self-signed certificate, and Cockpit to its own."
                : "asl-web-ui's Apache site is removed. Visitors get Apache's other sites again (often a self-signed certificate), and Cockpit its own certificate."}
            </Content>
            <Checkbox id="https-delete-cert" label="Also delete the certificate and stop renewing it"
                      isChecked={deleteCert} onChange={(_e, v) => setDeleteCert(v)} />
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="danger" onClick={remove}>Stop using it</Button>
          <Button variant="link" onClick={() => setRemoving(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
      {jobElement}
      {reauthElement}
    </>
  );
}
