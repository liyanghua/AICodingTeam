from __future__ import annotations

from pathlib import Path


class DryRunTaobaoDevice:
    def __init__(self) -> None:
        self.state = "home"
        self.actions: list[dict] = []

    def current_package(self) -> str:
        return "com.taobao.taobao"

    def start_app(self, package: str) -> None:
        self.actions.append({"action": "start_app", "package": package})
        self.state = "home"

    def dump_hierarchy(self) -> str:
        markers = {
            "home": "淘宝 搜索 拍照",
            "search_page": "搜索 取消 输入商品",
            "album": "相册 全部照片 最近项目",
            "album_confirm": "预览 确定",
            "results": "综合 销量 店铺 商品",
            "detail": "宝贝详情 评价 店铺 加入购物车 立即购买",
            "save_menu": "保存图片 保存到相册 取消",
        }
        return markers.get(self.state, self.state)

    def tap_profile_point(self, name: str, _point: tuple[float, float]) -> None:
        self.actions.append({"action": "tap", "point": name})
        if name == "home_search_box":
            self.state = "search_page"
        elif name == "image_search_button":
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

    def long_press_profile_point(
        self, name: str, _point: tuple[float, float], duration: float = 1.0
    ) -> None:
        self.actions.append({"action": "long_press", "point": name, "duration": duration})
        if name == "detail_main_image":
            self.state = "save_menu"

    def swipe_profile_points(
        self,
        name: str,
        _start: tuple[float, float],
        _end: tuple[float, float],
        duration: float = 0.3,
    ) -> None:
        self.actions.append({"action": "swipe", "point": name, "duration": duration})

    def set_text(self, text: str) -> None:
        self.actions.append({"action": "set_text", "text": text})

    def press_enter(self) -> None:
        self.actions.append({"action": "press_enter"})
        self.state = "results"

    def press_back(self) -> None:
        self.actions.append({"action": "press_back"})
        self.state = "home"

    def save_screenshot(self, path: Path) -> None:
        self.actions.append({"action": "screenshot", "path": str(path)})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"dry-run-taobao-{path.name}".encode("utf-8"))

    def push_reference_image(self, local_path: Path, item_id: str, remote_dir: str) -> str:
        self.actions.append(
            {
                "action": "push_reference_image",
                "local_path": str(local_path),
                "item_id": item_id,
            }
        )
        return f"{remote_dir}/{item_id}{local_path.suffix or '.jpg'}"
