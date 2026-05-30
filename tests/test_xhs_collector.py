from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from xml.sax.saxutils import escape


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    shared_strings: list[str] = []
    string_indexes: dict[str, int] = {}

    def shared_index(value: str) -> int:
        if value not in string_indexes:
            string_indexes[value] = len(shared_strings)
            shared_strings.append(value)
        return string_indexes[value]

    def column_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{column_name(column_index)}{row_index}"
            cells.append(
                f'<c r="{cell_ref}" t="s"><v>{shared_index(str(value))}</v></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    shared_xml = "".join(
        f"<si><t>{escape(value)}</t></si>" for value in shared_strings
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>
""",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">{shared_xml}</sst>
""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>
""",
        )


def _write_xlsx_with_embedded_image(
    path: Path, rows: list[list[str]], image_row_number: int, image_payload: bytes
) -> None:
    _write_xlsx(path, rows)
    original_entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as archive:
        for name in archive.namelist():
            original_entries[name] = archive.read(name)
    sheet_xml = original_entries["xl/worksheets/sheet1.xml"].decode("utf-8")
    original_entries["xl/worksheets/sheet1.xml"] = sheet_xml.replace(
        "</worksheet>",
        '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></worksheet>',
    ).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in original_entries.items():
            archive.writestr(name, payload)
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/drawings/_rels/drawing1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdImage1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.jpg"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/drawings/drawing1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{image_row_number - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:to><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{image_row_number}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="1" name="Picture 1"/><xdr:cNvPicPr/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rIdImage1"/></xdr:blipFill>
      <xdr:spPr/>
    </xdr:pic>
  </xdr:twoCellAnchor>
</xdr:wsDr>
""",
        )
        archive.writestr("xl/media/image1.jpg", image_payload)


class XhsCollectorTests(unittest.TestCase):
    def _basic_download_profile(self):
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        return CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.1, 0.1],
                    "image_search_button": [0.2, 0.2],
                    "album_entry": [0.3, 0.3],
                    "first_album_image": [0.4, 0.4],
                    "album_confirm": [0.5, 0.5],
                    "keyword_search_box": [0.12, 0.08],
                    "keyword_search_submit": [0.88, 0.08],
                    "results_panel_swipe_start": [0.5, 0.82],
                    "results_panel_swipe_end": [0.5, 0.18],
                    "result_card_1": [0.25, 0.3],
                    "result_card_2": [0.75, 0.3],
                    "result_card_3": [0.25, 0.58],
                    "note_main_image": [0.5, 0.4],
                    "save_image_menu_item": [0.5, 0.82],
                    "note_back_button": [0.06, 0.07],
                }
            }
        )

    def test_excel_reader_supports_real_scene_keywords_workbook(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        workbook = (
            Path(__file__).resolve().parents[1]
            / "input_image"
            / "买家秀场景图"
            / "桌垫买家秀_TOP10关键词组合.xlsx"
        )
        if not workbook.exists():
            self.skipTest(f"fixture workbook not found: {workbook}")

        with tempfile.TemporaryDirectory() as temp_dir:
            items = read_input_excel(workbook, Path(temp_dir) / "inputs", default_top_n=5)

            self.assertEqual(len(items), 9)
            self.assertEqual(
                items[0].item_id,
                "1d3cbda4-3bdc-45e1-9dc7-b4cdab59e976",
            )
            self.assertEqual(items[0].keyword, "白底红格桌垫 餐桌布置")
            self.assertEqual(len(items[0].keyword_candidates), 10)
            self.assertEqual(
                items[0].keyword_candidates[1],
                "红格餐桌垫 买家秀 实拍",
            )
            self.assertTrue(items[0].reference_image.exists())
            self.assertEqual(
                items[0].reference_image.suffix,
                ".png",
            )

    def test_excel_reader_rejects_empty_file(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        with tempfile.TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "empty.xlsx"
            excel_path.write_bytes(b"")
            output_dir = Path(temp_dir) / "run" / "inputs"

            with self.assertRaisesRegex(ValueError, "invalid xlsx: file is empty"):
                read_input_excel(excel_path, output_dir, default_top_n=5)

    def test_excel_reader_requires_keyword(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        with tempfile.TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "items.xlsx"
            image_path = Path(temp_dir) / "ref.jpg"
            image_path.write_bytes(b"fake image")
            _write_xlsx(excel_path, [["image_path"], [str(image_path)]])

            with self.assertRaisesRegex(
                ValueError, "missing required column: keyword or keywords"
            ):
                read_input_excel(excel_path, Path(temp_dir) / "inputs", default_top_n=5)

    def test_excel_reader_uses_keywords_column_without_keyword(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [
                    ["image_path", "keywords"],
                    [
                        image_path.name,
                        "1. 白底红格桌垫 餐桌布置\n2、红格餐桌垫 买家秀 实拍",
                    ],
                ],
            )

            items = read_input_excel(excel_path, root / "run" / "inputs", default_top_n=5)

            self.assertEqual(items[0].keyword, "白底红格桌垫 餐桌布置")
            self.assertEqual(
                items[0].keyword_candidates,
                ["白底红格桌垫 餐桌布置", "红格餐桌垫 买家秀 实拍"],
            )
            self.assertEqual(items[0].item_id, "ref")

    def test_excel_reader_copies_reference_and_uses_row_top_n(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [
                    ["item_id", "keyword", "description", "image_path", "top_n", "enabled"],
                    ["sku-1", "红色连衣裙", "通勤", str(image_path), "3", "yes"],
                ],
            )

            items = read_input_excel(excel_path, root / "run" / "inputs", default_top_n=5)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].item_id, "sku-1")
            self.assertEqual(items[0].keyword, "红色连衣裙")
            self.assertEqual(items[0].keyword_candidates, ["红色连衣裙"])
            self.assertEqual(items[0].top_n, 3)
            self.assertTrue(items[0].reference_image.exists())
            self.assertEqual(items[0].reference_image.read_bytes(), b"fake image")

    def test_excel_reader_uses_embedded_image_anchor_row(self) -> None:
        from third_party.xhs_collector.xhs_collector.excel_reader import read_input_excel

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            excel_path = root / "items.xlsx"
            _write_xlsx_with_embedded_image(
                excel_path,
                [
                    ["item_id", "keyword", "enabled"],
                    ["skip-me", "跳过", "no"],
                    ["sku-embedded", "嵌入图", "yes"],
                ],
                image_row_number=3,
                image_payload=b"embedded image",
            )

            items = read_input_excel(excel_path, root / "run" / "inputs", default_top_n=5)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].item_id, "sku-embedded")
            self.assertEqual(items[0].reference_image.read_bytes(), b"embedded image")

    def test_config_defaults_and_validation(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig

        config = CollectorConfig.from_dict({})

        self.assertEqual(config.xhs_package, "com.xingin.xhs")
        self.assertEqual(config.top_n, 5)
        self.assertEqual(config.keyword_top_n, 3)
        self.assertEqual(config.download_mode, "in_app_save")
        self.assertEqual(config.output_root, Path("runs/xhs_collector"))
        self.assertEqual(config.target_category, "")
        self.assertEqual(config.target_category_keywords, [])

        with self.assertRaisesRegex(ValueError, "top_n must be >= 1"):
            CollectorConfig.from_dict({"top_n": 0})
        with self.assertRaisesRegex(ValueError, "keyword_top_n must be >= 0"):
            CollectorConfig.from_dict({"keyword_top_n": -1})

    def test_config_parses_target_category_keywords(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig

        config = CollectorConfig.from_dict(
            {
                "target_category": "桌垫",
                "target_category_keywords": "桌垫, 餐桌垫\n餐垫，桌垫桌布",
            }
        )

        self.assertEqual(config.target_category, "桌垫")
        self.assertEqual(
            config.target_category_keywords,
            ["桌垫", "餐桌垫", "餐垫", "桌垫桌布"],
        )

    def test_config_loads_deterministic_defaults(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig

        config = CollectorConfig.from_dict({})

        self.assertEqual(config.mode, "mobilerun")
        self.assertEqual(config.deterministic.match_threshold, 0.86)
        self.assertEqual(config.deterministic.app_start_wait_seconds, 6.0)
        self.assertEqual(config.deterministic.subject_recognition_wait_seconds, 5.0)
        self.assertEqual(config.deterministic.save_action, "long_press_then_save")
        self.assertEqual(
            config.deterministic.coordinate_profile,
            Path("config/xhs_coordinates.json"),
        )

        with self.assertRaisesRegex(
            ValueError, "subject_recognition_wait_seconds must be >= 0"
        ):
            CollectorConfig.from_dict(
                {"deterministic": {"subject_recognition_wait_seconds": -1}}
            )

    def test_coordinate_profile_validates_ratios_and_required_points(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        profile = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.2, 0.3],
                    "image_search_button": [0.3, 0.4],
                    "album_entry": [0.4, 0.5],
                    "first_album_image": [0.5, 0.6],
                    "album_confirm": [0.6, 0.7],
                    "results_anchor": [0.8, 0.9],
                }
            }
        )

        self.assertEqual(profile.point("search_box"), (0.2, 0.3))
        with self.assertRaisesRegex(ValueError, "ratio must be between 0 and 1"):
            CoordinateProfile.from_dict(
                {"points": {"search_box": [1.2, 0.3]}}
            )
        with self.assertRaisesRegex(ValueError, "missing coordinate point"):
            CoordinateProfile.from_dict({"points": {"search_box": [0.2, 0.3]}})

    def test_coordinate_profile_requires_download_points_for_result_download(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
            DOWNLOAD_POINTS,
        )

        profile = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.2, 0.3],
                    "image_search_button": [0.3, 0.4],
                    "album_entry": [0.4, 0.5],
                    "first_album_image": [0.5, 0.6],
                    "album_confirm": [0.6, 0.7],
                    "results_anchor": [0.8, 0.9],
                    "results_panel_swipe_start": [0.5, 0.82],
                    "results_panel_swipe_end": [0.5, 0.18],
                    "result_card_1": [0.25, 0.3],
                    "result_card_2": [0.75, 0.3],
                    "result_card_3": [0.25, 0.58],
                    "note_main_image": [0.5, 0.4],
                    "save_image_menu_item": [0.5, 0.82],
                    "note_back_button": [0.06, 0.07],
                }
            }
        )

        profile.require_points(DOWNLOAD_POINTS)
        incomplete = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.2, 0.3],
                    "image_search_button": [0.3, 0.4],
                    "album_entry": [0.4, 0.5],
                    "first_album_image": [0.5, 0.6],
                    "album_confirm": [0.6, 0.7],
                    "results_anchor": [0.8, 0.9],
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "missing coordinate point"):
            incomplete.require_points(DOWNLOAD_POINTS)

    def test_coordinate_profile_no_longer_requires_results_anchor(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        profile = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.2, 0.3],
                    "image_search_button": [0.3, 0.4],
                    "album_entry": [0.4, 0.5],
                    "first_album_image": [0.5, 0.6],
                    "album_confirm": [0.6, 0.7],
                }
            }
        )

        self.assertEqual(profile.point("album_confirm"), (0.6, 0.7))

    def test_click_ratio_converts_to_physical_coordinates(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            DeterministicDevice,
        )

        class FakeU2:
            def __init__(self) -> None:
                self.clicks: list[tuple[int, int]] = []

            def window_size(self) -> tuple[int, int]:
                return (1080, 2400)

            def click(self, x: int, y: int) -> None:
                self.clicks.append((x, y))

        fake = FakeU2()
        device = DeterministicDevice(fake)

        device.click_ratio(0.5, 0.25)

        self.assertEqual(fake.clicks, [(540, 600)])

    def test_click_ratio_falls_back_to_adb_tap_when_uiautomator_injection_is_denied(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector import deterministic_device
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            DeterministicDevice,
        )

        class FakeU2:
            def window_size(self) -> tuple[int, int]:
                return (1080, 2400)

            def click(self, x: int, y: int) -> None:
                raise RuntimeError(
                    "java.lang.SecurityException: Injecting input events requires INJECT_EVENTS permission"
                )

        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)

            class Result:
                stdout = ""

            return Result()

        with mock.patch.object(deterministic_device.subprocess, "run", fake_run):
            device = DeterministicDevice(FakeU2(), serial="phone-1")
            device.click_ratio(0.5, 0.25)

        self.assertEqual(calls[0], ["adb", "-s", "phone-1", "shell", "input tap 540 600"])

    def test_swipe_ratio_converts_to_physical_coordinates(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            DeterministicDevice,
        )

        class FakeU2:
            def __init__(self) -> None:
                self.swipes: list[tuple[int, int, int, int, float]] = []

            def window_size(self) -> tuple[int, int]:
                return (1080, 2400)

            def swipe(
                self, x1: int, y1: int, x2: int, y2: int, duration: float
            ) -> None:
                self.swipes.append((x1, y1, x2, y2, duration))

        fake = FakeU2()
        device = DeterministicDevice(fake)

        device.swipe_ratio(0.5, 0.82, 0.5, 0.18, duration=0.7)

        self.assertEqual(fake.swipes, [(540, 1968, 540, 432, 0.7)])

    def test_press_back_uses_system_back_key(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            DeterministicDevice,
        )

        class FakeU2:
            def __init__(self) -> None:
                self.presses: list[str] = []

            def press(self, key: str) -> None:
                self.presses.append(key)

        fake = FakeU2()
        device = DeterministicDevice(fake)

        device.press_back()

        self.assertEqual(fake.presses, ["back"])

    def test_calibration_finds_search_box_from_ui_hierarchy(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            find_point_ratio,
        )

        hierarchy = """
        <hierarchy>
          <node text="关注" bounds="[0,0][100,80]" />
          <node text="搜索" resource-id="com.xingin.xhs:id/search"
                bounds="[900,50][1120,150]" />
        </hierarchy>
        """

        self.assertEqual(
            find_point_ratio("search_box", hierarchy, (1200, 2670)),
            (0.8417, 0.0375),
        )

    def test_calibration_finds_image_search_button_from_ui_hierarchy(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            find_point_ratio,
        )

        hierarchy = """
        <hierarchy>
          <node text="搜索" bounds="[30,50][820,150]" />
          <node content-desc="图片搜索" bounds="[1010,54][1120,154]" />
        </hierarchy>
        """

        self.assertEqual(
            find_point_ratio("image_search_button", hierarchy, (1200, 2670)),
            (0.8875, 0.039),
        )

    def test_calibration_finds_album_and_confirm_points_from_ui_hierarchy(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            find_point_ratio,
        )

        hierarchy = """
        <hierarchy>
          <node text="从相册选择" bounds="[200,2200][1000,2350]" />
          <node text="完成" bounds="[980,2520][1170,2650]" />
        </hierarchy>
        """

        self.assertEqual(
            find_point_ratio("album_entry", hierarchy, (1200, 2670)),
            (0.5, 0.8521),
        )
        self.assertEqual(
            find_point_ratio("album_confirm", hierarchy, (1200, 2670)),
            (0.8958, 0.9682),
        )

    def test_calibration_updates_coordinate_profile_and_clicks_search_box(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            calibrate_search_box,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return '<node text="搜索" bounds="[900,50][1120,150]" />'

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)

            result = calibrate_search_box(
                device=FakeDevice(),
                profile_path=profile_path,
                output_dir=root / "calibration",
                xhs_package="com.xingin.xhs",
                click=True,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"]["search_box"], [0.8417, 0.0375])
            self.assertEqual(result["source"], "ui_hierarchy")
            self.assertEqual(result["search_box"], [0.8417, 0.0375])

    def test_calibration_updates_any_supported_point_from_pixels(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_point
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.started = False

            def start_app(self, package: str) -> None:
                self.started = True

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return "<hierarchy />"

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_point(
                point_name="image_search_button",
                device=device,
                profile_path=profile_path,
                output_dir=root / "calibration",
                xhs_package="com.xingin.xhs",
                pixel_x=1090,
                pixel_y=135,
                click=True,
                start_app=False,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertFalse(device.started)
            self.assertEqual(payload["points"]["image_search_button"], [0.9083, 0.0506])
            self.assertEqual(result["point"], "image_search_button")
            self.assertEqual(result["source"], "pixel")
            self.assertEqual(device.clicked, [(0.9083, 0.0506)])

    def test_calibration_rejects_unknown_point(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_point

        class FakeDevice:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsupported calibration point"):
                calibrate_point(
                    point_name="not_a_point",
                    device=FakeDevice(),
                    profile_path=Path(temp_dir) / "coords.json",
                    output_dir=Path(temp_dir) / "calibration",
                    xhs_package="com.xingin.xhs",
                )

    def test_grid_image_falls_back_when_screenshot_is_not_decodable(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            _write_grid_image,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.png"
            target_path = root / "target.png"
            source_path.write_bytes(b"not-a-real-image")

            _write_grid_image(source_path, target_path)

            self.assertEqual(target_path.read_bytes(), b"not-a-real-image")

    def test_search_box_suggestion_prefers_visual_home_search_icon(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "search_box",
            "source": "ui_hierarchy",
            "search_box": [0.8417, 0.0375],
            "grid": "search_box_grid.png",
        }

        suggestion = build_point_suggestion("search_box", preview, (1200, 2670))

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "visual_hint")
        self.assertEqual(suggestion["hint"], "home_top_right_search_icon")
        self.assertEqual(suggestion["pixel"], [1119, 200])
        self.assertEqual(suggestion["search_box"], [0.9325, 0.0749])
        self.assertEqual(suggestion["secondary"]["source"], "ui_hierarchy")

    def test_non_visual_point_suggestion_uses_ui_candidate(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "results_anchor",
            "source": "ui_hierarchy",
            "results_anchor": [0.9, 0.05],
            "grid": "results_anchor_grid.png",
        }

        suggestion = build_point_suggestion(
            "results_anchor", preview, (1200, 2670)
        )

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "ui_hierarchy")
        self.assertEqual(suggestion["pixel"], [1080, 134])
        self.assertEqual(suggestion["results_anchor"], [0.9, 0.05])

    def test_image_search_button_suggestion_prefers_visual_camera_icon(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "image_search_button",
            "source": "ui_hierarchy",
            "image_search_button": [0.2533, 0.2438],
            "grid": "image_search_button_grid.png",
        }

        suggestion = build_point_suggestion(
            "image_search_button", preview, (1200, 2670)
        )

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "visual_hint")
        self.assertEqual(suggestion["hint"], "search_page_camera_icon")
        self.assertEqual(suggestion["pixel"], [922, 212])
        self.assertEqual(suggestion["image_search_button"], [0.7683, 0.0794])
        self.assertEqual(suggestion["secondary"]["source"], "ui_hierarchy")

    def test_album_entry_suggestion_prefers_expand_button(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "album_entry",
            "source": "ui_hierarchy",
            "album_entry": [0.11, 0.847],
            "grid": "album_entry_grid.png",
        }

        suggestion = build_point_suggestion("album_entry", preview, (1200, 2670))

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "visual_hint")
        self.assertEqual(suggestion["hint"], "xhs_camera_page_album_expand")
        self.assertEqual(suggestion["pixel"], [1110, 2261])
        self.assertEqual(suggestion["album_entry"], [0.925, 0.8468])
        self.assertEqual(suggestion["secondary"]["source"], "ui_hierarchy")

    def test_first_album_image_suggestion_prefers_expanded_grid_first_tile(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "needs_manual_point",
            "point": "first_album_image",
            "grid": "first_album_image_grid.png",
        }

        suggestion = build_point_suggestion(
            "first_album_image", preview, (1200, 2670)
        )

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "visual_hint")
        self.assertEqual(suggestion["hint"], "expanded_album_grid_first_tile")
        self.assertEqual(suggestion["pixel"], [150, 520])
        self.assertEqual(suggestion["first_album_image"], [0.125, 0.1948])

    def test_album_confirm_suggestion_prefers_bottom_right_confirm(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "album_confirm",
            "source": "ui_hierarchy",
            "album_confirm": [0.8958, 0.9682],
            "grid": "album_confirm_grid.png",
        }

        suggestion = build_point_suggestion("album_confirm", preview, (1200, 2670))

        self.assertEqual(suggestion["status"], "ok")
        self.assertEqual(suggestion["source"], "visual_hint")
        self.assertEqual(suggestion["hint"], "album_picker_bottom_right_confirm")
        self.assertEqual(suggestion["pixel"], [1056, 2577])
        self.assertEqual(suggestion["album_confirm"], [0.88, 0.965])
        self.assertEqual(suggestion["secondary"]["source"], "ui_hierarchy")

    def test_result_download_point_suggestions_use_visual_defaults(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            build_point_suggestion,
        )

        for point_name, expected_pixel, expected_ratio in [
            ("results_panel_swipe_start", [600, 2189], [0.5, 0.82]),
            ("results_panel_swipe_end", [600, 481], [0.5, 0.18]),
            ("result_card_1", [300, 801], [0.25, 0.3]),
            ("result_card_2", [900, 801], [0.75, 0.3]),
            ("result_card_3", [300, 1549], [0.25, 0.58]),
            ("note_main_image", [600, 1068], [0.5, 0.4]),
            ("save_image_menu_item", [600, 2189], [0.5, 0.82]),
            ("note_back_button", [72, 187], [0.06, 0.07]),
        ]:
            with self.subTest(point_name=point_name):
                suggestion = build_point_suggestion(
                    point_name,
                    {
                        "status": "needs_manual_point",
                        "point": point_name,
                        "grid": f"{point_name}_grid.png",
                    },
                    (1200, 2670),
                )
                self.assertEqual(suggestion["status"], "ok")
                self.assertEqual(suggestion["source"], "visual_hint")
                self.assertEqual(suggestion["pixel"], expected_pixel)
                self.assertEqual(suggestion[point_name], expected_ratio)

    def test_flow_prompt_shows_visual_recommendation_and_secondary_candidate(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            _format_flow_prompt,
            build_point_suggestion,
        )

        preview = {
            "status": "ok",
            "point": "search_box",
            "source": "ui_hierarchy",
            "search_box": [0.8417, 0.0375],
            "grid": "calibration/flow/search_box/search_box_grid.png",
        }
        suggestion = build_point_suggestion("search_box", preview, (1200, 2670))

        prompt = _format_flow_prompt("search_box", suggestion)

        self.assertIn("Recommended: 1119,200", prompt)
        self.assertIn("visual_hint home_top_right_search_icon", prompt)
        self.assertIn("Secondary UI candidate: 1010,100", prompt)
        self.assertIn("search_box_grid.png", prompt)
        self.assertIn("Press Enter to accept recommended", prompt)

    def test_calibration_flow_accepts_auto_candidate_and_manual_override(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.started = 0
                self.current_point = ""
                self.search_opened = False

            def start_app(self, package: str) -> None:
                self.started += 1

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.search_opened and self.current_point == "search_box":
                    return "取消 搜索历史"
                if self.current_point == "image_search_button":
                    return "相册 最近项目"
                if self.current_point == "search_box":
                    return '<node text="搜索" bounds="[900,50][1120,150]" />'
                return "<hierarchy />"

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.9325, 0.0749):
                    self.search_opened = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()
            answers = iter(["", "1090,135"])

            def input_func(prompt: str) -> str:
                return next(answers)

            def before_point(point_name: str) -> None:
                device.current_point = point_name

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["search_box", "image_search_button"],
                input_func=input_func,
                output_func=lambda message: None,
                before_point=before_point,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(device.started, 1)
            self.assertEqual(payload["points"]["search_box"], [0.9325, 0.0749])
            self.assertEqual(payload["points"]["image_search_button"], [0.9083, 0.0506])
            self.assertEqual(device.clicked, [(0.9325, 0.0749), (0.9083, 0.0506)])

    def test_search_box_verification_accepts_search_page_input_markers(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import (
            _point_verification_passed,
        )

        self.assertTrue(
            _point_verification_passed(
                "search_box",
                '<node text="" resource-id="com.xingin.xhs:id/search_edit_text" />',
            )
        )
        self.assertTrue(
            _point_verification_passed(
                "search_box",
                '<node class="android.widget.EditText" text="搜索小红书" />',
            )
        )

    def test_calibration_flow_manual_override_beats_visual_recommendation(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.search_opened = False

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.search_opened:
                    return "取消 搜索历史"
                return '<node text="搜索" bounds="[900,50][1120,150]" />'

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.5, 0.0599):
                    self.search_opened = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["search_box"],
                input_func=lambda prompt: "600,160",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(payload["points"]["search_box"], [0.5, 0.0599])
            self.assertEqual(device.clicked, [(0.5, 0.0599)])

    def test_calibration_flow_retries_search_box_visual_fallback(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.ui_text = "首页 发现"

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.9, 0.0749):
                    self.ui_text = "取消 搜索历史"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)

            result = calibrate_flow(
                device=FakeDevice(),
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["search_box"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(payload["points"]["search_box"], [0.9, 0.0749])
            self.assertEqual(
                result["completed"][0]["source"],
                "visual_hint_fallback",
            )

    def test_calibration_flow_accepts_image_search_visual_recommendation(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.ui_text = "搜索页"

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.7683, 0.0794):
                    self.ui_text = "相册 最近项目"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)

            result = calibrate_flow(
                device=FakeDevice(),
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["image_search_button"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(payload["points"]["image_search_button"], [0.7683, 0.0794])
            self.assertEqual(result["completed"][0]["verified"], True)

    def test_calibration_flow_stops_when_image_search_does_not_open_album(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return "搜索页"

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["image_search_button", "album_entry"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            self.assertEqual(result["status"], "verification_failed")
            self.assertEqual(result["point"], "image_search_button")
            self.assertGreater(len(device.clicked), 1)
            self.assertTrue(
                (
                    root
                    / "flow"
                    / "image_search_button"
                    / "image_search_button_after_click.xml"
                ).exists()
            )

    def test_calibration_flow_accepts_album_entry_expand_recommendation(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.ui_text = "图搜相机页 我的相册 展开"

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.925, 0.8468):
                    self.ui_text = "最近项目 相册 照片"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.7683, 0.0794],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)

            result = calibrate_flow(
                device=FakeDevice(),
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["album_entry"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(payload["points"]["album_entry"], [0.925, 0.8468])
            self.assertEqual(result["completed"][0]["verified"], True)

    def test_calibration_flow_accepts_album_image_and_confirm_recommendations(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []
                self.ui_text = "最近项目 相册 照片 GridView"

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.125, 0.1948):
                    self.ui_text = "最近项目 相册 照片 已选择 1 完成"
                if (x, y) == (0.88, 0.965):
                    self.ui_text = "图搜结果 相似笔记"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.7683, 0.0794],
                        "album_entry": [0.925, 0.8468],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)

            result = calibrate_flow(
                device=FakeDevice(),
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["first_album_image", "album_confirm"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                payload["points"]["first_album_image"], [0.125, 0.1948]
            )
            self.assertEqual(payload["points"]["album_confirm"], [0.88, 0.965])
            self.assertEqual(
                result["completed"][0]["hint"],
                "expanded_album_grid_first_tile",
            )
            self.assertEqual(
                result["completed"][1]["hint"],
                "album_picker_bottom_right_confirm",
            )

    def test_calibration_flow_stops_when_album_entry_does_not_expand(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return "图搜相机页 我的相册 展开"

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.7683, 0.0794],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["album_entry", "first_album_image"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            self.assertEqual(result["status"], "verification_failed")
            self.assertEqual(result["point"], "album_entry")
            self.assertGreater(len(device.clicked), 1)
            self.assertTrue(
                (root / "flow" / "album_entry" / "album_entry_after_click.xml").exists()
            )

    def test_calibration_flow_stops_when_search_box_never_reaches_search_page(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.clicked: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return "首页 发现"

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["search_box", "image_search_button"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
            )

            self.assertEqual(result["status"], "verification_failed")
            self.assertEqual(result["point"], "search_box")
            self.assertGreater(len(device.clicked), 1)
            self.assertEqual(result["completed"], [])
            self.assertTrue((root / "flow" / "search_box" / "search_box_after_click.xml").exists())

    def test_calibration_flow_waits_after_start_and_each_click_before_next_screenshot(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self, events: list[str]) -> None:
                self.events = events
                self.search_opened = False
                self.album_opened = False

            def start_app(self, package: str) -> None:
                self.events.append("start_app")

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.album_opened:
                    return "相册 最近项目"
                if self.search_opened:
                    return "取消 搜索历史"
                return "<hierarchy />"

            def screenshot(self) -> bytes:
                self.events.append("screenshot")
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.events.append(f"click:{x},{y}")
                if (x, y) == (0.1, 0.1):
                    self.search_opened = True
                if (x, y) == (0.2, 0.2):
                    self.album_opened = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            events: list[str] = []
            iter_answers = iter(["120,267", "240,534"])

            def sleep_func(seconds: float) -> None:
                events.append(f"sleep:{seconds}")

            result = calibrate_flow(
                device=FakeDevice(events),
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["search_box", "image_search_button"],
                input_func=lambda prompt: next(iter_answers),
                output_func=lambda message: None,
                wait_seconds=2.5,
                sleep_func=sleep_func,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                events,
                [
                    "start_app",
                    "sleep:2.5",
                    "screenshot",
                    "screenshot",
                    "click:0.1,0.1",
                    "sleep:2.5",
                    "screenshot",
                    "screenshot",
                    "click:0.2,0.2",
                    "sleep:2.5",
                ],
            )

    def test_calibration_flow_can_continue_from_current_page_without_starting_app(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_flow
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.started = 0
                self.clicked: list[tuple[float, float]] = []
                self.ui_text = "图搜相机页 我的相册 展开"

            def start_app(self, package: str) -> None:
                self.started += 1

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def screenshot(self) -> bytes:
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.clicked.append((x, y))
                if (x, y) == (0.925, 0.8468):
                    self.ui_text = "最近项目 相册 照片"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.9325, 0.0749],
                        "image_search_button": [0.7683, 0.0794],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.125, 0.1948],
                        "album_confirm": [0.88, 0.965],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            device = FakeDevice()

            result = calibrate_flow(
                device=device,
                profile_path=profile_path,
                output_dir=root / "flow",
                xhs_package="com.xingin.xhs",
                points=["album_entry"],
                input_func=lambda prompt: "",
                output_func=lambda message: None,
                wait_seconds=0,
                start_app=False,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(device.started, 0)
            self.assertEqual(device.clicked, [(0.925, 0.8468)])

    def test_calibrate_point_waits_after_start_app_before_screenshot(self) -> None:
        from third_party.xhs_collector.xhs_collector.calibration import calibrate_point
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )

        class FakeDevice:
            def __init__(self, events: list[str]) -> None:
                self.events = events

            def start_app(self, package: str) -> None:
                self.events.append("start_app")

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return '<node text="搜索" bounds="[900,50][1120,150]" />'

            def screenshot(self) -> bytes:
                self.events.append("screenshot")
                return b"png"

            def click_ratio(self, x: float, y: float) -> None:
                self.events.append(f"click:{x},{y}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.6, 0.6],
                    }
                }
            ).write(profile_path)
            events: list[str] = []

            calibrate_point(
                point_name="search_box",
                device=FakeDevice(events),
                profile_path=profile_path,
                output_dir=root / "calibration",
                xhs_package="com.xingin.xhs",
                start_app=True,
                wait_seconds=3.0,
                sleep_func=lambda seconds: events.append(f"sleep:{seconds}"),
            )

            self.assertEqual(
                events[:3],
                ["start_app", "sleep:3.0", "screenshot"],
            )

    def test_screenshot_uses_uiautomator2_default_format_when_raw_is_unsupported(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            DeterministicDevice,
        )

        class FakeImage:
            def save(self, handle, format: str) -> None:
                handle.write(f"image/{format}".encode("utf-8"))

        class FakeU2:
            def screenshot(self, *args, **kwargs):
                if kwargs:
                    raise RuntimeError(("Unsupported format:", kwargs.get("format")))
                return FakeImage()

        device = DeterministicDevice(FakeU2())

        self.assertEqual(device.screenshot(), b"image/PNG")

    def test_template_matcher_threshold_and_sorting(self) -> None:
        from third_party.xhs_collector.xhs_collector.template_matcher import (
            TemplateMatch,
            TemplateMatcher,
        )

        matcher = TemplateMatcher(match_threshold=0.86)
        matches = matcher.filter_matches(
            [
                TemplateMatch("save", 0.8, 1, 1, 20, 20),
                TemplateMatch("album", 0.96, 5, 6, 20, 20),
                TemplateMatch("save", 0.9, 3, 4, 20, 20),
            ]
        )

        self.assertEqual([match.name for match in matches], ["album", "save"])
        self.assertEqual(matches[0].center, (15, 16))

    def test_risk_text_detection_stops_on_login_captcha_or_permission(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            detect_risk_text,
        )

        self.assertEqual(detect_risk_text("请先登录后继续"), "login_required")
        self.assertEqual(detect_risk_text("请输入验证码"), "captcha_required")
        self.assertEqual(detect_risk_text("账号存在风险"), "risk_control")
        self.assertEqual(detect_risk_text("允许访问照片和视频吗"), "permission_prompt")
        self.assertIsNone(detect_risk_text("桌垫 买家秀 实拍"))

    def test_media_store_diff_is_stable(self) -> None:
        from third_party.xhs_collector.xhs_collector.media_store import diff_new_media

        before = ["/sdcard/DCIM/a.jpg", "/sdcard/DCIM/b.jpg"]
        after = [
            "/sdcard/DCIM/new-2.jpg",
            "/sdcard/DCIM/a.jpg",
            "/sdcard/DCIM/new-1.jpg",
            "/sdcard/DCIM/b.jpg",
        ]

        self.assertEqual(
            diff_new_media(before, after),
            ["/sdcard/DCIM/new-1.jpg", "/sdcard/DCIM/new-2.jpg"],
        )

    def test_wait_for_new_media_refreshes_store_before_final_failure(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _wait_for_new_media,
        )

        class FakeMediaStore:
            def __init__(self) -> None:
                self.refreshed = False

            def snapshot(self) -> list[str]:
                if self.refreshed:
                    return ["/sdcard/DCIM/late-save.jpg"]
                return []

            def refresh(self) -> None:
                self.refreshed = True

        media_store = FakeMediaStore()

        self.assertEqual(
            _wait_for_new_media(
                media_store=media_store,
                before=[],
                timeout_seconds=0,
                sleep_func=lambda seconds: None,
            ),
            "/sdcard/DCIM/late-save.jpg",
        )
        self.assertTrue(media_store.refreshed)

    def test_prompt_builder_contains_safety_boundaries(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import InputItem
        from third_party.xhs_collector.xhs_collector.xhs_flow import (
            build_xhs_prompt,
            build_xhs_rank_prompt,
        )

        item = InputItem(
            item_id="sku-1",
            keyword="红色连衣裙",
            keyword_candidates=["红色连衣裙", "买家秀 实拍"],
            description="通勤",
            reference_image=Path("reference.jpg"),
            top_n=2,
        )

        prompt = build_xhs_prompt(item, "/sdcard/Pictures/xhs_collector/reference.jpg")

        self.assertIn("手动登录", prompt)
        self.assertIn("验证码", prompt)
        self.assertIn("不要绕过", prompt)
        self.assertIn("TOP 2", prompt)
        self.assertIn("红色连衣裙", prompt)
        self.assertIn("买家秀 实拍", prompt)
        self.assertIn("白底图", prompt)
        self.assertIn("渲染图", prompt)

        rank_prompt = build_xhs_rank_prompt(
            item, "/sdcard/Pictures/xhs_collector/reference.jpg", rank=2, already_saved=1
        )
        self.assertIn("验证码", rank_prompt)
        self.assertIn("不要绕过", rank_prompt)
        self.assertIn("第 2 张", rank_prompt)
        self.assertIn("此前已保存 1 张", rank_prompt)
        self.assertIn("买家秀 实拍", rank_prompt)
        self.assertIn("商拍", rank_prompt)

    def test_dry_run_writes_manifest_ranked_items_and_risk_events(self) -> None:
        from third_party.xhs_collector.xhs_collector.runner import run_dry_collect

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_a = root / "a.jpg"
            image_b = root / "b.jpg"
            image_a.write_bytes(b"a")
            image_b.write_bytes(b"b")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [
                    ["item_id", "keyword", "image_path", "top_n"],
                    ["sku-a", "白色包包", str(image_a), "3"],
                    ["sku-b", "黑色鞋子", str(image_b), "3"],
                ],
            )
            config_path = root / "config.json"
            output_root = root / "runs"
            config_path.write_text(
                json.dumps({"output_root": str(output_root), "top_n": 3}),
                encoding="utf-8",
            )

            manifest = run_dry_collect(excel_path, config_path)

            self.assertEqual(len(manifest.results), 2)
            manifest_path = output_root / manifest.run_id / "manifest.json"
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["results"][0]["collected_count"], 3)
            self.assertEqual(payload["results"][0]["keyword_candidates"], ["白色包包"])
            rank_path = output_root / manifest.run_id / "items" / "sku-a" / "rank_001.jpg"
            self.assertTrue(rank_path.exists())
            metadata_path = output_root / manifest.run_id / "items" / "sku-a" / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["keyword_candidates"], ["白色包包"])
            risk_log = output_root / manifest.run_id / "risk_events.jsonl"
            self.assertEqual(risk_log.read_text(encoding="utf-8").strip(), "")

    def test_deterministic_flow_fake_device_reaches_image_search_results(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "桌垫 买家秀 实拍"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(self, local_path: Path, item_id: str, remote_dir: str) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中 试试单击图片任意位置搜索"
                elif (x, y) == (0.8, 0.8):
                    self.ui_text = "图搜结果 桌垫 买家秀 实拍"

            def screenshot(self) -> bytes:
                return b"png"

            def save_debug_artifacts(self, output_dir: Path, step_name: str) -> None:
                (output_dir / "screenshots").mkdir(parents=True, exist_ok=True)
                (output_dir / "screenshots" / f"{step_name}.xml").write_text(
                    self.ui_text,
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=3,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.message, "image search results reached")
            self.assertEqual(result.collected_count, 0)
            self.assertEqual(
                device.actions,
                [
                    ("start_app", "com.xingin.xhs"),
                    ("push", "sku"),
                    ("click", (0.1, 0.1)),
                    ("click", (0.2, 0.2)),
                    ("click", (0.3, 0.3)),
                    ("click", (0.4, 0.4)),
                ],
            )
            self.assertTrue((root / "step_events.jsonl").exists())

    def test_deterministic_flow_waits_after_start_before_search_box(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        actions: list[tuple[str, object]] = []

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )

            run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=2.5,
                save_poll_seconds=0,
                sleep_func=lambda seconds: actions.append(("sleep", seconds)),
            )

            self.assertEqual(
                actions[:4],
                [
                    ("start_app", "com.xingin.xhs"),
                    ("sleep", 2.5),
                    ("push", "sku"),
                    ("click", (0.1, 0.1)),
                ],
            )

    def test_deterministic_flow_uses_dedicated_app_start_wait_before_search_box(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        actions: list[tuple[str, object]] = []

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )

            run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=2.0,
                app_start_wait_seconds=6.0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: actions.append(("sleep", seconds)),
            )

            self.assertEqual(
                actions[:4],
                [
                    ("start_app", "com.xingin.xhs"),
                    ("sleep", 6.0),
                    ("push", "sku"),
                    ("click", (0.1, 0.1)),
                ],
            )

    def test_deterministic_flow_retries_search_box_until_search_page_is_reached(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"
                self.search_taps = 0
                self.back_count = 0

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.search_taps += 1
                    self.ui_text = (
                        "首页 发现"
                        if self.search_taps == 1
                        else "取消 搜索历史 搜索小红书"
                    )
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.back_count += 1
                self.ui_text = "首页 发现"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(device.back_count, 1)
            self.assertEqual(
                device.actions,
                [
                    ("start_app", "com.xingin.xhs"),
                    ("push", "sku"),
                    ("click", (0.1, 0.1)),
                    ("press_back", None),
                    ("click", (0.1, 0.1)),
                    ("click", (0.2, 0.2)),
                    ("click", (0.3, 0.3)),
                    ("click", (0.4, 0.4)),
                ],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("wait_search_page_after_search_box", events)
            self.assertIn("search_box_click_not_on_search_page", events)
            self.assertIn("back_after_search_box_miss", events)

    def test_deterministic_flow_stops_when_search_page_never_opens(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.2, 0.2):
                    raise AssertionError("image search should not be clicked before search page")

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "首页 发现"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "search_page_not_reached_after_retries")
            self.assertEqual(
                result.risk_events,
                [{"event": "search_page_not_reached_after_retries", "item_id": "sku"}],
            )
            self.assertEqual(
                [action for action in result.risk_events],
                [{"event": "search_page_not_reached_after_retries", "item_id": "sku"}],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertEqual(events.count("search_box_click_not_on_search_page"), 3)
            self.assertIn("search_page_not_reached_after_retries", events)

    def test_deterministic_flow_restarts_app_when_search_retry_has_no_back_key(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"
                self.search_taps = 0

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.search_taps += 1
                    self.ui_text = (
                        "首页 发现"
                        if self.search_taps == 1
                        else "取消 搜索历史 搜索小红书"
                    )
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(
                [action for action in device.actions if action[0] == "start_app"],
                [("start_app", "com.xingin.xhs"), ("start_app", "com.xingin.xhs")],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"back_source": "start_app"', events)

    def test_deterministic_flow_retries_image_search_button_when_it_hits_suggestions(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"
                self.image_search_taps = 0

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.image_search_taps += 1
                    self.ui_text = (
                        "取消 搜索历史 照片 推荐词 综合 用户 商品"
                        if self.image_search_taps == 1
                        else "图搜 相册 最近项目"
                    )
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "取消 搜索历史 搜索小红书"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(
                device.actions,
                [
                    ("start_app", "com.xingin.xhs"),
                    ("push", "sku"),
                    ("click", (0.1, 0.1)),
                    ("click", (0.2, 0.2)),
                    ("press_back", None),
                    ("click", (0.2, 0.2)),
                    ("click", (0.3, 0.3)),
                    ("click", (0.4, 0.4)),
                ],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("wait_album_page_after_image_search_button", events)
            self.assertIn("image_search_button_click_not_on_album_page", events)
            self.assertIn("back_after_image_search_button_miss", events)
            self.assertLess(events.index("wait_album_page_after_image_search_button"), events.index("tap_album_entry"))

    def test_deterministic_flow_cancels_before_image_search_button(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeCancelToken:
            def __init__(self) -> None:
                self.calls = 0

            def is_cancel_requested(self) -> bool:
                self.calls += 1
                return self.calls >= 4

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    raise AssertionError("image search should not be clicked after cancel")

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                cancel_token=FakeCancelToken(),
            )

            self.assertEqual(result.status, "canceled")
            self.assertEqual(result.message, "canceled")
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("collection_canceled", events)

    def test_deterministic_flow_reuses_xhs_home_without_restarting_app(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现 推荐"

            def current_package(self) -> str:
                return "com.xingin.xhs"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertNotIn(("start_app", "com.xingin.xhs"), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("xhs_home_ready", events)

    def test_deterministic_flow_recovers_non_home_xhs_before_search(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "评论 点赞 收藏"

            def current_package(self) -> str:
                return "com.xingin.xhs"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现 推荐"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "首页 发现 推荐"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn(("press_back", None), device.actions)
            self.assertLess(
                device.actions.index(("press_back", None)),
                device.actions.index(("click", (0.1, 0.1))),
            )

    def test_deterministic_flow_recovers_search_residue_before_new_run(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "取消 搜索历史 推荐 搜索小红书"

            def current_package(self) -> str:
                return "com.xingin.xhs"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现 推荐"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "首页 发现 推荐"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertLess(
                device.actions.index(("press_back", None)),
                device.actions.index(("push", "sku")),
            )
            self.assertLess(
                device.actions.index(("press_back", None)),
                device.actions.index(("click", (0.1, 0.1))),
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertLess(
                events.index("recover_xhs_home_before_search"),
                events.index("push_reference"),
            )

    def test_xhs_home_page_detection_rejects_search_residue(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _is_xhs_home_page,
        )

        self.assertFalse(_is_xhs_home_page("取消 搜索历史 推荐 搜索小红书"))
        self.assertFalse(_is_xhs_home_page("推荐"))
        self.assertTrue(_is_xhs_home_page("首页 发现 推荐"))

    def test_deterministic_flow_stops_when_image_search_button_never_opens_album(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页 发现"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))
                self.ui_text = "首页 发现"

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "取消 搜索历史 照片 推荐词 综合 用户 商品"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "取消 搜索历史 搜索小红书"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "image_search_album_not_reached_after_retries")
            self.assertEqual(
                result.risk_events,
                [{"event": "image_search_album_not_reached_after_retries", "item_id": "sku"}],
            )
            self.assertNotIn(("click", (0.3, 0.3)), device.actions)
            self.assertEqual(device.actions.count(("click", (0.2, 0.2))), 3)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertEqual(events.count("image_search_button_click_not_on_album_page"), 3)
            self.assertIn("image_search_album_not_reached_after_retries", events)

    def test_search_box_recovery_records_home_page_marker(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _recover_home_after_search_box_miss,
        )

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "搜索页之外"

            def press_back(self) -> None:
                self.actions.append(("press_back", None))
                self.ui_text = "首页 发现"

            def dump_hierarchy(self) -> str:
                return self.ui_text

        device = FakeDevice()

        event = _recover_home_after_search_box_miss(
            device=device,
            xhs_package="com.xingin.xhs",
            timeout_seconds=1,
            sleep_func=lambda seconds: None,
            item_id="sku",
        )

        self.assertEqual(device.actions, [("press_back", None)])
        self.assertEqual(event["back_source"], "press_back")
        self.assertTrue(event["home_reached"])

    def test_deterministic_flow_skips_album_confirm_when_image_opens_analysis(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中 试试单击图片任意位置搜索"
                elif (x, y) == (0.8, 0.8):
                    self.ui_text = "图搜结果 桌垫 买家秀 实拍"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertNotIn(("click", (0.5, 0.5)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("tap_first_album_image", events)
            self.assertNotIn("tap_album_confirm", events)

    def test_deterministic_flow_stops_before_selecting_image_when_album_grid_not_ready(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "相册加载中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "album_grid_not_ready")
            self.assertEqual(
                result.risk_events,
                [{"event": "album_grid_not_ready", "item_id": "sku"}],
            )
            self.assertNotIn(("click", (0.4, 0.4)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("album_grid_not_ready", events)

    def test_deterministic_flow_clicks_album_confirm_only_when_confirm_is_visible(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "完成"
                elif (x, y) == (0.5, 0.5):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.8, 0.8):
                    self.ui_text = "图搜结果"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn(("click", (0.5, 0.5)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("tap_album_confirm", events)

    def test_deterministic_flow_stops_when_album_image_is_not_selected(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "全部照片 收起 RecyclerView"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "album_thumbnail_candidates_exhausted")
            self.assertEqual(
                result.risk_events,
                [{"event": "album_thumbnail_candidates_exhausted", "item_id": "sku"}],
            )
            self.assertNotIn(("click", (0.5, 0.5)), device.actions)
            self.assertNotIn(("click", (0.8, 0.8)), device.actions)

    def test_deterministic_flow_does_not_treat_system_status_text_as_album_confirm(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        album_grid_with_system_status = """
        <hierarchy>
          <node text="全部照片" package="com.xingin.xhs" bounds="[48,140][216,261]" />
          <node text="收起" package="com.xingin.xhs" bounds="[1068,140][1152,261]" />
          <node text="" package="com.android.systemui"
            content-desc="小红书正在使用（相机）" bounds="[1043,24][1124,112]" />
          <node text="" package="com.android.systemui"
            content-desc="正在充电，已完成百分之 100。" bounds="[1021,50][1066,86]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = album_grid_with_system_status
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = album_grid_with_system_status

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "album_thumbnail_candidates_exhausted")
            self.assertNotIn(("click", (0.5, 0.5)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("album_thumbnail_candidates_exhausted", events)
            self.assertNotIn("album_confirm_failed", events)

    def test_deterministic_flow_waits_past_transient_album_grid_after_image_tap(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"
                self.after_image_tap = False
                self.dumps_after_image_tap = 0

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                if self.after_image_tap:
                    self.dumps_after_image_tap += 1
                    if self.dumps_after_image_tap == 1:
                        return "全部照片 收起 RecyclerView"
                    return "图片分析中"
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.after_image_tap = True
                elif (x, y) == (0.8, 0.8):
                    self.ui_text = "图搜结果"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=1,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertGreaterEqual(device.dumps_after_image_tap, 2)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("wait_image_search_results", events)
            self.assertNotIn("album_image_not_selected", events)

    def test_album_thumbnail_candidates_filter_controls_and_sort_grid(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _find_album_thumbnail_target,
        )

        hierarchy = """
        <hierarchy>
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" bounds="[15,134][147,266]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" bounds="[1053,134][1185,266]" />
          <node class="android.widget.FrameLayout" package="com.xingin.xhs"
            clickable="true" bounds="[488,1790][713,2015]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" bounds="[301,775][596,1070]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" bounds="[0,775][295,1070]" />
          <node class="android.widget.ImageView" package="com.android.systemui"
            clickable="true" bounds="[0,775][295,1070]" />
        </hierarchy>
        """

        target = _find_album_thumbnail_target(hierarchy, (1200, 2670))

        self.assertIsNotNone(target)
        self.assertEqual(target["bounds"], [0, 775, 295, 1070])
        self.assertEqual(target["click_point"], [148, 922])
        self.assertEqual(target["point"], [0.1233, 0.3453])

    def test_deterministic_flow_clicks_album_thumbnail_from_ui_hierarchy_bounds(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        album_grid = """
        <hierarchy>
          <node text="全部照片" package="com.xingin.xhs" bounds="[48,649][216,770]" />
          <node text="收起" package="com.xingin.xhs" bounds="[1068,649][1152,770]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[15,134][147,266]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[0,775][295,1070]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[301,775][596,1070]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = album_grid
                elif round(x, 4) == 0.1233 and round(y, 4) == 0.3453:
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = album_grid

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn(("click", (0.1233, 0.3453)), device.actions)
            self.assertNotIn(("click", (0.4, 0.4)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"click_source": "ui_hierarchy"', events)
            self.assertIn('"album_image_bounds": [0, 775, 295, 1070]', events)

    def test_subject_recognition_wait_runs_before_results_panel_swipe(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        album_grid = """
        <hierarchy>
          <node text="全部照片" package="com.xingin.xhs" bounds="[48,649][216,770]" />
          <node text="收起" package="com.xingin.xhs" bounds="[1068,649][1152,770]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[0,775][295,1070]" />
        </hierarchy>
        """
        image_analysis = "图片分析中 输入关于图片的问题 图搜 result"

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "首页"
                self.actions: list[tuple[str, object]] = []

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = album_grid
                elif round(x, 4) == 0.1233 and round(y, 4) == 0.3453:
                    self.ui_text = image_analysis

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.actions.append(("swipe", (x1, y1, x2, y2, duration)))

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=object(),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                subject_recognition_wait_seconds=5,
                max_result_scrolls=1,
                sleep_func=lambda seconds: device.actions.append(("sleep", seconds)),
            )

            self.assertEqual(result.status, "partial")
            self.assertIn(("sleep", 5), device.actions)
            first_subject_wait = device.actions.index(("sleep", 5))
            first_swipe = next(
                index
                for index, action in enumerate(device.actions)
                if action[0] == "swipe"
            )
            self.assertLess(first_subject_wait, first_swipe)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"name": "wait_subject_recognition"', events)
            self.assertIn('"seconds": 5', events)

    def test_deterministic_flow_retries_album_thumbnail_candidates_until_selected(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        album_grid = """
        <hierarchy>
          <node text="全部照片" package="com.xingin.xhs" bounds="[48,649][216,770]" />
          <node text="收起" package="com.xingin.xhs" bounds="[1068,649][1152,770]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[0,775][295,1070]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[301,775][596,1070]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[602,775][897,1070]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click_ratio", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = album_grid

            def click_point(self, x: int, y: int) -> None:
                self.actions.append(("click_point", (x, y)))
                if (x, y) == (148, 922):
                    self.ui_text = album_grid
                elif (x, y) == (448, 922):
                    self.ui_text = "输入关于图片的问题 图片分析中"

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn(("click_point", (148, 922)), device.actions)
            self.assertIn(("click_point", (448, 922)), device.actions)
            self.assertNotIn(("click_ratio", (0.4, 0.4)), device.actions)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("wait_reference_media_scanned", events)
            self.assertIn("album_thumbnail_candidate_not_selected", events)
            self.assertIn('"attempt": 2', events)
            self.assertNotIn("album_image_not_selected", events)

    def test_deterministic_flow_reports_exhausted_album_thumbnail_candidates(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        album_grid = """
        <hierarchy>
          <node text="全部照片" package="com.xingin.xhs" bounds="[48,649][216,770]" />
          <node text="收起" package="com.xingin.xhs" bounds="[1068,649][1152,770]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[0,775][295,1070]" />
          <node class="android.widget.ImageView" package="com.xingin.xhs"
            clickable="true" enabled="true" visible-to-user="true"
            bounds="[301,775][596,1070]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "首页"

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click_ratio", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = album_grid

            def click_point(self, x: int, y: int) -> None:
                self.actions.append(("click_point", (x, y)))
                self.ui_text = album_grid

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "album_thumbnail_candidates_exhausted")
            self.assertEqual(
                result.risk_events,
                [{"event": "album_thumbnail_candidates_exhausted", "item_id": "sku"}],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("album_thumbnail_candidates_exhausted", events)
            self.assertIn('"bounds": [0, 775, 295, 1070]', events)
            self.assertIn('"click_point": [448, 922]', events)

    def test_deterministic_flow_downloads_top_three_results_with_media_pull(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.actions: list[tuple[str, object]] = []
                self.ui_text = "桌垫 买家秀 实拍"
                self.typed: list[str] = []

            def start_app(self, package: str) -> None:
                self.actions.append(("start_app", package))

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                self.actions.append(("push", item_id))
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.actions.append(("click", (x, y)))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中 试试单击图片任意位置搜索"
                elif (x, y) in {(0.25, 0.3), (0.75, 0.3), (0.25, 0.58)}:
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 桌垫 买家秀 实拍"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果 桌垫 买家秀 实拍"

            def set_text(self, text: str) -> None:
                self.actions.append(("set_text", text))
                self.typed.append(text)

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.actions.append(("swipe", (x1, y1, x2, y2, duration)))

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.actions.append(("long_press", (x, y, duration)))
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

            def save_debug_artifacts(self, output_dir: Path, step_name: str) -> None:
                (output_dir / "screenshots").mkdir(parents=True, exist_ok=True)
                (output_dir / "screenshots" / f"{step_name}.xml").write_text(
                    self.ui_text,
                    encoding="utf-8",
                )

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0
                self.pulled: list[tuple[str, Path]] = []

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                self.pulled.append((remote_path, target_path))
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(f"pulled:{remote_path}".encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=3,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                        "keyword_search_box": [0.12, 0.08],
                        "keyword_search_submit": [0.88, 0.08],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            device = FakeDevice()
            media_store = FakeMediaStore()

            def on_after_save() -> None:
                media_store.saved += 1

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=on_after_save,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 6)
            self.assertEqual([image.rank for image in result.images], [1, 2, 3, 1, 2, 3])
            self.assertEqual(
                [image.stage for image in result.images],
                [
                    "image_search",
                    "image_search",
                    "image_search",
                    "keyword_search",
                    "keyword_search",
                    "keyword_search",
                ],
            )
            self.assertEqual(
                [image.query for image in result.images],
                ["", "", "", "桌垫 买家秀 实拍", "桌垫 买家秀 实拍", "桌垫 买家秀 实拍"],
            )
            self.assertEqual(
                [image.local_path.name for image in result.images],
                [
                    "rank_001.jpg",
                    "rank_002.jpg",
                    "rank_003.jpg",
                    "keyword_rank_001.jpg",
                    "keyword_rank_002.jpg",
                    "keyword_rank_003.jpg",
                ],
            )
            self.assertTrue((root / "items" / "sku" / "rank_001.jpg").exists())
            self.assertTrue(
                (root / "items" / "sku" / "keyword_rank_001.jpg").exists()
            )
            self.assertEqual(device.typed, ["桌垫 买家秀 实拍"])
            self.assertIn(
                ("swipe", (0.5, 0.82, 0.5, 0.18, 0.7)),
                device.actions,
            )
            self.assertEqual(
                [action for action, payload in device.actions if action == "long_press"],
                ["long_press", "long_press", "long_press", "long_press", "long_press", "long_press"],
            )
            self.assertEqual(
                [remote for remote, target in media_store.pulled],
                [
                    "/sdcard/Pictures/xhs_collector/saved_1.jpg",
                    "/sdcard/Pictures/xhs_collector/saved_2.jpg",
                    "/sdcard/Pictures/xhs_collector/saved_3.jpg",
                    "/sdcard/Pictures/xhs_collector/saved_4.jpg",
                    "/sdcard/Pictures/xhs_collector/saved_5.jpg",
                    "/sdcard/Pictures/xhs_collector/saved_6.jpg",
                ],
            )
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("download_image_search_rank_1", events)
            self.assertIn("download_keyword_search_rank_1", events)

    def test_deterministic_flow_runs_top_three_keyword_queries(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "桌垫 买家秀 实拍"
                self.typed: list[str] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"
                elif (x, y) in {(0.25, 0.3), (0.75, 0.3)}:
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 笔记"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                self.typed.append(text)
                self.ui_text = f"搜索输入框 {text}"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = "图搜结果 笔记"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["关键词一", "关键词二", "关键词三", "关键词四"],
                reference_image=ref,
                top_n=2,
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(media_store, "saved", media_store.saved + 1),
                save_poll_seconds=0,
                keyword_top_n=3,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 8)
            self.assertEqual(
                [image.query for image in result.images if image.stage == "keyword_search"],
                ["关键词一", "关键词一", "关键词二", "关键词二", "关键词三", "关键词三"],
            )
            self.assertEqual(
                [image.keyword_index for image in result.images if image.stage == "keyword_search"],
                [1, 1, 2, 2, 3, 3],
            )
            self.assertTrue((root / "items" / "sku" / "keyword_001_rank_002.jpg").exists())
            self.assertTrue((root / "items" / "sku" / "keyword_002_rank_002.jpg").exists())
            self.assertTrue((root / "items" / "sku" / "keyword_003_rank_002.jpg").exists())
            self.assertFalse((root / "items" / "sku" / "keyword_rank_001.jpg").exists())
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"name": "start_keyword_search_query"', events)
            self.assertIn('"name": "finish_keyword_search_query"', events)
            self.assertIn('"keyword_index": 3', events)
            self.assertIn('"filename_prefix": "keyword_003_rank"', events)

    def test_deterministic_flow_keyword_top_n_one_keeps_legacy_filename(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "桌垫 买家秀 实拍"
                self.typed: list[str] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"
                elif (x, y) == (0.25, 0.3):
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 笔记"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                self.typed.append(text)

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = "图搜结果 笔记"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["关键词一", "关键词二"],
                reference_image=ref,
                top_n=1,
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(media_store, "saved", media_store.saved + 1),
                save_poll_seconds=0,
                keyword_top_n=1,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 2)
            self.assertTrue((root / "items" / "sku" / "keyword_rank_001.jpg").exists())
            self.assertFalse((root / "items" / "sku" / "keyword_001_rank_001.jpg").exists())

    def test_deterministic_flow_keyword_top_n_zero_skips_keyword_search(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "桌垫 买家秀 实拍"
                self.typed: list[str] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"
                elif (x, y) == (0.25, 0.3):
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 笔记"

            def set_text(self, text: str) -> None:
                self.typed.append(text)

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = "图搜结果 笔记"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["关键词一", "关键词二"],
                reference_image=ref,
                top_n=1,
            )
            device = FakeDevice()
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=media_store,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(media_store, "saved", media_store.saved + 1),
                save_poll_seconds=0,
                keyword_top_n=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 1)
            self.assertEqual(device.typed, [])
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("start_keyword_search_query", events)

    def test_deterministic_flow_dedupes_saved_media_across_keyword_stages(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "桌垫 买家秀 实拍"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"
                elif (x, y) in {(0.25, 0.3), (0.75, 0.3)}:
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 笔记"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                self.ui_text = f"搜索输入框 {text}"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = "图搜结果 笔记"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                content = b"same-image"
                if remote_path.endswith("saved_3.jpg"):
                    content = b"keyword-unique"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(content)
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["关键词一"],
                reference_image=ref,
                top_n=1,
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(media_store, "saved", media_store.saved + 1),
                save_poll_seconds=0,
                keyword_top_n=1,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 2)
            self.assertEqual((root / "items" / "sku" / "keyword_rank_001.jpg").read_bytes(), b"keyword-unique")
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("duplicate_saved_media", events)

    def test_download_visible_note_results_downloads_top_ten_across_scrolls(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _download_visible_note_results,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        def result_list_xml(page: int) -> str:
            first = page * 2 + 1
            second = first + 1
            return f"""
            <hierarchy>
              <node class="android.widget.LinearLayout" text="note-{first}"
                    clickable="true" long-clickable="true"
                    bounds="[15,500][593,1530]" />
              <node class="android.widget.LinearLayout" text="note-{second}"
                    clickable="true" long-clickable="true"
                    bounds="[607,495][1185,1268]" />
            </hierarchy>
            """

        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
          <node text="说点什么" bounds="[170,2300][400,2400]" />
        </hierarchy>
        """
        save_xml = """
        <hierarchy>
          <node class="android.widget.TextView" text="保存图片" clickable="true"
                bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.page = 0
                self.state = "list"
                self.saved = 0
                self.initial_swipe_done = False
                self.scrolls = 0

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.state == "list":
                    return result_list_xml(self.page)
                if self.state == "save":
                    return save_xml
                return note_xml

            def click_point(self, x: int, y: int) -> None:
                if (x, y) in {(304, 1015), (896, 882)}:
                    self.state = "note"
                elif (x, y) == (300, 2160):
                    self.saved += 1
                    self.state = "note"
                elif (x, y) == (79, 128):
                    self.state = "list"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("visible card targets should come from XML")

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if not self.initial_swipe_done:
                    self.initial_swipe_done = True
                    self.state = "list"
                    return
                self.scrolls += 1
                self.page += 1
                self.state = "list"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.state = "save"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.device.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(f"image:{remote_path}".encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = InputItem(item_id="sku", keyword="", top_n=10)
            device = FakeDevice()
            events: list[tuple[str, dict | None]] = []

            images, failures = _download_visible_note_results(
                stage="image_search",
                query="",
                filename_prefix="rank",
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                step=lambda name, payload=None: events.append((name, payload)),
            )

            self.assertEqual(failures, [])
            self.assertEqual(len(images), 10)
            self.assertEqual([image.rank for image in images], list(range(1, 11)))
            self.assertTrue((root / "items" / "sku" / "rank_010.jpg").exists())
            self.assertGreaterEqual(device.scrolls, 4)
            event_names = [name for name, payload in events]
            self.assertIn("scroll_image_search_result_list", event_names)
            self.assertIn("download_image_search_rank_10", event_names)

            keyword_device = FakeDevice()
            keyword_events: list[tuple[str, dict | None]] = []
            keyword_images, keyword_failures = _download_visible_note_results(
                stage="keyword_search",
                query="白底红格桌垫 餐桌布置",
                filename_prefix="keyword_rank",
                item=item,
                device=keyword_device,
                media_store=FakeMediaStore(keyword_device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                step=lambda name, payload=None: keyword_events.append((name, payload)),
            )

            self.assertEqual(keyword_failures, [])
            self.assertEqual(len(keyword_images), 10)
            self.assertTrue((root / "items" / "sku" / "keyword_rank_010.jpg").exists())
            self.assertIn(
                "download_keyword_search_rank_10",
                [name for name, payload in keyword_events],
            )

    def test_download_visible_note_results_does_not_consume_rank_on_save_failure(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _download_visible_note_results,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" text="note-1"
                clickable="true" long-clickable="true"
                bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" text="note-2"
                clickable="true" long-clickable="true"
                bounds="[607,495][1185,1268]" />
          <node class="android.widget.LinearLayout" text="note-3"
                clickable="true" long-clickable="true"
                bounds="[15,1533][593,2563]" />
        </hierarchy>
        """
        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
        </hierarchy>
        """
        save_xml = """
        <hierarchy>
          <node text="保存图片" clickable="true" bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.state = "list"
                self.current_note = ""
                self.saved_paths: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.state == "save":
                    return save_xml
                if self.state == "note":
                    return note_xml
                return result_list_xml

            def click_point(self, x: int, y: int) -> None:
                centers = {
                    (304, 1015): "note-1",
                    (896, 882): "note-2",
                    (304, 2048): "note-3",
                }
                if (x, y) in centers:
                    self.current_note = centers[(x, y)]
                    self.state = "note"
                elif (x, y) == (300, 2160):
                    if self.current_note != "note-1":
                        self.saved_paths.append(
                            f"/sdcard/Pictures/xhs_collector/{self.current_note}.jpg"
                        )
                    self.state = "note"
                elif (x, y) == (79, 128):
                    self.state = "list"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("coordinate fallback should not be used")

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.state = "list"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.state = "save"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                return list(self.device.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = InputItem(item_id="sku", keyword="", top_n=2)
            device = FakeDevice()
            events: list[tuple[str, dict | None]] = []

            images, failures = _download_visible_note_results(
                stage="image_search",
                query="",
                filename_prefix="rank",
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                step=lambda name, payload=None: events.append((name, payload)),
            )

            self.assertEqual([image.rank for image in images], [1, 2])
            self.assertEqual([image.local_path.name for image in images], ["rank_001.jpg", "rank_002.jpg"])
            self.assertTrue(any(failure["event"] == "save_rank_failed" for failure in failures))
            self.assertTrue((root / "items" / "sku" / "rank_001.jpg").exists())
            self.assertTrue((root / "items" / "sku" / "rank_002.jpg").exists())

    def test_download_visible_note_results_skips_duplicate_note_cards_across_scrolls(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _download_visible_note_results,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        def result_list_xml(page: int) -> str:
            labels = [["note-a", "note-b"], ["note-a", "note-c"]][min(page, 1)]
            return f"""
            <hierarchy>
              <node class="android.widget.LinearLayout" text="{labels[0]}"
                    clickable="true" long-clickable="true"
                    bounds="[15,500][593,1530]" />
              <node class="android.widget.LinearLayout" text="{labels[1]}"
                    clickable="true" long-clickable="true"
                    bounds="[607,495][1185,1268]" />
            </hierarchy>
            """

        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
        </hierarchy>
        """
        save_xml = """
        <hierarchy>
          <node text="保存图片" clickable="true" bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.page = 0
                self.state = "list"
                self.initial_swipe_done = False
                self.current_note = ""
                self.saved_paths: list[str] = []
                self.opened_notes: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.state == "save":
                    return save_xml
                if self.state == "note":
                    return note_xml
                return result_list_xml(self.page)

            def click_point(self, x: int, y: int) -> None:
                labels = [["note-a", "note-b"], ["note-a", "note-c"]][min(self.page, 1)]
                centers = {(304, 1015): labels[0], (896, 882): labels[1]}
                if (x, y) in centers:
                    self.current_note = centers[(x, y)]
                    self.opened_notes.append(self.current_note)
                    self.state = "note"
                elif (x, y) == (300, 2160):
                    self.saved_paths.append(
                        f"/sdcard/Pictures/xhs_collector/{self.current_note}-{len(self.saved_paths)}.jpg"
                    )
                    self.state = "note"
                elif (x, y) == (79, 128):
                    self.state = "list"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("coordinate fallback should not be used")

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if not self.initial_swipe_done:
                    self.initial_swipe_done = True
                else:
                    self.page += 1
                self.state = "list"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.state = "save"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                return list(self.device.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = InputItem(item_id="sku", keyword="", top_n=3)
            device = FakeDevice()
            events: list[tuple[str, dict | None]] = []

            images, failures = _download_visible_note_results(
                stage="image_search",
                query="",
                filename_prefix="rank",
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                step=lambda name, payload=None: events.append((name, payload)),
            )

            self.assertEqual(failures, [])
            self.assertEqual(len(images), 3)
            self.assertEqual(device.opened_notes, ["note-a", "note-b", "note-c"])
            self.assertIn("skip_duplicate_note_card", [name for name, payload in events])

    def test_download_visible_note_results_filters_note_cards_by_target_category(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _download_visible_note_results,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" text="餐桌 椅子 家居布置"
                clickable="true" long-clickable="true"
                bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" text="红格桌垫 餐桌垫 买家秀"
                clickable="true" long-clickable="true"
                bounds="[607,495][1185,1268]" />
        </hierarchy>
        """
        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
        </hierarchy>
        """
        save_xml = """
        <hierarchy>
          <node text="保存图片" clickable="true" bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.state = "list"
                self.saved_paths: list[str] = []
                self.opened_notes: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.state == "save":
                    return save_xml
                if self.state == "note":
                    return note_xml
                return result_list_xml

            def click_point(self, x: int, y: int) -> None:
                if (x, y) == (304, 1015):
                    raise AssertionError("category mismatch card should not be opened")
                if (x, y) == (896, 882):
                    self.opened_notes.append("红格桌垫 餐桌垫 买家秀")
                    self.state = "note"
                elif (x, y) == (300, 2160):
                    self.saved_paths.append("/sdcard/Pictures/xhs_collector/桌垫.jpg")
                    self.state = "note"
                elif (x, y) == (79, 128):
                    self.state = "list"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("coordinate fallback should not be used")

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.state = "list"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.state = "save"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                return list(self.device.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = InputItem(item_id="sku", keyword="", top_n=1)
            device = FakeDevice()
            events: list[tuple[str, dict | None]] = []

            images, failures = _download_visible_note_results(
                stage="image_search",
                query="",
                filename_prefix="rank",
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                target_category="桌垫",
                target_category_keywords=["桌垫", "餐桌垫", "餐垫", "桌垫桌布"],
                step=lambda name, payload=None: events.append((name, payload)),
            )

            self.assertEqual(failures, [])
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0].rank, 1)
            self.assertEqual(device.opened_notes, ["红格桌垫 餐桌垫 买家秀"])
            mismatch_events = [
                payload
                for name, payload in events
                if name == "skip_result_card_category_mismatch"
            ]
            self.assertEqual(len(mismatch_events), 1)
            self.assertEqual(mismatch_events[0]["target_category"], "桌垫")
            self.assertIn("餐桌 椅子", mismatch_events[0]["card_text"])
            self.assertEqual(mismatch_events[0]["matched_keyword"], None)

    def test_download_visible_note_results_skips_duplicate_saved_media_hash(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _download_visible_note_results,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" text="note-1"
                clickable="true" long-clickable="true"
                bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" text="note-2"
                clickable="true" long-clickable="true"
                bounds="[607,495][1185,1268]" />
          <node class="android.widget.LinearLayout" text="note-3"
                clickable="true" long-clickable="true"
                bounds="[15,1533][593,2563]" />
        </hierarchy>
        """
        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
        </hierarchy>
        """
        save_xml = """
        <hierarchy>
          <node text="保存图片" clickable="true" bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.state = "list"
                self.current_note = ""
                self.saved_paths: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                if self.state == "save":
                    return save_xml
                if self.state == "note":
                    return note_xml
                return result_list_xml

            def click_point(self, x: int, y: int) -> None:
                centers = {
                    (304, 1015): "note-1",
                    (896, 882): "note-2",
                    (304, 2048): "note-3",
                }
                if (x, y) in centers:
                    self.current_note = centers[(x, y)]
                    self.state = "note"
                elif (x, y) == (300, 2160):
                    self.saved_paths.append(
                        f"/sdcard/Pictures/xhs_collector/{self.current_note}.jpg"
                    )
                    self.state = "note"
                elif (x, y) == (79, 128):
                    self.state = "list"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("coordinate fallback should not be used")

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.state = "list"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.state = "save"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                return list(self.device.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                content = b"same-image"
                if "note-3" in remote_path:
                    content = b"unique-image"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(content)
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = InputItem(item_id="sku", keyword="", top_n=2)
            device = FakeDevice()
            events: list[tuple[str, dict | None]] = []

            images, failures = _download_visible_note_results(
                stage="image_search",
                query="",
                filename_prefix="rank",
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
                on_after_save=None,
                step=lambda name, payload=None: events.append((name, payload)),
            )

            self.assertEqual([image.rank for image in images], [1, 2])
            self.assertEqual((root / "items" / "sku" / "rank_002.jpg").read_bytes(), b"unique-image")
            self.assertTrue(any(failure["event"] == "duplicate_saved_media" for failure in failures))
            self.assertIn("duplicate_saved_media", [name for name, payload in events])

    def test_deterministic_flow_does_not_long_press_when_note_card_is_not_opened(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"
                self.long_press_count = 0

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                pass

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                pass

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.long_press_count += 1

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def snapshot(self) -> list[str]:
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                raise AssertionError("pull should not run when card is not opened")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "keyword_search_box": [0.12, 0.08],
                        "keyword_search_submit": [0.88, 0.08],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=FakeMediaStore(),
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "partial")
            self.assertEqual(result.collected_count, 0)
            self.assertEqual(device.long_press_count, 0)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("note_card_not_opened", events)
            self.assertIn("continue_keyword_search_after_image_download_failures", events)
            self.assertIn("tap_keyword_search_box", events)
            self.assertNotIn("skip_keyword_search_due_to_image_download_failure", events)

    def test_note_card_candidates_use_large_clickable_card_bounds(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _find_note_card_candidates,
        )

        hierarchy = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,404][593,497]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[607,495][1185,1268]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="false" bounds="[15,1533][593,2563]" />
        </hierarchy>
        """

        candidates = _find_note_card_candidates(hierarchy, (1200, 2670))

        self.assertEqual(candidates[0]["bounds"], [15, 500, 593, 1530])
        self.assertEqual(candidates[0]["center"], [304, 1015])
        self.assertEqual(candidates[1]["bounds"], [607, 495, 1185, 1268])

    def test_keyword_search_targets_ignore_suggestion_nodes(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _find_keyword_search_box_target,
            _find_keyword_search_submit_target,
        )

        hierarchy = """
        <hierarchy>
          <node class="android.widget.TextView" text="桌垫 搜索推荐"
                clickable="true" bounds="[20,360][1180,470]" />
          <node class="android.widget.EditText" text="搜索小红书"
                clickable="true" bounds="[90,80][920,180]" />
          <node class="android.widget.TextView" text="搜索"
                clickable="true" bounds="[980,80][1160,180]" />
        </hierarchy>
        """

        search_box = _find_keyword_search_box_target(hierarchy, (1200, 2670))
        submit = _find_keyword_search_submit_target(hierarchy, (1200, 2670))

        self.assertEqual(search_box["bounds"], [90, 80, 920, 180])
        self.assertEqual(submit["bounds"], [980, 80, 1160, 180])
        self.assertEqual(submit["matched_marker"], "搜索")

    def test_keyword_search_submit_does_not_use_suggestion_as_submit(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _perform_keyword_search,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        hierarchy = """
        <hierarchy>
          <node class="android.widget.EditText" text="搜索小红书"
                clickable="true" bounds="[90,80][920,180]" />
          <node class="android.widget.TextView" text="桌垫 搜索推荐"
                clickable="true" bounds="[20,360][1180,470]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.point_clicks: list[tuple[int, int]] = []
                self.ratio_clicks: list[tuple[float, float]] = []
                self.typed: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return hierarchy

            def click_point(self, x: int, y: int) -> None:
                self.point_clicks.append((x, y))

            def click_ratio(self, x: float, y: float) -> None:
                self.ratio_clicks.append((x, y))

            def set_text(self, text: str) -> None:
                self.typed.append(text)

        events: list[tuple[str, dict | None]] = []
        device = FakeDevice()
        profile = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.1, 0.1],
                    "image_search_button": [0.2, 0.2],
                    "album_entry": [0.3, 0.3],
                    "first_album_image": [0.4, 0.4],
                    "album_confirm": [0.5, 0.5],
                    "keyword_search_box": [0.12, 0.08],
                }
            }
        )
        item = InputItem(item_id="sku", keyword="", top_n=1)

        started = _perform_keyword_search(
            query="桌垫 买家秀 实拍",
            item=item,
            device=device,
            profile=profile,
            save_poll_seconds=0,
            sleep_func=lambda seconds: None,
            step=lambda name, payload=None: events.append((name, payload)),
        )

        self.assertFalse(started)
        self.assertEqual(device.typed, ["桌垫 买家秀 实拍"])
        self.assertEqual(device.point_clicks, [(505, 130)])
        self.assertEqual(device.ratio_clicks, [])
        self.assertIn(("keyword_search_submit_not_found", {"query": "桌垫 买家秀 实拍"}), events)

    def test_keyword_search_submits_with_top_search_button_bounds(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _perform_keyword_search,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        input_hierarchy = """
        <hierarchy>
          <node class="android.widget.EditText" text="搜索小红书"
                clickable="true" bounds="[90,80][920,180]" />
          <node class="android.widget.TextView" text="搜索"
                clickable="true" bounds="[980,80][1160,180]" />
          <node class="android.widget.TextView" text="桌垫 搜索推荐"
                clickable="true" bounds="[20,360][1180,470]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = input_hierarchy
                self.point_clicks: list[tuple[int, int]] = []
                self.typed: list[str] = []

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_point(self, x: int, y: int) -> None:
                self.point_clicks.append((x, y))
                if (x, y) == (1070, 130):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def click_ratio(self, x: float, y: float) -> None:
                raise AssertionError("explicit hierarchy targets should be used")

            def set_text(self, text: str) -> None:
                self.typed.append(text)

        events: list[tuple[str, dict | None]] = []
        device = FakeDevice()
        profile = CoordinateProfile.from_dict(
            {
                "points": {
                    "search_box": [0.1, 0.1],
                    "image_search_button": [0.2, 0.2],
                    "album_entry": [0.3, 0.3],
                    "first_album_image": [0.4, 0.4],
                    "album_confirm": [0.5, 0.5],
                    "keyword_search_box": [0.12, 0.08],
                    "keyword_search_submit": [0.88, 0.08],
                }
            }
        )
        item = InputItem(item_id="sku", keyword="", top_n=1)

        started = _perform_keyword_search(
            query="桌垫 买家秀 实拍",
            item=item,
            device=device,
            profile=profile,
            save_poll_seconds=0,
            sleep_func=lambda seconds: None,
            step=lambda name, payload=None: events.append((name, payload)),
        )

        self.assertTrue(started)
        self.assertEqual(device.typed, ["桌垫 买家秀 实拍"])
        self.assertEqual(device.point_clicks, [(505, 130), (1070, 130)])
        submit_event = next(
            payload for name, payload in events if name == "tap_keyword_search_submit"
        )
        self.assertEqual(submit_event["keyword_submit_source"], "ui_hierarchy")
        self.assertEqual(submit_event["keyword_submit_bounds"], [980, 80, 1160, 180])

    def test_deterministic_flow_clicks_note_card_from_ui_hierarchy_bounds(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="androidx.recyclerview.widget.RecyclerView"
                scrollable="true" bounds="[0,404][1200,2670]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[607,495][1185,1268]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"
                self.point_clicks: list[tuple[int, int]] = []
                self.ratio_clicks: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.ratio_clicks.append((x, y))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = result_list_xml

            def click_point(self, x: int, y: int) -> None:
                self.point_clicks.append((x, y))
                if (x, y) == (304, 1015):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if (x1, y1, x2, y2) == (0.5, 0.82, 0.5, 0.18):
                    self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                if self.saved:
                    return ["/sdcard/Pictures/xhs_collector/saved.jpg"]
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            media_store = FakeMediaStore()
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(media_store, "saved", 1),
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 1)
            self.assertIn((304, 1015), device.point_clicks)
            self.assertNotIn((0.25, 0.3), device.ratio_clicks)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"click_source": "ui_hierarchy"', events)
            self.assertIn('"card_bounds": [15, 500, 593, 1530]', events)

    def test_deterministic_flow_prefers_save_menu_text_bounds(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
        </hierarchy>
        """
        save_menu_xml = """
        <hierarchy>
          <node class="android.widget.TextView" text="保存图片" clickable="true"
                bounds="[100,2100][500,2220]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"
                self.saved = False
                self.point_clicks: list[tuple[int, int]] = []
                self.ratio_clicks: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.ratio_clicks.append((x, y))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = result_list_xml

            def click_point(self, x: int, y: int) -> None:
                self.point_clicks.append((x, y))
                if (x, y) == (304, 1015):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"
                elif (x, y) == (300, 2160):
                    self.saved = True
                    self.ui_text = "已保存"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if (x1, y1, x2, y2) == (0.5, 0.82, 0.5, 0.18):
                    self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = save_menu_xml

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                if self.device.saved:
                    return ["/sdcard/Pictures/xhs_collector/saved.jpg"]
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn((300, 2160), device.point_clicks)
            self.assertNotIn((0.5, 0.82), device.ratio_clicks)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"save_click_source": "ui_hierarchy"', events)

    def test_deterministic_flow_waits_for_list_after_back_before_next_rank(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[607,495][1185,1268]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = result_list_xml

            def click_point(self, x: int, y: int) -> None:
                if (x, y) in {(304, 1015), (896, 882)}:
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=2,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(
                    media_store, "saved", media_store.saved + 1
                ),
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.collected_count, 2)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            wait_index = events.index("wait_back_to_image_search_result_list_rank_1")
            open_second_index = events.index("open_image_search_result_card_rank_2")
            self.assertLess(wait_index, open_second_index)

    def test_deterministic_flow_stops_next_rank_when_back_does_not_restore_list(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[607,495][1185,1268]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"

            def click_point(self, x: int, y: int) -> None:
                if (x, y) == (304, 1015):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if (x1, y1, x2, y2) == (0.5, 0.82, 0.5, 0.18):
                    self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(b"image")
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=2,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(
                    media_store, "saved", media_store.saved + 1
                ),
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.collected_count, 1)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("result_list_not_restored_after_back", events)
            self.assertNotIn("open_image_search_result_card_rank_2", events)

    def test_deterministic_flow_classifies_download_permission_disabled(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[607,495][1185,1268]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "作者已关闭下载权限"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = result_list_xml
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def click_point(self, x: int, y: int) -> None:
                if (x, y) == (304, 1015):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"
                elif (x, y) == (896, 882):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def set_text(self, text: str) -> None:
                self.ui_text = f"搜索输入框 {text}"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def snapshot(self) -> list[str]:
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                raise AssertionError("pull should not run when save is denied")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=2,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "keyword_search_box": [0.12, 0.08],
                        "keyword_search_submit": [0.88, 0.08],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=FakeMediaStore(),
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "partial")
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"reason": "download_permission_disabled"', events)
            self.assertIn('"permission_hint": "作者已关闭下载权限"', events)
            self.assertIn("wait_back_to_image_search_result_list_rank_1", events)
            self.assertIn("continue_keyword_search_after_image_download_failures", events)
            self.assertIn("tap_keyword_search_box", events)
            self.assertNotIn("skip_keyword_search_due_to_image_download_failure", events)

    def test_deterministic_flow_uses_ui_back_button_before_profile_coordinate(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
        </hierarchy>
        """
        note_xml = """
        <hierarchy>
          <node text="<" clickable="true" bounds="[18,66][140,190]" />
          <node text="评论" bounds="[30,2300][160,2400]" />
          <node text="说点什么" bounds="[170,2300][400,2400]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"
                self.saved = False
                self.point_clicks: list[tuple[int, int]] = []
                self.ratio_clicks: list[tuple[float, float]] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.ratio_clicks.append((x, y))
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.saved = True
                    self.ui_text = note_xml

            def click_point(self, x: int, y: int) -> None:
                self.point_clicks.append((x, y))
                if (x, y) == (304, 1015):
                    self.ui_text = note_xml
                elif (x, y) == (79, 128):
                    self.ui_text = result_list_xml

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                if self.device.saved:
                    return ["/sdcard/Pictures/xhs_collector/saved.jpg"]
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(b"image")
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertIn((79, 128), device.point_clicks)
            self.assertNotIn((0.06, 0.07), device.ratio_clicks)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"back_source": "ui_hierarchy"', events)
            self.assertIn('"back_bounds": [18, 66, 140, 190]', events)

    def test_deterministic_flow_uses_system_back_when_button_fallbacks_fail(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        result_list_xml = """
        <hierarchy>
          <node class="android.widget.LinearLayout" clickable="true"
                long-clickable="true" bounds="[15,500][593,1530]" />
        </hierarchy>
        """

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"
                self.saved = False
                self.press_back_count = 0
                self.horizontal_swipe_count = 0

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def window_size(self) -> tuple[int, int]:
                return (1200, 2670)

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "图片分析中"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.saved = True
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def click_point(self, x: int, y: int) -> None:
                if (x, y) == (304, 1015):
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                if (x1, y1, x2, y2) == (0.08, 0.5, 0.85, 0.5):
                    self.horizontal_swipe_count += 1
                    self.ui_text = "笔记详情 评论 说点什么 收藏 分享 图片已切换"
                else:
                    self.ui_text = result_list_xml

            def press_back(self) -> None:
                self.press_back_count += 1
                self.ui_text = result_list_xml

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self, device: FakeDevice) -> None:
                self.device = device

            def snapshot(self) -> list[str]:
                if self.device.saved:
                    return ["/sdcard/Pictures/xhs_collector/saved.jpg"]
                return []

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(b"image")
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=FakeMediaStore(device),
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(device.press_back_count, 1)
            self.assertEqual(device.horizontal_swipe_count, 0)
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"back_source": "system_back"', events)
            self.assertNotIn('"back_source": "swipe_gesture"', events)

    def test_deterministic_flow_continues_when_one_rank_save_times_out(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中 试试单击图片任意位置搜索"
                elif (x, y) in {(0.25, 0.3), (0.75, 0.3), (0.25, 0.58)}:
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                pass

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                pass

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved_paths: list[str] = []
                self.pull_targets: list[Path] = []
                self.attempt = 0

            def snapshot(self) -> list[str]:
                return list(self.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                self.pull_targets.append(target_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=3,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                        "keyword_search_box": [0.12, 0.08],
                        "keyword_search_submit": [0.88, 0.08],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            media_store = FakeMediaStore()

            def on_after_save() -> None:
                media_store.attempt += 1
                if media_store.attempt not in {2, 3}:
                    media_store.saved_paths.append(
                        f"/sdcard/Pictures/xhs_collector/saved_{media_store.attempt}.png"
                    )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=on_after_save,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "partial")
            self.assertEqual(result.collected_count, 5)
            self.assertEqual([image.rank for image in result.images], [1, 2, 1, 2, 3])
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("save_rank_failed", events)
            self.assertTrue((root / "items" / "sku" / "rank_002.png").exists())

    def test_deterministic_flow_retries_save_once_when_media_diff_is_late(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "图搜结果"

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中 试试单击图片任意位置搜索"
                elif (x, y) == (0.25, 0.3):
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果"

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                pass

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved_paths: list[str] = []
                self.save_attempts = 0

            def snapshot(self) -> list[str]:
                return list(self.saved_paths)

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(b"image")
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="",
                keyword_candidates=[],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_panel_swipe_start": [0.5, 0.82],
                        "results_panel_swipe_end": [0.5, 0.18],
                        "result_card_1": [0.25, 0.3],
                        "result_card_2": [0.75, 0.3],
                        "result_card_3": [0.25, 0.58],
                        "note_main_image": [0.5, 0.4],
                        "save_image_menu_item": [0.5, 0.82],
                        "note_back_button": [0.06, 0.07],
                    }
                }
            )
            media_store = FakeMediaStore()

            def on_after_save() -> None:
                media_store.save_attempts += 1
                if media_store.save_attempts == 2:
                    media_store.saved_paths.append(
                        "/sdcard/Pictures/xhs_collector/retry_saved.jpg"
                    )

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=on_after_save,
                save_poll_seconds=0,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 1)
            self.assertEqual(media_store.save_attempts, 2)
            self.assertTrue((root / "items" / "sku" / "rank_001.jpg").exists())
            events = (root / "step_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("retry_save_after_no_new_media", events)
            self.assertNotIn("save_rank_failed", events)

    def test_deterministic_flow_stops_on_risk_before_clicking(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_device import (
            CoordinateProfile,
        )
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "请输入验证码"
                self.clicks = 0

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                self.clicks += 1

            def screenshot(self) -> bytes:
                return b"png"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["桌垫 买家秀 实拍"],
                reference_image=ref,
                top_n=1,
            )
            profile = CoordinateProfile.from_dict(
                {
                    "points": {
                        "search_box": [0.1, 0.1],
                        "image_search_button": [0.2, 0.2],
                        "album_entry": [0.3, 0.3],
                        "first_album_image": [0.4, 0.4],
                        "album_confirm": [0.5, 0.5],
                        "results_anchor": [0.8, 0.8],
                    }
                }
            )
            device = FakeDevice()

            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=None,
                profile=profile,
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.message, "captcha_required")
            self.assertEqual(device.clicks, 0)

    def test_deterministic_failure_classifies_input_injection_permission(self) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            _deterministic_failure_event,
        )

        event = _deterministic_failure_event(
            Exception(
                "java.lang.SecurityException: Injecting input events requires the caller to have the INJECT_EVENTS permission"
            )
        )

        self.assertEqual(event["event"], "device_input_permission_required")
        self.assertIn("INJECT_EVENTS", event["reason"])

    def test_manifest_status_is_failed_when_every_item_failed_without_downloads(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import ItemResult
        from third_party.xhs_collector.xhs_collector.runner import (
            _manifest_status_from_results,
        )

        status = _manifest_status_from_results(
            [
                ItemResult(
                    item_id="sku",
                    keyword="",
                    status="failed",
                    collected_count=0,
                    risk_events=[{"event": "device_input_permission_required"}],
                )
            ]
        )

        self.assertEqual(status, "failed")

    def test_manifest_status_is_canceled_when_every_item_canceled(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import ItemResult
        from third_party.xhs_collector.xhs_collector.runner import (
            _manifest_status_from_results,
        )

        status = _manifest_status_from_results(
            [
                ItemResult(
                    item_id="sku",
                    keyword="",
                    status="canceled",
                    collected_count=0,
                    risk_events=[{"event": "collection_canceled"}],
                )
            ]
        )

        self.assertEqual(status, "canceled")

    def test_manifest_status_is_partial_when_canceled_after_downloads(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import ItemResult
        from third_party.xhs_collector.xhs_collector.runner import (
            _manifest_status_from_results,
        )

        status = _manifest_status_from_results(
            [
                ItemResult(
                    item_id="sku",
                    keyword="",
                    status="canceled",
                    collected_count=1,
                    risk_events=[{"event": "collection_canceled"}],
                )
            ]
        )

        self.assertEqual(status, "partial")

    def test_run_collect_passes_cancel_token_to_deterministic_runner(self) -> None:
        from third_party.xhs_collector.xhs_collector.runner import run_collect

        class FakeCancelToken:
            def is_cancel_requested(self) -> bool:
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [["item_id", "keyword", "image_path"], ["sku", "桌垫", str(image_path)]],
            )
            profile_path = root / "coords.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "points": {
                            "search_box": [0.1, 0.1],
                            "image_search_button": [0.15, 0.15],
                            "album_entry": [0.2, 0.2],
                            "first_album_image": [0.25, 0.25],
                            "album_confirm": [0.3, 0.3],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "output_root": str(root / "runs"),
                        "mode": "deterministic",
                        "top_n": 1,
                        "deterministic": {"coordinate_profile": str(profile_path)},
                    }
                ),
                encoding="utf-8",
            )
            token = FakeCancelToken()

            with mock.patch(
                "third_party.xhs_collector.xhs_collector.runner.run_deterministic_collect"
            ) as deterministic:
                run_collect(excel_path, config_path, cancel_token=token)

        self.assertIs(deterministic.call_args.kwargs["cancel_token"], token)

    def test_run_collect_routes_deterministic_mode(self) -> None:
        from third_party.xhs_collector.xhs_collector.runner import run_collect

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [["item_id", "keyword", "image_path"], ["sku", "桌垫", str(image_path)]],
            )
            config_path = root / "config.json"
            profile_path = root / "coords.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "points": {
                            "search_box": [0.1, 0.1],
                            "image_search_button": [0.15, 0.15],
                            "album_entry": [0.2, 0.2],
                            "first_album_image": [0.25, 0.25],
                            "album_confirm": [0.3, 0.3],
                            "results_anchor": [0.5, 0.5],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "output_root": str(root / "runs"),
                        "mode": "deterministic",
                        "top_n": 1,
                        "deterministic": {
                            "coordinate_profile": str(profile_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "third_party.xhs_collector.xhs_collector.runner.run_deterministic_collect"
            ) as deterministic:
                result = run_collect(excel_path, config_path)

        self.assertEqual(result.status, "completed")
        deterministic.assert_called_once()

    def test_deterministic_manifest_includes_mode_profile_templates_and_steps(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.models import ItemResult
        from third_party.xhs_collector.xhs_collector.runner import run_collect

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            excel_path = root / "items.xlsx"
            _write_xlsx(
                excel_path,
                [["item_id", "keyword", "image_path"], ["sku", "桌垫", str(image_path)]],
            )
            profile_path = root / "coords.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "points": {
                            "search_box": [0.1, 0.1],
                            "image_search_button": [0.15, 0.15],
                            "album_entry": [0.2, 0.2],
                            "first_album_image": [0.25, 0.25],
                            "album_confirm": [0.3, 0.3],
                            "results_anchor": [0.5, 0.5],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "config.json"
            output_root = root / "runs"
            config_path.write_text(
                json.dumps(
                    {
                        "output_root": str(output_root),
                        "mode": "deterministic",
                        "top_n": 1,
                        "deterministic": {"coordinate_profile": str(profile_path)},
                    }
                ),
                encoding="utf-8",
            )

            def fake_collect(**kwargs) -> None:
                kwargs["write_result"](
                    ItemResult(
                        item_id="sku",
                        keyword="桌垫",
                        status="completed",
                        step_count=7,
                        template_hits=[
                            {
                                "item_id": "sku",
                        "step": "wait_image_search_results",
                        "template": "results_anchor",
                        "score": 0.93,
                    }
                ],
                    )
                )

            with mock.patch(
                "third_party.xhs_collector.xhs_collector.runner.run_deterministic_collect",
                side_effect=fake_collect,
            ):
                manifest = run_collect(excel_path, config_path)

            payload = json.loads(
                (output_root / manifest.run_id / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["mode"], "deterministic")
            self.assertEqual(payload["coordinate_profile"], str(profile_path))
            self.assertEqual(payload["step_count"], 7)
            self.assertEqual(payload["template_hits"][0]["template"], "results_anchor")

    def test_real_excel_enters_deterministic_runner_with_nine_items(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import ItemResult
        from third_party.xhs_collector.xhs_collector.runner import run_collect

        workbook = (
            Path(__file__).resolve().parents[1]
            / "input_image"
            / "买家秀场景图"
            / "桌垫买家秀_TOP10关键词组合.xlsx"
        )
        if not workbook.exists():
            self.skipTest(f"fixture workbook not found: {workbook}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "coords.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "points": {
                            "search_box": [0.1, 0.1],
                            "image_search_button": [0.15, 0.15],
                            "album_entry": [0.2, 0.2],
                            "first_album_image": [0.25, 0.25],
                            "album_confirm": [0.3, 0.3],
                            "results_anchor": [0.5, 0.5],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "output_root": str(root / "runs"),
                        "mode": "deterministic",
                        "top_n": 1,
                        "deterministic": {"coordinate_profile": str(profile_path)},
                    }
                ),
                encoding="utf-8",
            )

            def fake_collect(**kwargs) -> None:
                self.assertEqual(len(kwargs["items"]), 9)
                for item in kwargs["items"]:
                    kwargs["write_result"](
                        ItemResult(
                            item_id=item.item_id,
                            keyword=item.keyword,
                            keyword_candidates=item.keyword_candidates,
                            status="completed",
                            step_count=1,
                        )
                    )

            with mock.patch(
                "third_party.xhs_collector.xhs_collector.runner.run_deterministic_collect",
                side_effect=fake_collect,
            ):
                manifest = run_collect(workbook, config_path)

            self.assertEqual(len(manifest.results), 9)
            self.assertEqual(manifest.mode, "deterministic")
            self.assertEqual(len(manifest.results[0].keyword_candidates), 10)

    def test_mode_override_preserves_config_top_n_when_top_n_not_provided(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig
        from third_party.xhs_collector.xhs_collector.runner import _config_with_overrides

        config = CollectorConfig.from_dict({"top_n": 3, "keyword_top_n": 2})

        updated = _config_with_overrides(config, mode="deterministic")

        self.assertEqual(updated.top_n, 3)
        self.assertEqual(updated.keyword_top_n, 2)
        self.assertEqual(updated.mode, "deterministic")

    def test_keyword_top_n_override_updates_config(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig
        from third_party.xhs_collector.xhs_collector.runner import _config_with_overrides

        config = CollectorConfig.from_dict({"keyword_top_n": 1})

        updated = _config_with_overrides(config, keyword_top_n=3)

        self.assertEqual(updated.keyword_top_n, 3)

    def test_collector_config_supports_stage_specific_download_counts(self) -> None:
        from third_party.xhs_collector.xhs_collector.models import CollectorConfig

        legacy = CollectorConfig.from_dict({"top_n": 7})
        staged = CollectorConfig.from_dict(
            {
                "top_n": 7,
                "image_top_n": 10,
                "keyword_top_n": 4,
                "keyword_result_top_n": 5,
            }
        )

        self.assertEqual(legacy.image_top_n, 7)
        self.assertEqual(legacy.keyword_result_top_n, 7)
        self.assertEqual(staged.image_top_n, 10)
        self.assertEqual(staged.keyword_top_n, 4)
        self.assertEqual(staged.keyword_result_top_n, 5)

    def test_deterministic_flow_uses_separate_image_and_keyword_result_counts(
        self,
    ) -> None:
        from third_party.xhs_collector.xhs_collector.deterministic_flow import (
            run_deterministic_item,
        )
        from third_party.xhs_collector.xhs_collector.models import InputItem

        class FakeDevice:
            def __init__(self) -> None:
                self.ui_text = "桌垫 买家秀 实拍"
                self.typed: list[str] = []

            def start_app(self, package: str) -> None:
                pass

            def push_reference_image(
                self, local_path: Path, item_id: str, remote_dir: str
            ) -> str:
                return f"{remote_dir}/{item_id}{local_path.suffix}"

            def dump_hierarchy(self) -> str:
                return self.ui_text

            def click_ratio(self, x: float, y: float) -> None:
                if (x, y) == (0.1, 0.1):
                    self.ui_text = "取消 搜索历史 搜索小红书"
                elif (x, y) == (0.2, 0.2):
                    self.ui_text = "图搜 相册 最近项目"
                elif (x, y) == (0.3, 0.3):
                    self.ui_text = "全部照片 收起 RecyclerView"
                elif (x, y) == (0.4, 0.4):
                    self.ui_text = "输入关于图片的问题 图片分析中"
                elif (x, y) in {(0.25, 0.3), (0.75, 0.3)}:
                    self.ui_text = "笔记详情 评论 说点什么"
                elif (x, y) == (0.5, 0.82) and "保存图片" in self.ui_text:
                    self.ui_text = "已保存"
                elif (x, y) == (0.06, 0.07):
                    self.ui_text = "图搜结果 笔记"
                elif (x, y) == (0.12, 0.08):
                    self.ui_text = "搜索输入框"
                elif (x, y) == (0.88, 0.08):
                    self.ui_text = "AI回答 笔记 搜索结果"

            def set_text(self, text: str) -> None:
                self.typed.append(text)

            def swipe_ratio(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
                duration: float = 0.5,
            ) -> None:
                self.ui_text = "图搜结果 笔记"

            def long_press_ratio(
                self, x: float, y: float, duration: float = 1.0
            ) -> None:
                self.ui_text = "保存图片"

            def screenshot(self) -> bytes:
                return b"png"

        class FakeMediaStore:
            def __init__(self) -> None:
                self.saved = 0

            def snapshot(self) -> list[str]:
                return [
                    f"/sdcard/Pictures/xhs_collector/saved_{rank}.jpg"
                    for rank in range(1, self.saved + 1)
                ]

            def pull(self, remote_path: str, target_path: Path) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(remote_path.encode("utf-8"))
                return target_path

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ref = root / "ref.jpg"
            ref.write_bytes(b"ref")
            item = InputItem(
                item_id="sku",
                keyword="桌垫",
                keyword_candidates=["关键词一", "关键词二"],
                reference_image=ref,
                top_n=99,
            )
            media_store = FakeMediaStore()

            result = run_deterministic_item(
                item=item,
                device=FakeDevice(),
                media_store=media_store,
                profile=self._basic_download_profile(),
                output_item_dir=root / "items" / item.item_id,
                output_dir=root,
                xhs_package="com.xingin.xhs",
                remote_image_dir="/sdcard/Pictures/xhs_collector",
                throttle_seconds=0,
                on_after_save=lambda: setattr(
                    media_store, "saved", media_store.saved + 1
                ),
                save_poll_seconds=0,
                image_top_n=2,
                keyword_top_n=2,
                keyword_result_top_n=1,
                sleep_func=lambda seconds: None,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.collected_count, 4)
            self.assertEqual(
                [image.local_path.name for image in result.images],
                [
                    "rank_001.jpg",
                    "rank_002.jpg",
                    "keyword_001_rank_001.jpg",
                    "keyword_002_rank_001.jpg",
                ],
            )
            self.assertEqual(result.message, "downloaded 4 of 4 image search and keyword results")

    def test_run_cli_accepts_keyword_top_n_override(self) -> None:
        from third_party.xhs_collector.xhs_collector.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            excel_path = root / "items.xlsx"
            ref = root / "ref.jpg"
            ref.write_bytes(b"image")
            _write_xlsx(
                excel_path,
                [
                    ["item_id", "keyword", "image_path"],
                    ["sku", "桌垫", str(ref)],
                ],
            )
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({"output_root": str(root / "runs"), "top_n": 1}),
                encoding="utf-8",
            )

            with mock.patch(
                "third_party.xhs_collector.xhs_collector.cli.run_dry_collect"
            ) as run_dry:
                run_dry.return_value = mock.Mock(
                    status="completed",
                    run_id="run-1",
                    output_dir=root / "runs" / "run-1",
                    results=[],
                )

                exit_code = main(
                    [
                        "run",
                        "--input",
                        str(excel_path),
                        "--config",
                        str(config_path),
                        "--keyword-top-n",
                        "4",
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_dry.call_args.args[3], 4)


if __name__ == "__main__":
    unittest.main()
