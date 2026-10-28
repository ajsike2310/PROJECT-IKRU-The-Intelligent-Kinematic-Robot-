# Team Workflow

## Branching
- `main` is protected: changes land only through a reviewed and approved Pull Request.
- Each member works on their own feature branch (`feature/<topic>-<name>`) with at least two commits.

## Pending work (one issue per member)
| Member | Issue | Branch |
|---|---|---|
| Avin Joy | Add PyTest unit tests for parser, VAD and protocol | `feature/unit-tests-avin` |
| V. Anantha Krishnan | Add GitHub Actions CI workflow | `feature/ci-anantha` |
| Athira S | Add Dockerfile and deployment notes | `feature/docker-athira` |
| Divina Ann Shaji | Write test-case table, Gantt chart and risk log | `feature/docs-divina` |

## Review rule
Reviewers rotate (Avin -> Athira -> Divina -> Anantha -> Avin). Nobody approves their own PR.
