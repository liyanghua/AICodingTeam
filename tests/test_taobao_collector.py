from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class FakeTaobaoDevice:
    def __init__(self, state: str = "home", image_button_misses: bool = False) -> None:
        self.state = state
        self.image_button_misses = image_button_misses
        self.actions: list[tuple[str, str | None]] = []
        self.text = ""

    def current_package(self) -> str:
        return "com.taobao.taobao" if self.state != "other_app" else "other.app"

    def start_app(self, package: str) -> None:
        self.actions.append(("start_app", package))
        self.state = "home"

    def dump_hierarchy(self) -> str:
        markers = {
            "home": "淘宝 搜索 拍照",
            "search_page": "搜索 取消 输入商品",
            "recommendations": "猜你想搜 搜索推荐",
            "album": "相册 全部照片 最近项目",
            "album_confirm": "预览 确定",
            "results": "综合 销量 店铺 商品",
            "detail": "宝贝详情 评价 店铺 加入购物车 立即购买",
            "detail_video": "宝贝详情 播放 00:12 视频 评价 店铺 加入购物车 立即购买",
            "save_menu": "保存图片 保存到相册 取消",
            "risk": "安全验证 请登录 验证码",
        }
        return markers.get(self.state, self.state)

    def tap_profile_point(self, name: str, _point: tuple[float, float]) -> None:
        self.actions.append(("tap", name))
        if name == "home_search_box":
            self.state = "search_page"
        elif name == "image_search_button":
            self.state = "recommendations" if self.image_button_misses else "album"
        elif name == "album_entry":
            self.state = "album"
        elif name == "first_album_image":
            self.state = "album_confirm"
        elif name == "album_confirm":
            self.state = "results"
        elif name.startswith("result_card"):
            self.state = "detail"
        elif name in {"save_image_button", "save_image_button_detected"}:
            self.state = "detail"
        elif name == "detail_back_button":
            self.state = "results"

    def long_press_profile_point(self, name: str, _point: tuple[float, float], duration: float = 1.0) -> None:
        self.actions.append(("long_press", name))
        if name in {"detail_main_image", "detail_main_image_detected"}:
            self.state = "save_menu"

    def swipe_profile_points(
        self,
        name: str,
        _start: tuple[float, float],
        _end: tuple[float, float],
        duration: float = 0.3,
    ) -> None:
        self.actions.append(("swipe", name))
        if self.state == "detail_video":
            self.state = "detail"

    def set_text(self, text: str) -> None:
        self.actions.append(("set_text", text))
        self.text = text

    def press_enter(self) -> None:
        self.actions.append(("press_enter", None))
        self.state = "results"

    def press_back(self) -> None:
        self.actions.append(("press_back", None))
        self.state = "home"

    def save_screenshot(self, path: Path) -> None:
        self.actions.append(("screenshot", path.name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-taobao-image")


class FakeTaobaoMediaStore:
    def __init__(self, auto_record: bool = True) -> None:
        self.auto_record = auto_record
        self.paths: list[str] = []
        self.payloads: dict[str, bytes] = {}
        self.pulled: list[tuple[str, Path]] = []
        self.refreshed = False

    def snapshot(self) -> list[str]:
        return list(self.paths)

    def record_saved_image(self) -> str | None:
        if not self.auto_record:
            return None
        remote_path = f"/sdcard/Pictures/taobao/saved_{len(self.paths) + 1}.jpg"
        self.paths.append(remote_path)
        self.payloads[remote_path] = f"pulled:{remote_path}".encode("utf-8")
        return remote_path

    def pull(self, remote_path: str, target_path: Path) -> Path:
        self.pulled.append((remote_path, target_path))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(self.payloads.get(remote_path, b"pulled-taobao-detail"))
        return target_path

    def refresh(self) -> None:
        self.refreshed = True


class FailingSendKeysDevice:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_keys(self, text: str, clear: bool = False) -> None:
        self.calls.append(("send_keys", f"{text}|clear={clear}"))
        raise RuntimeError(
            "broadcast ADB_KEYBOARD_CLEAR_TEXT failed: error:Attempt to read from "
            "field 'java.lang.CharSequence android.view.inputmethod.ExtractedText.text' "
            "on a null object reference in method "
            "'void com.github.uiautomator.AdbKeyboard.clearText()'"
        )


class RecordingAdb:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.commands: list[str] = []

    def shell(self, command: str) -> str:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("adb input failed")
        return ""


def _profile_dict() -> dict:
    return {
        "points": {
            "home_search_box": [0.5, 0.08],
            "image_search_button": [0.9, 0.08],
            "album_entry": [0.5, 0.88],
            "first_album_image": [0.16, 0.22],
            "album_confirm": [0.88, 0.95],
            "result_card": [0.5, 0.34],
            "result_card_1": [0.25, 0.34],
            "detail_main_image": [0.5, 0.35],
            "save_image_button": [0.5, 0.82],
            "detail_back_button": [0.06, 0.07],
        }
    }


def _taobao_result_list_xml() -> str:
    return """
<hierarchy>
  <node package="com.taobao.taobao" text="全部" />
  <node package="com.taobao.taobao" text="品牌" />
  <node package="com.taobao.taobao" text="官方自营" />
  <node package="com.taobao.taobao" text="SOAIY索爱旗舰无线领夹麦" />
  <node package="com.taobao.taobao" text="1000+人加购" />
  <node package="com.taobao.taobao" text="政府补贴15%已售4万+" />
  <node package="com.taobao.taobao" text="¥126.65政补后" />
  <node package="com.taobao.taobao" text="SOAIY旗舰店" />
  <node package="com.taobao.taobao" text="国补专区" />
</hierarchy>
"""


def _taobao_home_with_search_bar_xml() -> str:
    return """
<hierarchy rotation="0">
  <node bounds="[0,0][1200,2670]" package="com.taobao.taobao">
    <node resource-id="com.taobao.taobao:id/search_bar_container" bounds="[0,0][1200,369]">
      <node resource-id="com.taobao.taobao:id/search_view" bounds="[0,243][1200,369]">
        <node content-desc="搜索栏" clickable="true" focusable="true" focused="false" bounds="[205,254][840,356]" />
        <node content-desc="拍立淘" clickable="true" bounds="[840,266][917,343]" />
        <node content-desc="搜索" clickable="true" bounds="[946,260][1160,350]" />
      </node>
    </node>
    <node content-desc="首页" selected="true" bounds="[0,2454][240,2622]" />
  </node>
</hierarchy>
"""


class TaobaoCollectorTests(unittest.TestCase):
    def test_coordinate_profile_reports_missing_points(self) -> None:
        from third_party.taobao_collector.taobao_collector.coordinates import (
            CoordinateProfile,
        )

        profile = _profile_dict()
        del profile["points"]["album_entry"]
        with self.assertRaisesRegex(ValueError, "missing coordinate point: album_entry"):
            CoordinateProfile.from_dict(profile)

    def test_config_rejects_invalid_mode_and_counts(self) -> None:
        from third_party.taobao_collector.taobao_collector.models import TaobaoConfig

        with self.assertRaisesRegex(ValueError, "mode must be one of"):
            TaobaoConfig.from_dict({"mode": "xhs"})
        with self.assertRaisesRegex(ValueError, "top_n must be >= 1"):
            TaobaoConfig.from_dict({"top_n": 0})

    def test_image_search_gate_does_not_click_album_when_camera_misses(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            ref = root / "reference.jpg"
            ref.write_bytes(b"reference")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "image_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = FakeTaobaoDevice(image_button_misses=True)

            manifest = run_taobao_flow(
                TaobaoRequest(mode="image_search", input_image=ref, top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "failed")
            self.assertIn(
                "taobao_image_search_album_not_reached",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertNotIn(("tap", "album_entry"), device.actions)
            events = (manifest.output_dir / "step_events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("taobao_image_search_button_not_on_album_page", events)

    def test_keyword_search_stops_on_risk_prompt_before_collecting_results(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = FakeTaobaoDevice(state="risk")

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "failed")
            self.assertEqual(manifest.assets, [])
            self.assertIn(
                "taobao_risk_prompt_detected",
                {event["event"] for event in manifest.risk_events},
            )

    def test_taobao_home_with_system_payment_notification_is_not_risk(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import classify_page_state

        hierarchy = """
        <hierarchy>
          <node package="com.android.systemui" content-desc="支付宝通知：" text="" />
          <node package="com.taobao.taobao" content-desc="搜索栏" text="" bounds="[50,150][900,240]" />
          <node package="com.taobao.taobao" content-desc="购物车" text="" bounds="[720,2454][960,2622]" />
          <node package="com.taobao.taobao" content-desc="首页" selected="true" text="" />
        </hierarchy>
        """

        self.assertEqual(classify_page_state(hierarchy)["state"], "home")

    def test_taobao_home_feed_with_product_markers_is_still_home(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import classify_page_state

        hierarchy = """
        <hierarchy>
          <node package="com.taobao.taobao" content-desc="搜索栏" text="" bounds="[50,150][900,240]" />
          <node package="com.taobao.taobao" content-desc="首页" selected="true" text="" />
          <node package="com.taobao.taobao" text="猜你喜欢商品" />
          <node package="com.taobao.taobao" text="¥39.90" />
          <node package="com.taobao.taobao" text="品牌店" />
        </hierarchy>
        """

        self.assertEqual(classify_page_state(hierarchy)["state"], "home")

    def test_successful_keyword_run_writes_manifest_csv_html_and_hashes(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                FakeTaobaoDevice(),
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.channel, "taobao")
            self.assertEqual(manifest.status, "completed")
            self.assertEqual([asset.stage for asset in manifest.assets], ["keyword_search", "detail"])
            self.assertTrue(all(asset.content_sha256 for asset in manifest.assets))

            manifest_json = json.loads(
                (manifest.output_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest_json["channel"], "taobao")
            self.assertEqual(manifest_json["assets"][0]["stage"], "keyword_search")
            csv_text = (manifest.output_dir / "results.csv").read_text(encoding="utf-8")
            self.assertIn("channel,mode,source_item_id,query,stage,rank", csv_text)
            self.assertIn("taobao,keyword_search", csv_text)
            html_text = (manifest.output_dir / "results.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("淘宝采集结果", html_text)
            self.assertIn("keyword_search", html_text)

    def test_successful_image_search_writes_result_and_detail_assets(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            ref = root / "reference.jpg"
            ref.write_bytes(b"reference")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "image_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )

            device = FakeTaobaoDevice()
            manifest = run_taobao_flow(
                TaobaoRequest(mode="image_search", input_image=ref, top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "completed")
            self.assertEqual([asset.stage for asset in manifest.assets], ["image_search", "detail"])
            self.assertIn(("tap", "image_search_button"), device.actions)
            self.assertIn(("tap", "album_entry"), device.actions)

    def test_detail_video_first_swipes_to_non_video_before_saving_detail_image(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class VideoFirstDevice(FakeTaobaoDevice):
            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))
                if name.startswith("result_card"):
                    self.state = "detail_video"
                    return
                if name in {"save_image_button", "save_image_button_detected"}:
                    self.state = "detail"
                    return
                super().tap_profile_point(name, point)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            media_store = FakeTaobaoMediaStore()
            device = VideoFirstDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=media_store,
            )

            self.assertEqual(manifest.status, "completed")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card", "detail_main"])
            self.assertEqual(media_store.pulled[0][0], "/sdcard/Pictures/taobao/saved_1.jpg")
            actions = [action for action, _ in device.actions]
            self.assertLess(actions.index("swipe"), actions.index("long_press"))
            self.assertIn(("tap", "detail_main_image"), device.actions)
            detail_tap_index = device.actions.index(("tap", "detail_main_image"))
            self.assertLess(detail_tap_index, actions.index("long_press"))
            events = (manifest.output_dir / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("taobao_detail_media_video_detected", events)
            self.assertIn("taobao_swipe_detail_media_next", events)
            self.assertIn("taobao_detail_non_video_image_selected", events)
            self.assertIn("taobao_detail_image_stable_before_save", events)
            self.assertIn("taobao_tap_detail_main_image", events)
            self.assertIn("taobao_pull_saved_detail_image", events)

    def test_detail_save_uses_detected_hero_image_bounds_before_long_press(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class HeroBoundsDevice(FakeTaobaoDevice):
            def dump_hierarchy(self) -> str:
                if self.state == "detail":
                    return """
                    <hierarchy>
                      <node package="com.taobao.taobao" text="宝贝详情" bounds="[0,0][1200,2400]" />
                      <node package="com.taobao.taobao"
                            resource-id="com.taobao.taobao:id/iv_image_content"
                            content-desc="商品图片"
                            bounds="[120,240][1080,1200]" />
                      <node package="com.taobao.taobao" text="加入购物车" bounds="[0,2100][600,2400]" />
                      <node package="com.taobao.taobao" text="立即购买" bounds="[600,2100][1200,2400]" />
                    </hierarchy>
                    """
                if self.state == "save_menu":
                    return """
                    <hierarchy>
                      <node package="com.taobao.taobao" text="保存图片" bounds="[240,1500][960,1620]" />
                      <node package="com.taobao.taobao" text="取消" bounds="[240,1700][960,1820]" />
                    </hierarchy>
                    """
                return super().dump_hierarchy()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = HeroBoundsDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "completed")
            self.assertIn(("tap", "detail_main_image_detected"), device.actions)
            self.assertIn(("long_press", "detail_main_image_detected"), device.actions)
            events = (manifest.output_dir / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"point_source": "detected_hero_image"', events)

    def test_detail_save_stops_when_activation_tap_triggers_login(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class LoginAfterTapDevice(FakeTaobaoDevice):
            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))
                if name.startswith("result_card"):
                    self.state = "detail"
                    return
                if name == "detail_main_image":
                    self.state = "risk"
                    return
                super().tap_profile_point(name, point)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = LoginAfterTapDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "partial")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card"])
            self.assertIn(
                "taobao_detail_save_login_triggered",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertNotIn(("long_press", "detail_main_image"), device.actions)
            self.assertNotIn(("tap", "save_image_button"), device.actions)

    def test_detail_save_stops_when_long_press_triggers_login_without_retry(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class LoginAfterLongPressDevice(FakeTaobaoDevice):
            def long_press_profile_point(
                self,
                name: str,
                _point: tuple[float, float],
                duration: float = 1.0,
            ) -> None:
                self.actions.append(("long_press", name))
                if name == "detail_main_image":
                    self.state = "risk"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = LoginAfterLongPressDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "partial")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card"])
            self.assertIn(
                "taobao_detail_save_login_triggered",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertEqual(
                [action for action, point in device.actions if action == "long_press"],
                ["long_press"],
            )
            self.assertNotIn(("tap", "save_image_button"), device.actions)

    def test_detail_gallery_selected_with_unselected_video_tab_is_not_video(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import (
            is_detail_video_media,
        )

        hierarchy = """
        <hierarchy>
          <node package="com.taobao.taobao"
                resource-id="com.taobao.taobao:id/iv_image_content"
                class="android.widget.ImageView"
                content-desc="商品图片"
                visible-to-user="true"
                bounds="[0,0][1200,1200]" />
          <node package="com.taobao.taobao"
                class="android.widget.LinearLayout"
                content-desc="视频"
                selected="false"
                bounds="[984,1122][1092,1200]">
            <node package="com.taobao.taobao" text="视频" selected="false" />
          </node>
          <node package="com.taobao.taobao"
                class="android.widget.LinearLayout"
                content-desc="图集"
                selected="true"
                bounds="[1092,1122][1200,1200]">
            <node package="com.taobao.taobao" text="图集" selected="true" />
          </node>
        </hierarchy>
        """

        self.assertFalse(is_detail_video_media(hierarchy))

    def test_detail_selected_video_tab_is_video(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import (
            is_detail_video_media,
        )

        hierarchy = """
        <hierarchy>
          <node package="com.taobao.taobao"
                class="android.widget.FrameLayout"
                content-desc="播放"
                selected="false"
                bounds="[0,0][1200,1200]" />
          <node package="com.taobao.taobao"
                class="android.widget.LinearLayout"
                content-desc="视频"
                selected="true"
                bounds="[984,1122][1092,1200]">
            <node package="com.taobao.taobao" text="视频" selected="true" />
          </node>
          <node package="com.taobao.taobao"
                class="android.widget.LinearLayout"
                content-desc="图集"
                selected="false"
                bounds="[1092,1122][1200,1200]" />
        </hierarchy>
        """

        self.assertTrue(is_detail_video_media(hierarchy))

    def test_detail_all_video_media_records_failure_without_saving_detail_asset(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class AllVideoDevice(FakeTaobaoDevice):
            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))
                if name.startswith("result_card"):
                    self.state = "detail_video"
                    return
                super().tap_profile_point(name, point)

            def swipe_profile_points(
                self,
                name: str,
                _start: tuple[float, float],
                _end: tuple[float, float],
                duration: float = 0.3,
            ) -> None:
                self.actions.append(("swipe", name))
                self.state = "detail_video"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                    "detail_media_scan_max": 3,
                }
            )
            device = AllVideoDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "partial")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card"])
            self.assertIn(
                "taobao_detail_non_video_image_not_found",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertNotIn(("long_press", "detail_main_image"), device.actions)

    def test_detail_save_menu_missing_records_failure_without_detail_asset(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class MissingSaveMenuDevice(FakeTaobaoDevice):
            def long_press_profile_point(self, name: str, _point: tuple[float, float], duration: float = 1.0) -> None:
                self.actions.append(("long_press", name))
                self.state = "detail"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                MissingSaveMenuDevice(),
                media_store=FakeTaobaoMediaStore(),
            )

            self.assertEqual(manifest.status, "partial")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card"])
            self.assertIn(
                "taobao_detail_save_menu_not_found",
                {event["event"] for event in manifest.risk_events},
            )

    def test_detail_save_no_new_media_retries_once_then_records_failure(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = FakeTaobaoDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
                media_store=FakeTaobaoMediaStore(auto_record=False),
            )

            self.assertEqual(manifest.status, "partial")
            self.assertEqual([asset.image_type for asset in manifest.assets], ["result_card"])
            self.assertIn(
                "taobao_detail_save_no_new_media",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertEqual(
                [action for action, point in device.actions if action == "long_press"],
                ["long_press", "long_press"],
            )

    def test_risk_events_are_written_to_dedicated_jsonl(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                FakeTaobaoDevice(state="risk"),
            )

            risk_log = manifest.output_dir / "risk_events.jsonl"
            self.assertTrue(risk_log.exists())
            self.assertIn("taobao_risk_prompt_detected", risk_log.read_text(encoding="utf-8"))

    def test_cli_dry_run_writes_outputs_without_connecting_device(self) -> None:
        from third_party.taobao_collector.taobao_collector.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            runs_root = root / "runs"

            with mock.patch("builtins.print") as printed:
                exit_code = main(
                    [
                        "run",
                        "--dry-run",
                        "--mode",
                        "keyword_search",
                        "--keyword",
                        "红白格桌垫",
                        "--top-n",
                        "1",
                        "--coordinate-profile",
                        str(profile),
                        "--runs-root",
                        str(runs_root),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(printed.call_args.args[0])
            output_dir = Path(payload["output_dir"])
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["asset_count"], 2)
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "results.csv").exists())
            self.assertTrue((output_dir / "results.html").exists())

    def test_real_taobao_result_xml_is_recognized_as_result_page(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import classify_page_state

        hierarchy = _taobao_result_list_xml()

        state = classify_page_state(hierarchy)

        self.assertEqual(state["state"], "result_list")
        self.assertIn("旗舰店", state["matched_markers"])

    def test_home_and_recommendation_pages_are_not_result_pages(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import classify_page_state

        self.assertEqual(classify_page_state("淘宝 搜索 拍照 潮玩盲盒")["state"], "home")
        self.assertEqual(
            classify_page_state("猜你想搜 搜索推荐 历史搜索")["state"],
            "recommendation",
        )

    def test_home_search_bar_xml_is_not_keyword_input_page(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import (
            is_keyword_input_page,
        )

        self.assertFalse(is_keyword_input_page(_taobao_home_with_search_bar_xml()))
        self.assertTrue(is_keyword_input_page("搜索 取消 输入商品"))

    def test_keyword_search_uses_detected_home_search_bar_bounds_before_profile_point(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class HomeSearchBarBoundsDevice(FakeTaobaoDevice):
            def dump_hierarchy(self) -> str:
                if self.state == "home":
                    return _taobao_home_with_search_bar_xml()
                return super().dump_hierarchy()

            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", f"{name}:{point[0]:.3f},{point[1]:.3f}"))
                if name == "home_search_box_detected":
                    self.state = "search_page"
                    return
                if name == "home_search_box":
                    return
                super().tap_profile_point(name, point)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = HomeSearchBarBoundsDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "completed")
            self.assertTrue(
                any(
                    action == "tap" and value.startswith("home_search_box_detected:0.435,0.114")
                    for action, value in device.actions
                    if value is not None
                )
            )

    def test_keyword_search_uses_accessibility_search_bar_before_coordinates(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class AccessibilitySearchBarDevice(FakeTaobaoDevice):
            def dump_hierarchy(self) -> str:
                if self.state == "home":
                    return _taobao_home_with_search_bar_xml()
                return super().dump_hierarchy()

            def tap_by_description(self, description: str) -> bool:
                self.actions.append(("tap_by_description", description))
                if description == "搜索栏":
                    self.state = "search_page"
                    return True
                return False

            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = AccessibilitySearchBarDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "completed")
            self.assertIn(("tap_by_description", "搜索栏"), device.actions)
            self.assertNotIn(("tap", "home_search_box_detected"), device.actions)

    def test_keyword_search_retries_profile_point_when_detected_home_search_tap_misses(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class DetectedTapMissDevice(FakeTaobaoDevice):
            def dump_hierarchy(self) -> str:
                if self.state == "home":
                    return _taobao_home_with_search_bar_xml()
                return super().dump_hierarchy()

            def tap_profile_point(self, name: str, point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))
                if name == "home_search_box":
                    self.state = "search_page"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = DetectedTapMissDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "completed")
            self.assertIn(("tap", "home_search_box_detected"), device.actions)
            self.assertIn(("tap", "home_search_box"), device.actions)
            events = (manifest.output_dir / "step_events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("taobao_home_search_box_click_not_on_input_page", events)

    def test_keyword_search_does_not_type_when_home_tap_does_not_open_input_page(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class SearchTapMissDevice(FakeTaobaoDevice):
            def tap_profile_point(self, name: str, _point: tuple[float, float]) -> None:
                self.actions.append(("tap", name))
                if name != "home_search_box":
                    super().tap_profile_point(name, _point)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )
            device = SearchTapMissDevice()

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                device,
            )

            self.assertEqual(manifest.status, "failed")
            self.assertIn(
                "taobao_search_page_not_reached",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertNotIn(("set_text", "红白格桌垫"), device.actions)

    def test_set_text_falls_back_to_adb_when_uiautomator_clear_text_fails(self) -> None:
        from third_party.taobao_collector.taobao_collector.device import (
            UiautomatorTaobaoDevice,
        )

        taobao_device = UiautomatorTaobaoDevice(FailingSendKeysDevice(), serial="serial")
        recorder = RecordingAdb()
        taobao_device._adb = recorder

        taobao_device.set_text("红白格桌垫")

        self.assertTrue(
            any("ADB_INPUT_B64" in command for command in recorder.commands),
            recorder.commands,
        )
        self.assertFalse(any("input text '红白格桌垫'" in command for command in recorder.commands))
        self.assertTrue(any("keyevent" in command for command in recorder.commands))

    def test_set_text_failure_is_recorded_as_keyword_input_failure(self) -> None:
        from third_party.taobao_collector.taobao_collector.flow import run_taobao_flow
        from third_party.taobao_collector.taobao_collector.models import (
            TaobaoConfig,
            TaobaoRequest,
        )

        class BrokenInputDevice(FakeTaobaoDevice):
            def set_text(self, text: str) -> None:
                raise RuntimeError("adb input failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "taobao_coordinates.json"
            profile.write_text(json.dumps(_profile_dict()), encoding="utf-8")
            config = TaobaoConfig.from_dict(
                {
                    "mode": "keyword_search",
                    "top_n": 1,
                    "output_root": str(root / "runs"),
                    "coordinate_profile": str(profile),
                    "wait_timeout_seconds": 0,
                }
            )

            manifest = run_taobao_flow(
                TaobaoRequest(mode="keyword_search", keyword="红白格桌垫", top_n=1),
                config,
                BrokenInputDevice(),
            )

            self.assertEqual(manifest.status, "failed")
            self.assertIn(
                "taobao_keyword_text_input_failed",
                {event["event"] for event in manifest.risk_events},
            )
            self.assertIn(
                "taobao_keyword_text_input_failed",
                (manifest.output_dir / "risk_events.jsonl").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
