import { TextArea, type TextAreaProps, TextInput, type TextInputProps } from "@patternfly/react-core";

// Text fields here hold user names, passwords, node numbers, call signs and
// paths: phones and Safari must not capitalize, correct or spell-check them
// (issues #11 and #13).
const plain = { autoCapitalize: "none", autoCorrect: "off", spellCheck: false } as const;

export function PlainTextInput(props: TextInputProps) {
  return <TextInput {...plain} {...props} />;
}

export function PlainTextArea(props: TextAreaProps) {
  return <TextArea {...plain} {...props} />;
}
