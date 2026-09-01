"""EARS traceability (E4)."""

from __future__ import annotations

import unittest

from cecli.spec.ears import analyze_traceability

REQ = """\
### REQ-001
**WHEN** the user saves
**THE** system **SHALL** persist specs.

### REQ-002
**WHEN** the user traces
**THE** system **SHALL** report gaps.
"""

DESIGN = """\
## Overview
Covers REQ-001 in the persistence layer.
"""

TASKS = """\
- [ ] 1. Wire HTTP for REQ-002 (depends: none)
- [x] 2. Add tests (depends: 1)
"""


class TestEarsTrace(unittest.TestCase):
    def test_links_and_uncovered_warning(self):
        r = analyze_traceability(REQ, DESIGN, TASKS)
        by_id = {link.req_id: link for link in r.links}
        self.assertTrue(by_id["REQ-001"].in_design)
        self.assertIn(1, by_id["REQ-002"].task_steps)
        self.assertEqual(len(r.steps), 2)

        bare = analyze_traceability(REQ, "", "")
        self.assertTrue(any(i.code == "TRACE_REQ_UNCOVERED" for i in bare.issues))

    def test_unknown_req_in_tasks_errors(self):
        r = analyze_traceability(
            REQ,
            DESIGN,
            "- [ ] 1. Fix REQ-999 (depends: none)\n",
        )
        self.assertFalse(r.ok)
        self.assertTrue(any(i.code == "TRACE_REQ_UNKNOWN" for i in r.issues))


if __name__ == "__main__":
    unittest.main()
