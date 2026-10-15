import { StreamLanguage, StringStream } from "@codemirror/language";

// Syntax highlighting for Asterisk configuration files: comments (";" and
// ";-- --;" blocks), [section](options) headers, #directives, and
// name = value lines.
type State = { block: number; afterKey: boolean };

export const asteriskConf = StreamLanguage.define<State>({
  name: "asterisk-conf",
  startState: () => ({ block: 0, afterKey: false }),
  token(stream: StringStream, state: State) {
    if (stream.sol()) state.afterKey = false;
    if (state.block > 0) {
      while (!stream.eol()) {
        if (stream.match(";--") && !stream.match("-", false)) state.block++;
        else if (stream.match("--;")) {
          state.block--;
          if (state.block === 0) return "comment";
        } else stream.next();
      }
      return "comment";
    }
    if (stream.eatSpace()) return null;
    if (stream.match("\\;")) return "string";
    if (stream.match(";--") && !stream.match("-", false)) {
      state.block = 1;
      return "comment";
    }
    if (stream.peek() === ";") {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.sol() || stream.string.slice(0, stream.pos).trim() === "") {
      if (stream.match(/^\[[^\]]*\]/)) {
        stream.match(/^\([^)]*\)/);
        return "heading";
      }
      if (stream.match(/^#\w+/)) return "keyword";
      if (stream.match(/^[^=;]+?(?=\s*\+?=>?)/)) {
        state.afterKey = true;
        return "propertyName";
      }
    }
    if (state.afterKey && stream.match(/^\+?=>?/)) return "operator";
    stream.next();
    while (!stream.eol() && stream.peek() !== ";" && !stream.match("\\;", false)) stream.next();
    return state.afterKey ? "string" : null;
  },
  languageData: { commentTokens: { line: ";" } },
});
