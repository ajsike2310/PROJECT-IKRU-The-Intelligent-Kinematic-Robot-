# IKRU Documentation

| What | Where |
|---|---|
| Full codebase manual and developer handbook | [`HOW_IKRU_WORKS.md`](HOW_IKRU_WORKS.md) |
| Diagrams (interactive HTML + JSON source) | [`diagrams/`](diagrams/) |
| Hardware photos | [`images/`](images/) |

## Diagrams

Open any `.html` file in a browser. Each one is self-contained and supports pan/zoom, search, light/dark themes, guided views, and PNG/SVG export. The `.json` next to it is the editable source.

| # | Diagram | Shows | Files |
|---|---|---|---|
| 1 | System architecture | The three computers (PC, ESP32 body, ESP32-CAM head) and the main Python components | [html](diagrams/01-system-architecture/system-architecture.html) · [json](diagrams/01-system-architecture/system-architecture.json) |
| 2 | Use case | What the desk user and the developer can do with IKRU | [html](diagrams/02-use-case/use-case.html) · [json](diagrams/02-use-case/use-case.json) |
| 3 | Class | Core Python classes, their key methods, and ownership/usage relations | [html](diagrams/03-class/class-diagram.html) · [json](diagrams/03-class/class-diagram.json) |
| 4 | Activity | One conversation turn: hear → screen → think → speak → move → resume | [html](diagrams/04-activity/activity-diagram.html) · [json](diagrams/04-activity/activity-diagram.json) |
| 5 | Sequence | Messages exchanged for "move forward 2 seconds", from speech to motor commands | [html](diagrams/05-sequence/sequence-diagram.html) · [json](diagrams/05-sequence/sequence-diagram.json) |
| 6 | DFD Level 1 | The five top-level processes (1.0–5.0), external entities and data stores | [html](diagrams/06-dfd-level-1/dfd-level-1.html) · [json](diagrams/06-dfd-level-1/dfd-level-1.json) |
| 7 | DFD Level 2 | Process 2.0 *Converse* decomposed into 2.1–2.6 | [html](diagrams/07-dfd-level-2/dfd-level-2.html) · [json](diagrams/07-dfd-level-2/dfd-level-2.json) |
| 8 | DFD Level 3 | Process 2.4 *Query LLM* (`ChatEngine.ask`) decomposed into 2.4.1–2.4.4 | [html](diagrams/08-dfd-level-3/dfd-level-3.html) · [json](diagrams/08-dfd-level-3/dfd-level-3.json) |

### Notation notes
- Diagrams are rendered with the Archify skill. The use-case and class diagrams approximate UML: actors and use cases are boxes inside a system boundary, and classes show their key methods as a subtitle rather than UML compartments.
- DFD numbering follows the usual convention. Level 1 processes are `1.0`–`5.0`, Level 2 expands `2.0` into `2.1`–`2.6`, and Level 3 expands `2.4` into `2.4.1`–`2.4.4`. Data stores are `D1`–`D3`, and grey boxes are external entities or neighbouring processes from the level above.
- The system-architecture diagram links each node to its source file. Those links resolve against a local checkout (`link_mode: local-only`).

### Regenerating a diagram
Edit the `.json`, then from the repository root:
```bash
node ~/.claude/skills/archify/bin/archify.mjs deliver <type> docs/diagrams/<folder>/<name>.json docs/diagrams/<folder>/<name>.html --quality showcase --json
```
`<type>` is `architecture` (1–3), `workflow` (4), `sequence` (5) or `dataflow` (6–8). The architecture diagram also needs `--repo-root .`, because it cites source files.
