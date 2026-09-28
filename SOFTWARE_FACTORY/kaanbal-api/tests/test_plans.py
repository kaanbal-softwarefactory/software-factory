"""Planes (app/services/plans.py): la huella que ata lo que se vio con lo que se aplica."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import plans  # noqa: E402

PLAN = {"action": "create_app", "name": "tienda-api", "urls": {"prod": "https://tienda-api.ejemplo.com"}}


class PlanIdTests(unittest.TestCase):
    def test_the_same_plan_always_has_the_same_id(self):
        reordered = {"urls": {"prod": "https://tienda-api.ejemplo.com"}, "name": "tienda-api", "action": "create_app"}
        self.assertEqual(plans.plan_id("create_app", PLAN), plans.plan_id("create_app", reordered))
        self.assertRegex(plans.plan_id("create_app", PLAN), r"^[0-9a-f]{16}$")

    def test_any_change_in_the_plan_changes_the_id(self):
        other = {**PLAN, "urls": {"prod": "https://ejemplo.com"}}
        self.assertNotEqual(plans.plan_id("create_app", PLAN), plans.plan_id("create_app", other))

    def test_the_kind_is_part_of_the_id(self):
        """El plan de un stack no sirve para aplicar un alta aunque el contenido coincida."""
        self.assertNotEqual(plans.plan_id("create_app", PLAN), plans.plan_id("launch_stack", PLAN))


class VerifyTests(unittest.TestCase):
    def test_without_plan_id_there_is_nothing_to_verify(self):
        plans.verify("create_app", PLAN, None)
        plans.verify("create_app", PLAN, "")

    def test_the_right_id_passes(self):
        plans.verify("create_app", PLAN, plans.plan_id("create_app", PLAN))

    def test_a_stale_id_is_rejected_with_an_explanation(self):
        stale = plans.plan_id("create_app", {**PLAN, "name": "otra"})
        with self.assertRaises(plans.PlanMismatch) as ctx:
            plans.verify("create_app", PLAN, stale)
        self.assertIn("plan cambió", str(ctx.exception))


class DryRunAnswerTests(unittest.TestCase):
    def test_the_answer_carries_plan_and_id(self):
        answer = plans.dry_run_answer("create_app", PLAN)
        self.assertTrue(answer["dry_run"])
        self.assertEqual(answer["plan"], PLAN)
        self.assertEqual(answer["plan_id"], plans.plan_id("create_app", PLAN))
        self.assertNotIn("notices", answer)

    def test_notices_are_shown_but_not_fingerprinted(self):
        """'Ya hay un stack lanzándose' deja de ser cierto sin que el plan cambie."""
        answer = plans.dry_run_answer("launch_stack", PLAN, notices=["Ya hay un stack lanzándose"])
        self.assertEqual(answer["notices"], ["Ya hay un stack lanzándose"])
        self.assertEqual(answer["plan_id"], plans.plan_id("launch_stack", PLAN))


if __name__ == "__main__":
    unittest.main()
