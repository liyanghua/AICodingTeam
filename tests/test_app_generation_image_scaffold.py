"""
Test image generation app scaffold (deterministic fallback).

规范来源: docs/app_generation_prd_to_local_app_spec.md § 图片生成类 PRD 要求
"""

import tempfile
import unittest
from pathlib import Path


class ImageAppScaffoldTests(unittest.TestCase):
    """Test that image generation PRDs trigger correct deterministic scaffold."""

    def test_image_prd_triggers_full_image_scaffold(self) -> None:
        """
        图片类 PRD（包含「图片生成」「主图生成」「生图」等关键词）触发时，
        deterministic 脚手架必须包含：
        - GET /api/health
        - POST /api/images/generate
        - provider 配置状态徽标（不显示 key）
        - 模型选择 UI
        - AGENT_EDIT 锚点（便于 patch_app）
        - .env.example（占位 key，无真实 secret）
        - README 配置段（明确说明在服务端 .env 配置 API_KEY）
        
        禁止：
        - 前端 API_KEY 输入框
        - localStorage 保存 key
        - config.json 持久化 key
        """
        from growth_dev.team.app_generation import generate_deterministic_app_files

        prd_text = """# 叮当主图生成 Agent

## 产品需求

电商运营需要批量生成主图，提供产品图、参考图上传，选择模型，一键生成 8 张主图。

## 核心流程

1. 上传产品图、参考图
2. 选择图片生成模型（OpenAI / OpenRouter）
3. 单张生成或批量生成
4. 下载 Prompt 和图片

## 技术要求

- 前端：原生 SPA，模型选择，provider 配置状态显示
- 后端：Node stdlib，GET /api/health + POST /api/images/generate
- 配置：服务端 .env，不暴露 API_KEY
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            contract = {
                "generated_app_dir": "generated_apps/dingdang",
                "preview": {"url": "http://127.0.0.1:8788"},
            }

            files = generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="dingdang",
                prd_text=prd_text,
                contract=contract,
                repo_root=run_dir,
            )

            # 断言生成了 .env.example
            self.assertIn("generated_apps/dingdang/.env.example", files)
            env_example = (run_dir / "generated_apps/dingdang/.env.example").read_text(encoding="utf-8")
            
            # .env.example 必须包含占位 key 和默认模型，不含真实 secret
            self.assertIn("OPENROUTER_API_KEY", env_example)
            self.assertIn("OPENROUTER_IMAGE_MODEL", env_example)
            self.assertNotIn("sk-or-v1-real", env_example)  # 无真实 key
            self.assertNotIn("your-real-key-here", env_example)

            # server.js 必须包含 GET /api/health 和 POST /api/images/generate
            server_js = (run_dir / "generated_apps/dingdang/server.js").read_text(encoding="utf-8")
            self.assertIn("/api/health", server_js)
            self.assertIn("/api/images/generate", server_js)
            # 必须有 method 路由判断
            self.assertIn("GET", server_js)
            self.assertIn("POST", server_js)
            
            # server.js 必须从 process.env 读 API_KEY，不从请求体或文件读
            self.assertIn("process.env.OPENROUTER_API_KEY", server_js)
            self.assertNotIn("req.body.api_key", server_js.lower())
            self.assertNotIn("config.json", server_js)

            # index.html 必须包含模型选择和 provider 配置状态徽标
            index_html = (run_dir / "generated_apps/dingdang/public/index.html").read_text(encoding="utf-8")
            # 模型选择可能是 select 或 button group
            self.assertTrue(
                "模型" in index_html or "model" in index_html.lower(),
                "index.html 必须包含模型选择 UI"
            )
            # provider 配置状态徽标（显示「未配置 / 已配置 / 错误」，不显示 key）
            self.assertTrue(
                "配置状态" in index_html or "provider" in index_html.lower() or "status" in index_html.lower(),
                "index.html 必须包含 provider 配置状态徽标"
            )
            
            # index.html 禁止 API_KEY 输入框（精确扫 input 元素的 id/name/placeholder/aria-label）
            html_lower = index_html.lower()
            # 不能有 password 类型输入（通常用于 API key）
            self.assertNotIn('type="password"', html_lower)
            # 不能有 input/textarea 的 id/name 含 api_key / apikey
            import re as _re
            input_with_key = _re.search(
                r'<(?:input|textarea)[^>]*(?:id|name|placeholder|aria-label)\s*=\s*"[^"]*(?:api[_-]?key|apikey)[^"]*"',
                html_lower,
            )
            self.assertIsNone(
                input_with_key,
                f"index.html 不得包含 API_KEY 输入框，命中: {input_with_key.group(0) if input_with_key else ''}"
            )

            # app.js 必须包含 fetchHealth 和 callImageModel（或类似命名）
            app_js = (run_dir / "generated_apps/dingdang/public/app.js").read_text(encoding="utf-8")
            self.assertTrue(
                "/api/health" in app_js,
                "app.js 必须调用 /api/health"
            )
            self.assertTrue(
                "/api/images/generate" in app_js or "/api/images" in app_js,
                "app.js 必须调用 /api/images/generate"
            )
            
            # app.js 禁止 localStorage 真实持久化 API_KEY（精确扫 setItem 调用）
            # 允许 localStorage 保存模型选择、任务状态等，但 setItem 的 key 不能含 api_key / apikey
            setitem_with_key = _re.search(
                r"""localStorage\.setItem\s*\(\s*['"][^'"]*(?:api[_-]?key|apikey)[^'"]*['"]""",
                app_js,
                _re.IGNORECASE,
            )
            self.assertIsNone(
                setitem_with_key,
                f"app.js 不得用 localStorage 保存 API_KEY，命中: {setitem_with_key.group(0) if setitem_with_key else ''}"
            )

            # index.html 或 app.js 必须包含 AGENT_EDIT 锚点（便于 patch_app replace_block）
            has_agent_edit_anchor = "AGENT_EDIT:" in index_html or "AGENT_EDIT:" in app_js or "AGENT_EDIT:" in server_js
            self.assertTrue(
                has_agent_edit_anchor,
                "图片应用脚手架必须包含至少一个 AGENT_EDIT 锚点，便于 patch_app"
            )

            # README 必须包含「如何在服务端配置 API_KEY」段落
            readme = (run_dir / "generated_apps/dingdang/README.md").read_text(encoding="utf-8")
            self.assertTrue(
                "API_KEY" in readme or "api key" in readme.lower() or ".env" in readme,
                "README 必须说明如何在服务端配置 API_KEY"
            )
            self.assertTrue(
                "服务端" in readme or "server" in readme.lower() or "process.env" in readme,
                "README 必须明确 API_KEY 配置在服务端"
            )

    def test_non_image_prd_uses_generic_scaffold(self) -> None:
        """
        非图片类 PRD（普通 TODO、笔记应用）不触发图片脚手架，
        仍然生成通用 SPA 骨架（无 /api/health、无 .env.example）。
        """
        from growth_dev.team.app_generation import generate_deterministic_app_files

        prd_text = """# TODO 应用

简单的 TODO 列表，支持新增、删除、标记完成。

## 技术栈

- 前端：原生 SPA
- 后端：Node stdlib HTTP
- 存储：localStorage
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            contract = {
                "generated_app_dir": "generated_apps/todo",
                "preview": {"url": "http://127.0.0.1:8788"},
            }

            files = generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="todo",
                prd_text=prd_text,
                contract=contract,
                repo_root=run_dir,
            )

            # 非图片 PRD 不生成 .env.example
            self.assertNotIn("generated_apps/todo/.env.example", files)

            # server.js 不包含 /api/health 或 /api/images/generate
            server_js = (run_dir / "generated_apps/todo/server.js").read_text(encoding="utf-8")
            self.assertNotIn("/api/health", server_js)
            self.assertNotIn("/api/images", server_js)


if __name__ == "__main__":
    unittest.main()