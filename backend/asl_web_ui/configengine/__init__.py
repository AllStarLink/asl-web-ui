"""The configuration engine.

text      Lossless line model of one file: every line keeps its exact bytes.
model     Asterisk's view of a configuration (includes, templates, last-wins
          values), reproducing ASL-patched Asterisk.
lint      Findings: errors (Asterisk rejects the file) and warnings
          (something is ignored or overridden).
edit      Intents (set, unset, add_category, ...) planned as minimal line edits.
store     Applying plans: lock, hash check, snapshot, atomic writes.
"""
