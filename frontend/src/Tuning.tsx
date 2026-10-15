import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  FormSelect,
  FormSelectOption,
  Gallery,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Slider,
  Spinner,
  Switch,
  TextInput,
} from "@patternfly/react-core";

import { get, message, openSocket, post, Status } from "./api";
import { Started } from "./backupsApi";
import { Console } from "./Console";
import { DiffView } from "./DiffView";
import { useJob } from "./Job";

type TuneSetting = {
  name: string;
  label: string;
  kind: "level" | "bool" | "choice" | "delay";
  value: number | boolean | null;
  help: string;
  options: { value: number; label: string }[];
  needs_device: boolean;
};
type TuneState = {
  interface: string;
  device: string;
  usb: string | null;
  settings: TuneSetting[];
  calibrations: { name: string; description: string }[];
  locked: boolean;
  locked_message: string | null;
  unsaved: boolean;
  tui_running: boolean;
  classic_menu: boolean;
  meter_marks: Record<string, number>;
  ptt_config: { invert: boolean; file: string } | null;
};
type Meter = { keyed: boolean; level: number; columns: number };
type RxTx = { cos: string; ctcss: string; rx_keyed: boolean; ptt: boolean };

// A live display from the driver, while the toggle is on.
function useLive<T>(node: string, display: "meter" | "status", on: boolean): [T | null, string | null] {
  const [reading, setReading] = useState<T | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (!on) {
      setReading(null);
      return;
    }
    setProblem(null);
    let socket: WebSocket | null = null;
    let cancelled = false;
    openSocket(`ws/tune/${node}/${display}`).then(
      (s) => {
        if (cancelled) {
          s.close();
          return;
        }
        socket = s;
        s.onmessage = (e) => {
          const msg = JSON.parse(e.data as string);
          if (msg.error) setProblem(msg.message ?? msg.error);
          else setReading(msg as T);
        };
        s.onclose = (e) => {
          if (e.code !== 1000 && e.code !== 1005) setProblem("The live display stopped.");
        };
      },
      (err) => setProblem(message(err)),
    );
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [node, display, on]);
  return [reading, problem];
}

function MeterBar({ meter, marks }: { meter: Meter | null; marks: Record<string, number> }) {
  const columns = meter?.columns ?? 75;
  const pct = meter?.keyed ? Math.min(100, (meter.level / columns) * 100) : 0;
  return (
    <div className="asl-meter" aria-label="Receive level">
      <div className="asl-meter-fill" style={{ width: `${pct}%` }} />
      {Object.entries(marks).map(([label, col]) => (
        <div key={label} className="asl-meter-mark" style={{ left: `${(col / columns) * 100}%` }}>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

function Lamp({ label, state }: { label: string; state: string | boolean | undefined }) {
  const on = state === true || state === "keyed";
  const off = state === "off";
  return (
    <div className="asl-lamp">
      <span className={`asl-lamp-dot${on ? " on" : ""}${off ? " disabled" : ""}`} />
      {label}
      <span className="asl-sub">{state === undefined ? "—" : off ? "not used" : on ? "active" : "clear"}</span>
    </div>
  );
}

function LevelControl({ s, onSet, disabled }: { s: TuneSetting; onSet: (v: number) => Promise<void>; disabled: boolean }) {
  const [value, setValue] = useState(Number(s.value ?? 0));
  useEffect(() => setValue(Number(s.value ?? 0)), [s.value]);
  return (
    <div className="asl-level">
      <Slider value={value} min={0} max={999} onChange={(_e, v) => setValue(Math.round(v))} isDisabled={disabled}
              aria-label={s.label} />
      <TextInput value={String(value)} aria-label={`${s.label} value`} type="number" isDisabled={disabled}
                 onChange={(_e, v) => setValue(Math.max(0, Math.min(999, Number(v) || 0)))} className="asl-level-input" />
      <Button variant="secondary" size="sm" isDisabled={disabled || value === s.value} onClick={() => onSet(value)}>
        Apply
      </Button>
    </div>
  );
}

export function TuningPanel({ node, status }: { node: string; status: Status | null }) {
  const [state, setState] = useState<TuneState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [meterOn, setMeterOn] = useState(false);
  const [statusOn, setStatusOn] = useState(false);
  const [saved, setSaved] = useState<{ diff: string; file: string; files?: string[] } | null>(null);
  const [classic, setClassic] = useState(false);
  const [toning, setToning] = useState(false);
  const [jobElement, runJob] = useJob();
  const [meter, meterProblem] = useLive<Meter>(node, "meter", meterOn);
  const [rxtx, statusProblem] = useLive<RxTx>(node, "status", statusOn);
  const touched = useRef(false);

  const load = useCallback(async () => {
    try {
      setState(await get<TuneState>(`tuning/${node}`));
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, [node]);
  useEffect(() => {
    void load();
    return () => {
      // Free the driver for others when leaving the page.
      if (touched.current) void post(`tuning/${node}/release`, {}).catch(() => null);
    };
  }, [load, node]);

  const act = async (fn: () => Promise<unknown>) => {
    setNotice(null);
    touched.current = true;
    try {
      await fn();
    } catch (err) {
      setNotice(message(err));
    }
  };
  const set = (name: string, value: unknown) =>
    act(async () => {
      const res = await post<{ settings: TuneSetting[]; unsaved: boolean }>(`tuning/${node}/set`, { name, value });
      setState((s) => (s ? { ...s, settings: res.settings, unsaved: true } : s));
    });
  const tone = () =>
    act(async () => {
      setToning(true);
      try {
        await post(`tuning/${node}/tone`, {});
      } finally {
        setToning(false);
      }
    });
  const save = () =>
    act(async () => {
      const res = await post<{ diff: string; file: string; files: string[] }>(`tuning/${node}/save`, {});
      setSaved(res);
      setState((s) => (s ? { ...s, unsaved: false } : s));
    });
  const revert = () =>
    act(async () => {
      const res = await post<{ diff: string; file: string; files: string[]; settings: TuneSetting[] }>(`tuning/${node}/revert`, {});
      setSaved(res);
      setState((s) => (s ? { ...s, settings: res.settings, unsaved: false } : s));
    });
  const calibrate = (name: string) =>
    act(async () => {
      touched.current = true;
      await runJob(`Calibrate ${name}`, () => post<Started>(`tuning/${node}/calibrate`, { name }));
      await load();
    });

  if (error) return <Alert variant="warning" isInline title={error} />;
  if (!state) return <Spinner aria-label="Loading" />;
  const noDevice = state.usb === null;
  const levels = state.settings.filter((s) => s.kind === "level");
  const others = state.settings.filter((s) => s.kind !== "level");
  const asteriskDown = status && !status.asterisk.reachable;

  return (
    <div className="asl-stack">
      {jobElement}
      {state.locked && <Alert variant="warning" isInline title={state.locked_message ?? "Someone else is tuning."} />}
      {state.tui_running && (
        <Alert variant="warning" isInline title="A classic tune menu is open over SSH">
          Changes from both places affect the same device; close the other one first.
        </Alert>
      )}
      {asteriskDown && <Alert variant="danger" isInline title="Asterisk is not running, so the interface cannot be tuned." />}
      {noDevice && (
        <Alert variant="warning" isInline title={`No USB sound card is assigned to node ${node}`}>
          Levels, live displays and the test tone need the sound card. Check that it is plugged in, then restart
          Asterisk. The other settings can still be changed.
        </Alert>
      )}
      {notice && <Alert variant="danger" isInline title={notice} />}
      <Gallery hasGutter minWidths={{ default: "100%", xl: "34rem" }}>
        <Card>
          <CardTitle>Live</CardTitle>
          <CardBody>
            <div className="asl-stack">
              <Switch id="tune-meter" label="Receive level" isChecked={meterOn} isDisabled={noDevice}
                      onChange={(_e, v) => { touched.current = true; setMeterOn(v); }} />
              {meterOn && (
                <>
                  <MeterBar meter={meter} marks={state.meter_marks} />
                  <Content component="p" className="asl-sub">
                    {meterProblem ?? (meter?.keyed ? "Receiving." : "Waiting for a signal. Transmit a tone at 3 kHz deviation and set the receive level so the bar reaches the 3 kHz mark.")}
                  </Content>
                </>
              )}
              <Switch id="tune-status" label="COS, CTCSS and PTT" isChecked={statusOn} isDisabled={noDevice}
                      onChange={(_e, v) => { touched.current = true; setStatusOn(v); }} />
              {statusOn && (
                <div className="asl-lamps">
                  <Lamp label="COS in" state={rxtx?.cos} />
                  <Lamp label="CTCSS in" state={rxtx?.ctcss} />
                  <Lamp label="Receiving" state={rxtx?.rx_keyed} />
                  <Lamp label="PTT out" state={rxtx?.ptt} />
                  {statusProblem && <span className="asl-sub">{statusProblem}</span>}
                </div>
              )}
              {statusOn && (
                <Content component="p" className="asl-sub">
                  PTT shows what the driver asks for, not the transmitter itself: with the wrong PTT polarity the
                  radio transmits while this reads clear.
                </Content>
              )}
              <div>
                <Button variant="secondary" onClick={tone} isLoading={toning} isDisabled={noDevice || toning}>
                  {toning ? "Sending test tone…" : "Send test tone"}
                </Button>
                <span className="asl-sub"> Keys the transmitter three times for one second, with a 1 kHz tone.</span>
              </div>
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardTitle>Levels</CardTitle>
          <CardBody>
            <DescriptionList>
              {levels.map((s) => (
                <DescriptionListGroup key={s.name}>
                  <DescriptionListTerm>{s.label}</DescriptionListTerm>
                  <DescriptionListDescription>
                    <LevelControl s={s} onSet={(v) => set(s.name, v)} disabled={noDevice || state.locked} />
                    {s.help && <span className="asl-sub">{s.help}</span>}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              ))}
            </DescriptionList>
          </CardBody>
        </Card>
      </Gallery>
      <Card>
        <CardTitle>Settings</CardTitle>
        <CardBody>
          <DescriptionList isHorizontal className="asl-settings">
            {state.ptt_config && (
              <DescriptionListGroup>
                <DescriptionListTerm>Invert PTT</DescriptionListTerm>
                <DescriptionListDescription>
                  {state.ptt_config.invert ? "Yes (keyed = line open)" : "No (keyed = line grounded)"}
                  <div className="asl-sub">
                    The {state.interface} driver reads this from {state.ptt_config.file} when Asterisk starts; it cannot
                    be changed here. Edit invertptt in Manual Config Edit, then restart Asterisk.
                  </div>
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {others.map((s) => (
              <DescriptionListGroup key={s.name}>
                <DescriptionListTerm>{s.label}</DescriptionListTerm>
                <DescriptionListDescription>
                  {s.kind === "bool" && (
                    <Switch id={`tune-${s.name}`} isChecked={Boolean(s.value)} isDisabled={state.locked}
                            onChange={(_e, v) => set(s.name, v)} aria-label={s.label} />
                  )}
                  {s.kind === "choice" && (
                    <FormSelect value={String(s.value)} onChange={(_e, v) => set(s.name, Number(v))} aria-label={s.label}
                                isDisabled={state.locked} className="asl-select">
                      {s.options.map((o) => <FormSelectOption key={o.value} value={String(o.value)} label={o.label} />)}
                    </FormSelect>
                  )}
                  {s.kind === "delay" && (
                    <FormSelect value={String(s.value)} onChange={(_e, v) => set(s.name, Number(v))} aria-label={s.label}
                                isDisabled={state.locked} className="asl-select">
                      {[0, 20, 40, 60, 100, 200, 300, 500, 1000, 2000].concat(
                        [0, 20, 40, 60, 100, 200, 300, 500, 1000, 2000].includes(Number(s.value)) ? [] : [Number(s.value)],
                      ).map((ms) => <FormSelectOption key={ms} value={String(ms)} label={`${ms} ms`} />)}
                    </FormSelect>
                  )}
                  {s.help && <div className="asl-sub">{s.help}</div>}
                </DescriptionListDescription>
              </DescriptionListGroup>
            ))}
          </DescriptionList>
        </CardBody>
      </Card>
      {state.calibrations.length > 0 && (
        <Card>
          <CardTitle>Calibration</CardTitle>
          <CardBody>
            <div className="asl-stack">
              <Content component="p">Each step needs the signal described, then adjusts the level automatically.</Content>
              {state.calibrations.map((c) => (
                <div key={c.name} className="asl-buttons">
                  <Button variant="secondary" size="sm" isDisabled={noDevice || state.locked}
                          onClick={() => calibrate(c.name)}>Run</Button>
                  <span>{c.description}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
      <Card>
        <CardBody>
          <div className="asl-buttons">
            {state.unsaved && <Label color="orange">Not saved: Asterisk forgets these changes when it restarts</Label>}
            <ActionGroup className="asl-flush">
              <Button onClick={save} isDisabled={state.locked}>Save settings</Button>
              <Button variant="secondary" onClick={revert} isDisabled={state.locked}>Undo this session's changes</Button>
              {state.classic_menu && (
                <Button variant="link" onClick={() => { touched.current = true; setClassic(true); }} isDisabled={state.locked}>
                  Open the classic tune menu
                </Button>
              )}
            </ActionGroup>
          </div>
        </CardBody>
      </Card>
      <Modal isOpen={saved !== null} onClose={() => setSaved(null)} variant="large" aria-labelledby="tune-saved">
        <ModalHeader title={`Saved to ${saved?.file ?? ""}`} labelId="tune-saved" titleIconVariant="success" />
        <ModalBody>
          <div className="asl-stack">
            {saved && (saved.files?.length ?? 0) > 1 && (
              <Content component="p" className="asl-sub">
                The driver saves through Asterisk, which also rewrites the files {saved.file} includes
                ({saved.files?.filter((f) => f !== saved.file).join(", ")}).
              </Content>
            )}
            {saved?.diff ? <DiffView diff={saved.diff} /> : "The file did not change."}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={() => setSaved(null)}>Close</Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={classic} onClose={() => { setClassic(false); void load(); }} variant="large" aria-labelledby="tune-classic">
        <ModalHeader title={`Classic tune menu, node ${node}`} labelId="tune-classic" />
        <ModalBody>
          {classic && (
            <Console status={status} path={`ws/tune-menu/${node}`}
                     note="The text tune menu from the command line, running as the asterisk user." />
          )}
        </ModalBody>
      </Modal>
    </div>
  );
}
