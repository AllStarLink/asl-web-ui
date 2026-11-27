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

// Compatibility API/settings names are retained; visible identity comes from firmware.
// SA818-compatible and exact SR110U V223 modules use distinct programming commands.

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
    out.CURRENT_FREQ_RX = "This programmer supports receive frequencies in the amateur bands only (144-148 or 420-450 MHz).";
  }
  if (s.CURRENT_SR_ADVANCED === "Enabled" && s.CURRENT_SR_VOX !== "0" && s.CURRENT_SR_POWER_SAVING === "Enabled") {
    out.CURRENT_SR_POWER_SAVING = "Disable power saving before enabling VOX.";
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

function moduleName(firmware: string | null | undefined): string {
  if (/^(SR)?110U-V/.test(firmware || "")) return "SR110U";
  if (/^SA[0-9]+[A-Za-z]*_/.test(firmware || "")) return firmware!.split("_")[0];
  return "Unidentified serial radio";
}

function selectedRadio(hardware: Hardware, draft: SA818Settings) {
  // Match the CLI's automatic port priority, not the order discovery reports devices.
  const ports = draft.CURRENT_PORT ? [draft.CURRENT_PORT] : ["/dev/serial0", "/dev/ttyUSB0"];
  return ports.map((port) => hardware.detect?.found.find((m) => m.port === port &&
    m.speed === (draft.CURRENT_SPEED || "9600"))).find((m) => m !== undefined);
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
  const first = selectedRadio(hardware, draft) ?? detect.found[0];
  if (!first) {
    return (
      <Alert variant="warning" isInline title="No serial radio module answered" actionLinks={again}>
        Nothing answered on {detect.probed.join(", ") || "this server's serial ports"}.{" "}
        {saved ? "The settings below are saved, but the module may be disconnected or powered off." : ""}
      </Alert>
    );
  }
  const where = `${first.port} at ${first.speed}`;
  if (selectedRadio(hardware, draft)) {
    const firmware = first.firmware ? `firmware ${first.firmware}` : "firmware version unavailable";
    return <Alert variant="info" isInline isPlain title={`${moduleName(first.firmware)} module found on ${where} (${firmware}).`} />;
  }
  const chosen = draft.CURRENT_PORT === first.port && draft.CURRENT_SPEED === first.speed;
  return (
    <Alert variant="warning" isInline title={`${moduleName(first.firmware)} module found on ${where}, but the saved connection does not reach it`}
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

// Shared radio form; distinct identities and capability gates on the selected connection.
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
  const stays = useCallback((r: string) => r === "hardware" || r === "hardware/radio" || r === "hardware/sa818" || r === "sa818", []);
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

  const selectedModule = selectedRadio(hardware, draft);
  const sr110u = /^(SR)?110U-V[0-9]+$/.test(selectedModule?.firmware || "");
  const advancedSupported = selectedModule?.firmware === "110U-V223";
  const unsupportedSR = sr110u && !advancedSupported;
  const programmer = sr110u ? "sr110u" : "sa818";
  const programmerAvailable = sr110u ? state.sr110u_tool : state.tool;
  const advancedEnabled = draft.CURRENT_SR_ADVANCED === "Enabled";
  const set = (change: Partial<SA818Settings>) => setDraft({ ...draft, ...change });
  const found = problems(draft, state.choices.bands);
  const valid = Object.keys(found).length === 0;
  const offset = FREQ.test(draft.CURRENT_FREQ_RX) && FREQ.test(draft.CURRENT_FREQ_TX)
    ? Number(draft.CURRENT_FREQ_TX) - Number(draft.CURRENT_FREQ_RX) : 0;

  // As sa818-menu: choosing a tone for one direction when both were None sets both.
  const setTone = (kind: "CTCSS" | "DCS", dir: "RX" | "TX", value: string) => {
    const key = `CURRENT_${kind}_${dir}` as keyof SA818Settings;
    const other = `CURRENT_${kind}_${dir === "RX" ? "TX" : "RX"}` as keyof SA818Settings;
    set({ [key]: value, ...(value !== "None" && draft[key] === "None" && draft[other] === "None" ? { [other]: value } : {}) });
  };

  const finish = (res: SA818Result, saved: boolean) => {
    const noAnswer = res.log.includes("Connection error")
      ? " The module did not answer: check the serial port and speed under Connection." : "";
    setResult(res.programmed && res.unsupported?.length
      ? { variant: "warning", title: "Selected channel, volume and enabled advanced commands accepted. Tail and audio-filter settings are not supported or applied on this module.", log: res.log }
      : res.programmed
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
      setResult(v.ok ? { variant: "success", title: v.firmware
        ? `The module answered: firmware ${v.firmware}.`
        : "The module acknowledged the connection; its firmware version is unavailable.", log: v.log }
        : { variant: "danger", title: "Connection test failed. See the programmer log below.", log: v.log });
    } catch (err) {
      setResult({ variant: "danger", title: message(err), log: [] });
    } finally {
      setBusy(null);
    }
  };

  const ports = [...new Set([...state.ports, ...(draft.CURRENT_PORT ? [draft.CURRENT_PORT] : [])])];
  const [low, high] = state.choices.bands[draft.CURRENT_BAND];
  const onOff = (key: "CURRENT_EMPHASIS" | "CURRENT_FILTER_HIGH_PASS" | "CURRENT_FILTER_LOW_PASS", label: string) => (
    <Switch isDisabled={sr110u} id={`sa818-${key}`} label={label} isChecked={draft[key] === "Enabled"}
            onChange={(_e, v) => set({ [key]: v ? "Enabled" : "Disabled" })} />
  );

  return (
    <>
      <PageSection>
        <div className="asl-stack">
          <Content component="p" className="asl-sub">
            Program SA818-compatible modules or SR110U 110U-V223. These are different module families, not interchangeable protocols.
          </Content>
          {!programmerAvailable && (
            <Alert variant="warning" isInline title={`The ${programmer} command is missing`}>
              Install the matching ASL3 package; no fallback to a different programmer is used.
            </Alert>
          )}
          <Alert variant="info" isInline isPlain
                 title={state.saved ? "Saved settings, not radio readback: these are the values last saved by this page or sa818-menu."
                   : "No settings are saved yet; these are sa818-menu's defaults."} />
          <Detected hardware={hardware} saved={state.saved} draft={draft}
                    onUse={(port, speed) => set({ CURRENT_PORT: port, CURRENT_SPEED: speed })} />
          {!selectedModule?.firmware && <Alert variant="warning" isInline title="Module identity is unverified">
            A connection acknowledgment does not identify a board. The legacy SA818-compatible path remains available;
            SR110U programming requires exact firmware identification. Confirm the module before programming.
          </Alert>}
          {unsupportedSR && <Alert variant="warning" isInline title="Unsupported SR110U firmware — programming blocked">
            Only 110U-V223 is supported. Do not use its commands for another SR110U version.
          </Alert>}
          {advancedSupported && <Alert variant="info" isInline title="SR110U 110U-V223 — dedicated sr110u programmer">
            The 110U-V223 profile supports channel, CTCSS, volume and the advanced controls below. DCS, tail and SA818 audio-filter controls are unavailable.
            Command acknowledgments are not settings readback or RF verification.
          </Alert>}
          {result && (
            <div ref={resultRef} className="asl-scroll-target">
              <Alert variant={result.variant} isInline title={result.title}>
                {result.log.length > 0 && (
                  <ExpandableSection toggleText="Programmer output">
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
                    <Radio isDisabled={sr110u && t === "DCS"} key={t} id={`sa818-tone-${t}`} name="sa818-tone" label={t === "None" ? "None" : t}
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
                    <FormSelect isDisabled={sr110u} id="sa818-tail" value={draft.CURRENT_TAIL_TONE}
                                onChange={(_e, v) => set({ CURRENT_TAIL_TONE: v as SA818Settings["CURRENT_TAIL_TONE"] })}>
                      <FormSelectOption value="Closed" label="Closed (sa818-menu's default)" />
                      <FormSelectOption value="Opened" label="Opened" />
                    </FormSelect>
                  </Field>
                )}
              </Form>
            </CardBody>
          </Card>

          {(advancedSupported || advancedEnabled) && <Card>
            <CardTitle>SR110U advanced settings</CardTitle>
            <CardBody>
              <Form className="asl-node-form" onSubmit={(e) => e.preventDefault()}>
                <Switch id="sr-advanced" label="Apply advanced settings" isChecked={advancedEnabled}
                        onChange={(_e, v) => set({ CURRENT_SR_ADVANCED: v ? "Enabled" : "Disabled" })} />
                <Content component="p" className="asl-sub">
                  Saved selections, not radio readback. Enable to apply all seven controls on Save and program.
                  With this off, channel programming uses busy lock on, high power and companding off; other advanced settings are left unchanged.
                  Scrambling is always off when advanced settings are applied.
                </Content>
                {!advancedSupported && <Alert isInline variant="warning" title="Firmware 110U-V223 must be detected on the selected connection before advanced settings can be programmed." />}
                <div className="asl-form-row">
                  <Field id="sr-busy-lock" label="Busy-channel lock" hint="Block transmission while the receive channel is busy.">
                    <FormSelect id="sr-busy-lock" value={draft.CURRENT_SR_BUSY_LOCK} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_BUSY_LOCK: v as SA818Settings["CURRENT_SR_BUSY_LOCK"] })}>
                      <FormSelectOption value="Enabled" label="On" /><FormSelectOption value="Disabled" label="Off" />
                    </FormSelect>
                  </Field>
                  <Field id="sr-power" label="Transmit power" hint="Module high/low selection; output wattage has not been measured.">
                    <FormSelect id="sr-power" value={draft.CURRENT_SR_POWER} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_POWER: v as SA818Settings["CURRENT_SR_POWER"] })}>
                      <FormSelectOption value="High" label="High" /><FormSelectOption value="Low" label="Low" />
                    </FormSelect>
                  </Field>
                </div>
                <div className="asl-form-row">
                  <Field id="sr-companding" label="Companding" hint="Normally off for a repeater link; the other radio must use a matching setting.">
                    <FormSelect id="sr-companding" value={draft.CURRENT_SR_COMPANDING} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_COMPANDING: v as SA818Settings["CURRENT_SR_COMPANDING"] })}>
                      <FormSelectOption value="Disabled" label="Off" /><FormSelectOption value="Enabled" label="On" />
                    </FormSelect>
                  </Field>
                  <Field id="sr-mic" label="Microphone sensitivity" hint="1 to 8; higher is more sensitive. Separate from AllStar mixer levels.">
                    <FormSelect id="sr-mic" value={draft.CURRENT_SR_MIC} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_MIC: v })}>
                      {Array.from({ length: 8 }, (_, i) => <FormSelectOption key={i + 1} value={String(i + 1)} label={String(i + 1)} />)}
                    </FormSelect>
                  </Field>
                </div>
                <div className="asl-form-row">
                  <Field id="sr-timeout" label="Transmit timeout" hint="Radio timer, separate from AllStar's timeout. Timing has not been RF-tested.">
                    <FormSelect id="sr-timeout" value={draft.CURRENT_SR_TIMEOUT} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_TIMEOUT: v })}>
                      <FormSelectOption value="0" label="Off" />
                      {Array.from({ length: 9 }, (_, i) => <FormSelectOption key={i + 1} value={String(i + 1)} label={`${i + 1} minute${i ? "s" : ""}`} />)}
                    </FormSelect>
                  </Field>
                  <Field id="sr-power-saving" label="Power saving" problem={found.CURRENT_SR_POWER_SAVING}
                         hint="Normally off for a node. Must be off when VOX is enabled.">
                    <FormSelect id="sr-power-saving" value={draft.CURRENT_SR_POWER_SAVING} isDisabled={!advancedEnabled || !advancedSupported}
                                onChange={(_e, v) => set({ CURRENT_SR_POWER_SAVING: v as SA818Settings["CURRENT_SR_POWER_SAVING"] })}>
                      <FormSelectOption value="Disabled" label="Off" /><FormSelectOption value="Enabled" label="On" />
                    </FormSelect>
                  </Field>
                </div>
                <Field id="sr-vox" label="VOX" hint="Off uses normal PTT. 1 to 8 enables voice-triggered transmission; higher is more sensitive. Only the off command has been live-tested.">
                  <FormSelect id="sr-vox" value={draft.CURRENT_SR_VOX} isDisabled={!advancedEnabled || !advancedSupported}
                              onChange={(_e, v) => set({ CURRENT_SR_VOX: v })}>
                    <FormSelectOption value="0" label="Off (normal PTT)" />
                    {Array.from({ length: 8 }, (_, i) => <FormSelectOption key={i + 1} value={String(i + 1)} label={`On — sensitivity ${i + 1}`} />)}
                  </FormSelect>
                </Field>
                {advancedEnabled && draft.CURRENT_SR_VOX !== "0" && <Alert isInline variant="warning" title="Programming this selection enables voice-triggered transmission. Keep VOX off for normal AllStar PTT control." />}
              </Form>
            </CardBody>
          </Card>}

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
          <Button onClick={save} isLoading={busy === "save"} isDisabled={busy !== null || !valid || unsupportedSR || !programmerAvailable || (!dirty && state.saved)}>
            Save and program
          </Button>
          <Button variant="link" onClick={() => setDraft(state.settings)} isDisabled={!dirty || busy !== null}>Discard changes</Button>
          <Button variant="secondary" onClick={program} isLoading={busy === "program"}
                  isDisabled={busy !== null || dirty || !state.saved || unsupportedSR || !programmerAvailable}>
            Program again
          </Button>
          <span className="asl-sub">
            {!valid ? "Correct the highlighted settings first." : busy === "save" || busy === "program"
              ? "Programming may take up to thirty seconds." : "Programming changes the frequencies the radio uses at once."}
          </span>
        </div>
      </PageSection>
    </>
  );
}
