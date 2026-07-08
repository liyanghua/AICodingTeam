from __future__ import annotations

import unittest


class RunAgentActionsTests(unittest.TestCase):
    def test_dispatch_free_text_routes_common_run_agent_intents(self) -> None:
        from growth_dev.team.run_agent import RunAgentContext, dispatch_free_text

        context = RunAgentContext(
            app_config_ref="app.config.json",
            current_focus={"node_id": "strong_hot_gene"},
            runs_snapshot={},
            safety_capsule={},
        )

        self.assertEqual(dispatch_free_text("解释一下这一步为什么没命中", context).route, "explain")
        self.assertEqual(dispatch_free_text("TOP300 数据有问题，帮我重跑", context).route, "rerun_node")
        self.assertEqual(dispatch_free_text("把报告标题文案改短一点", context).route, "patch_app_proposal")
        self.assertEqual(dispatch_free_text("修 bug，改一下规则引擎", context).route, "delegate_code_repair")

    def test_validate_action_request_guards_patch_paths(self) -> None:
        from growth_dev.team.run_agent import validate_action_request

        ok_patch_app = {
            "type": "patch_app",
            "patches": [{"target_path": "generated_apps/demo/app.config.json", "edit_kind": "replace_block"}],
        }
        custom_patch_app = {
            "type": "patch_app",
            "patches": [{"target_path": "generated_apps/demo/custom/report_template.md.tmpl", "edit_kind": "replace_text"}],
        }
        bad_patch_app = {
            "type": "patch_app",
            "patches": [{"target_path": "generated_apps/demo/server.js", "edit_kind": "replace_text"}],
        }
        ok_patch_artifact = {
            "type": "patch_artifact",
            "patches": [{"target_path": "artifacts/implementation/notes.md", "edit_kind": "replace_text"}],
        }
        bad_patch_artifact = {
            "type": "patch_artifact",
            "patches": [{"target_path": "codex/stdout.jsonl", "edit_kind": "replace_text"}],
        }

        self.assertEqual(validate_action_request(ok_patch_app).status, "ok")
        self.assertEqual(validate_action_request(custom_patch_app).status, "ok")
        self.assertEqual(validate_action_request(bad_patch_app).status, "rejected")
        self.assertEqual(validate_action_request(ok_patch_artifact).status, "ok")
        self.assertEqual(validate_action_request(bad_patch_artifact).status, "rejected")


if __name__ == "__main__":
    unittest.main()
