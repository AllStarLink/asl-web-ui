import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  ExpandableSection,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
  HelperText,
  HelperTextItem,
  PageSection,
  Radio,
  Spinner,
  Switch,
  ToggleGroup,
  ToggleGroupItem,
} from "@patternfly/react-core";

import { ApiError, message } from "./api";
import type { Hardware } from "./HardwarePage";
import { PlainTextInput } from "./PlainInput";
import { applySA818, programSA818, readSA818, SA818Result, SA818Settings, SA818State, sa818Version } from "./sa818Api";
import { useLeaveGuard } from "./useRoute";

// sa818-menu's settings for an SA818 RF module (SHARI and similar), saved
// to /etc/sa818.conf and programmed into the module with the sa818 command.

type Problems = Partial<Record<keyof SA818Settings, string>>;

const FREQ = /^[0-9]{3}\.[0-9]*$/;

// The same checks as the server: sa818-menu's band limits (whole MHz) and
// sa818's own rule for the receive frequency.
function problems(s: SA818Settings, bands: Record<string, [number, number]>): Problems {
  const out: Problems = {};
  const [low, high] = bands[s.CURRENT_BAND] ?? [0, 0];
  for (const key of ["CURRENT_FREQ_RX", "CURRENT_FREQ_TX"] as const) {
    const v = s[key].trim();
    const mhz = Number(v.split(".")[0]);
    if (!FREQ.test(v) || mhz < low || mhz > high) out[key] = `Between ${low}.0000 and ${high}.0000 MHz, as xxx.xxxx.`;
  }
  const rx = Number(s.CURRENT_FREQ_RX);
  if (!out.CURRENT_FREQ_RX && !((rx > 144 && rx < 148) || (rx > 420 && rx < 450))) {
    out.CURRENT_FREQ_RX = "sa818 programs receive frequencies in the amateur bands only (144-148 or 420-450 MHz).";
  }
  return out;
}

const normalize = (f: string) => (FREQ.test(f.trim()) ? Number(f).toFixed(4).padStart(8, "0") : f.trim());

function Field({ id, label, problem, hint, children }: {
  id: string; label: string; problem?: string; hint?: ReactNode; children: ReactNode;
}) {
  return (
    <FormGroup label={label} fieldId={id}>
      {children}
      {(problem || hint) && (
        <FormHelperText>
          <HelperText>
            <HelperTextItem variant={problem ? "error" : "default"}>{problem ?? hint}</HelperTextItem>
          </HelperText>
        </FormHelperText>
      )}
    </FormGroup>
  );
}

function Log({ lines }: { lines: string[] }) {
  return <pre className="asl-job-log">{lines.join("\n")}</pre>;
}

// What looking for a module on the serial ports found, against the saved connection.
function Detected({ hardware, saved, draft, onUse }: {
  hardware: Hardware; saved: boolean; draft: SA818Settings; onUse: (port: string, speed: string) => void;
}) {
  const { detect, scanning, scan } = hardware;
  if (!detect) return null;
  const again = (
    <Button variant="link" isInline onClick={() => void scan(true)} isLoading={scanning} isDisabled={scanning}>Look again</Button>
  );
  const [first] = detect.found;
  if (!first) {
    return (
      <Alert variant="warning" isInline title="No SA818 module answered" actionLinks={again}>
        Nothing answered on {detect.probed.join(", ") || "this server's serial ports"}.{" "}
        {saved ? "The settings below are saved, but the module may be disconnected or powered off." : ""}
      </Alert>
    );
  }
  const where = `${first.port} at ${first.speed}`;
  if (detect.reachable) {
    return <Alert variant="info" isInline isPlain title={`SA818 module found on ${where} (firmware ${first.firmware}).`} />;
  }
  const chosen = draft.CURRENT_PORT === first.port && draft.CURRENT_SPEED === first.speed;
  return (
    <Alert variant="warning" isInline title={`SA818 module found on ${where}, but the saved connection does not reach it`}
           actionLinks={<>
             <Button variant="link" isInline onClick={() => onUse(first.port, first.speed)} isDisabled={chosen}>
               Use {where}
             </Button>
             {again}
           </>}>
      {chosen ? "Save to use it." : "Programming would fail: set the serial port and speed under Connection to where it answered."}
    </Alert>
  );
}

// The SA818 tab of the Hardware page.
export function SA818Tab({ hardware }: { hardware: Hardware }) {
  const [state, setState] = useState<SA818State | null>(null);
  const [draft, setDraft] = useState<SA818Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "program" | "test" | null>(null);
  const [result, setResult] = useState<{ variant: "success" | "danger" | "warning"; title: string; log: string[] } | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  // The buttons are at the bottom of a long page and the outcome is shown at
  // the top: bring it into view (issue #31).
  useEffect(() => {
    if (result) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [result]);

  const load = useCallback(async () => {
    try {
      const s = await readSA818();
      setState(s);
      setDraft(s.settings);
      setLoadError(null);
    } catch (err) {
      setLoadError(message(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const dirty = !!state && !!draft && JSON.stringify(state.settings) !== JSON.stringify(draft);
  const stays = useCallback((r: string) => r === "hardware" || r === "hardware/sa818", []);
  useLeaveGuard(dirty ? stays : null);

  if (loadError) {
    return (
      <PageSection>
        <Alert variant="danger" isInline title={loadError} />
      </PageSection>
    );
  }
  if (!state || !draft) {
    return (
      <PageSection>
        <Spinner aria-label="Loading" />
      </PageSection>
    );
  }

  const set = (change: Partial<SA818Settings>) => setDraft({ ...draft, ...change });
  const found = problems(draft, state.choices.bands);
  const valid = Object.keys(found).length === 0;
  const offset = FREQ.test(draft.CURRENT_FREQ_RX) && FREQ.test(draft.CURRENT_FREQ_TX)
    ? Number(draft.CURRENT_FREQ_TX) - Number(draft.CURRENT_FREQ_RX) : 0;

  // As sa818-menu: choosing a tone for one direction when both were None sets both.
  const setTone = (kind: "CTCSS" | "DCS", dir: "RX" | "TX", value: string) => {
    const key = `CURRENT_${kind}_${dir}` as keyof SA818Settings;
    const other = `CURRENT_${kind}_${dir === "RX" ? "TX" : "RX"}` as keyof SA818Settings;
    set({ [key]: value, ...(value !== "None" && draft[other] === "None" ? { [other]: value } : {}) });
  };

  const finish = (res: SA818Result, saved: boolean) => {
    const noAnswer = res.log.includes("Connection error")
      ? " The module did not answer: check the serial port and speed under Connection." : "";
    setResult(res.programmed
      ? { variant: "success", title: saved ? "Saved, and the module accepted every setting." : "The module accepted every setting.",
          log: res.log }
      : { variant: "danger", title: (saved ? "Saved, but programming the module failed." : "Programming the module failed.") + noAnswer,
          log: res.log });
  };

  const save = async () => {
    setBusy("save");
    setResult(null);
    try {
      const settings = { ...draft, CURRENT_FREQ_RX: normalize(draft.CURRENT_FREQ_RX), CURRENT_FREQ_TX: normalize(draft.CURRENT_FREQ_TX) };
      const res = await applySA818(settings);
      finish(res, true);
      await load();
      void hardware.scan();
    } catch (err) {
      const field = err instanceof ApiError ? (err.data.field as string | undefined) : undefined;
      setResult({ variant: "danger", title: field ? `${field}: ${message(err)}` : message(err), log: [] });
    } finally {
      setBusy(null);
    }
  };

  const program = async () => {
    setBusy("program");
    setResult(null);
    try {
      finish(await programSA818(), false);
    } catch (err) {
      setResult({ variant: "danger", title: message(err), log: [] });
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setResult(null);
    try {
      const v = await sa818Version();
      setResult(v.ok ? { variant: "success", title: `The module answered: firmware ${v.firmware}.`, log: v.log }
        : { variant: "danger", title: "The module did not answer on the saved serial port and speed.", log: v.log });
    } catch (err) {
      setResult({ variant: "danger", title: message(err), log: [] });
    } finally {
      setBusy(null);
    }
  };

  const ports = [...new Set([...state.ports, ...(draft.CURRENT_PORT ? [draft.CURRENT_PORT] : [])])];
  const [low, high] = state.choices.bands[draft.CURRENT_BAND];
  const onOff = (key: "CURRENT_EMPHASIS" | "CURRENT_FILTER_HIGH_PASS" | "CURRENT_FILTER_LOW_PASS", label: string) => (
    <Switch id={`sa818-${key}`} label={label} isChecked={draft[key] === "Enabled"}
            onChange={(_e, v) => set({ [key]: v ? "Enabled" : "Disabled" })} />
  );

  return (
    <>
      <PageSection>
        <div className="asl-stack">
          <Content component="p" className="asl-sub">
            SA818 radios are commonly used in hotspot-type nodes.
          </Content>
          {!state.tool && (
            <Alert variant="warning" isInline title="The sa818 command is missing">
              It comes with the asl3 package; the module cannot be programmed without it.
            </Alert>
          )}
          <Alert variant="info" isInline isPlain
                 title={state.saved ? "The module cannot be read back: these are the settings last saved by this page or sa818-menu."
                   : "No settings are saved yet; these are sa818-menu's defaults."} />
          <Detected hardware={hardware} saved={state.saved} draft={draft}
                    onUse={(port, speed) => set({ CURRENT_PORT: port, CURRENT_SPEED: speed })} />
          {result && (
            <div ref={resultRef} className="asl-scroll-target">
              <Alert variant={result.variant} isInline title={result.title}>
                {result.log.length > 0 && (
                  <ExpandableSection toggleText="What sa818 reported">
                    <Log lines={result.log} />
                  </ExpandableSection>
                )}
              </Alert>
            </div>
          )}

          <Card>
            <CardTitle>Radio</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
                <Field id="sa818-band" label="Band" hint="Which module this is: VHF or UHF.">
                  <ToggleGroup aria-label="Band">
                    {(["VHF", "UHF"] as const).map((b) => (
                      <ToggleGroupItem key={b} text={b} isSelected={draft.CURRENT_BAND === b} onChange={() => set({ CURRENT_BAND: b })} />
                    ))}
                  </ToggleGroup>
                </Field>
                <Field id="sa818-bw" label="Bandwidth">
                  <ToggleGroup aria-label="Bandwidth">
                    <ToggleGroupItem text="Narrow (12.5 kHz)" isSelected={draft.CURRENT_BANDWIDTH === "Narrow"}
                                     onChange={() => set({ CURRENT_BANDWIDTH: "Narrow" })} />
                    <ToggleGroupItem text="Wide (25 kHz)" isSelected={draft.CURRENT_BANDWIDTH === "Wide"}
                                     onChange={() => set({ CURRENT_BANDWIDTH: "Wide" })} />
                  </ToggleGroup>
                </Field>
                <div className="asl-form-row">
                  <Field id="sa818-rx" label="Receive frequency (MHz)" problem={found.CURRENT_FREQ_RX}
                         hint={`${low}.0000 to ${high}.0000`}>
                    <PlainTextInput id="sa818-rx" value={draft.CURRENT_FREQ_RX} inputMode="decimal"
                                    validated={found.CURRENT_FREQ_RX ? "error" : "default"}
                                    onChange={(_e, v) => set({ CURRENT_FREQ_RX: v,
                                      ...(draft.CURRENT_FREQ_TX === "000.0000" ? { CURRENT_FREQ_TX: v } : {}) })} />
                  </Field>
                  <Field id="sa818-tx" label="Transmit frequency (MHz)" problem={found.CURRENT_FREQ_TX}
                         hint={offset ? `Offset ${offset > 0 ? "+" : ""}${offset.toFixed(4)} MHz` : "Simplex (same as receive)"}>
                    <PlainTextInput id="sa818-tx" value={draft.CURRENT_FREQ_TX} inputMode="decimal"
                                    validated={found.CURRENT_FREQ_TX ? "error" : "default"}
                                    onChange={(_e, v) => set({ CURRENT_FREQ_TX: v })} />
                  </Field>
                </div>
                <div className="asl-form-row">
                  <Field id="sa818-squelch" label="Squelch" hint="0 (open) to 8.">
                    <FormSelect id="sa818-squelch" value={draft.CURRENT_SQUELCH} onChange={(_e, v) => set({ CURRENT_SQUELCH: v })}>
                      {Array.from({ length: 9 }, (_, i) => <FormSelectOption key={i} value={String(i)} label={String(i)} />)}
                    </FormSelect>
                  </Field>
                  <Field id="sa818-volume" label="Volume" hint="1 to 8: the audio level to the sound card.">
                    <FormSelect id="sa818-volume" value={draft.CURRENT_VOLUME} onChange={(_e, v) => set({ CURRENT_VOLUME: v })}>
                      {Array.from({ length: 8 }, (_, i) => <FormSelectOption key={i} value={String(i + 1)} label={String(i + 1)} />)}
                    </FormSelect>
                  </Field>
                </div>
              </Form>
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Sub-audible tone</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
                <FormGroup role="radiogroup" fieldId="sa818-tone" isInline>
                  {(["None", "CTCSS", "DCS"] as const).map((t) => (
                    <Radio key={t} id={`sa818-tone-${t}`} name="sa818-tone" label={t === "None" ? "None" : t}
                           isChecked={draft.CURRENT_TONE === t} onChange={() => set({ CURRENT_TONE: t })} />
                  ))}
                </FormGroup>
                {draft.CURRENT_TONE !== "None" && (
                  <div className="asl-form-row">
                    {(["RX", "TX"] as const).map((dir) => {
                      const kind = draft.CURRENT_TONE as "CTCSS" | "DCS";
                      const key = `CURRENT_${kind}_${dir}` as keyof SA818Settings;
                      const list = kind === "CTCSS" ? state.choices.ctcss : state.choices.dcs;
                      return (
                        <Field key={dir} id={`sa818-${kind}-${dir}`} label={`${kind} ${dir === "RX" ? "receive" : "transmit"}`}
                               hint={kind === "DCS" ? "N normal, I inverted." : undefined}>
                          <FormSelect id={`sa818-${kind}-${dir}`} value={draft[key]} onChange={(_e, v) => setTone(kind, dir, v)}>
                            {list.map((t) => (
                              <FormSelectOption key={t} value={t} label={t === "None" || kind === "DCS" ? t : `${t} Hz`} />
                            ))}
                          </FormSelect>
                        </Field>
                      );
                    })}
                  </div>
                )}
                {draft.CURRENT_TONE === "CTCSS" && (draft.CURRENT_CTCSS_RX !== "None" || draft.CURRENT_CTCSS_TX !== "None") && (
                  <Field id="sa818-tail" label="CTCSS reverse burst (tail tone)">
                    <FormSelect id="sa818-tail" value={draft.CURRENT_TAIL_TONE}
                                onChange={(_e, v) => set({ CURRENT_TAIL_TONE: v as SA818Settings["CURRENT_TAIL_TONE"] })}>
                      <FormSelectOption value="Closed" label="Closed (sa818-menu's default)" />
                      <FormSelectOption value="Opened" label="Opened" />
                    </FormSelect>
                  </Field>
                )}
              </Form>
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Audio filters</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
                {onOff("CURRENT_EMPHASIS", "Pre-emphasis and de-emphasis")}
                {onOff("CURRENT_FILTER_HIGH_PASS", "High-pass filter")}
                {onOff("CURRENT_FILTER_LOW_PASS", "Low-pass filter")}
              </Form>
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Connection</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
                <div className="asl-form-row">
                  <Field id="sa818-port" label="Serial port" problem={found.CURRENT_PORT}
                         hint={state.ports.length ? undefined : "No serial ports were found on this server."}>
                    <FormSelect id="sa818-port" value={draft.CURRENT_PORT} onChange={(_e, v) => set({ CURRENT_PORT: v })}>
                      <FormSelectOption value="" label="Automatic (/dev/serial0, then /dev/ttyUSB0)" />
                      {ports.map((p) => <FormSelectOption key={p} value={p} label={p} />)}
                    </FormSelect>
                  </Field>
                  <Field id="sa818-speed" label="Speed">
                    <FormSelect id="sa818-speed" value={draft.CURRENT_SPEED} onChange={(_e, v) => set({ CURRENT_SPEED: v })}>
                      <FormSelectOption value="" label="Default (9600)" />
                      {state.choices.speeds.map((s) => <FormSelectOption key={s} value={s} label={s} />)}
                    </FormSelect>
                  </Field>
                </div>
                <div>
                  <Button variant="secondary" onClick={test} isLoading={busy === "test"} isDisabled={busy !== null || dirty}>
                    Test the connection
                  </Button>{" "}
                  <Button variant="secondary" onClick={() => void hardware.scan(true)} isLoading={hardware.scanning}
                          isDisabled={busy !== null || hardware.scanning}>
                    Look for the module
                  </Button>
                  {dirty && <span className="asl-sub"> (save first to test the new port or speed)</span>}
                </div>
              </Form>
            </CardBody>
          </Card>
        </div>
      </PageSection>
      <PageSection className="asl-save-bar" stickyOnBreakpoint={{ default: "bottom" }} aria-label="Save">
        <div className="asl-save-row">
          <Button onClick={save} isLoading={busy === "save"} isDisabled={busy !== null || !valid || (!dirty && state.saved)}>
            Save and program
          </Button>
          <Button variant="link" onClick={() => setDraft(state.settings)} isDisabled={!dirty || busy !== null}>Discard changes</Button>
          <Button variant="secondary" onClick={program} isLoading={busy === "program"}
                  isDisabled={busy !== null || dirty || !state.saved}>
            Program again
          </Button>
          <span className="asl-sub">
            {!valid ? "Correct the highlighted settings first." : busy === "save" || busy === "program"
              ? "Programming takes about ten seconds." : "Programming changes the frequencies the radio uses at once."}
          </span>
        </div>
      </PageSection>
    </>
  );
}
