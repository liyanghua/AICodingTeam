#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

required_files=(
  "$root/settings.gradle.kts"
  "$root/build.gradle.kts"
  "$root/app/build.gradle.kts"
  "$root/app/src/main/AndroidManifest.xml"
  "$root/app/src/main/java/com/contentos/capture/MainActivity.kt"
  "$root/app/src/main/java/com/contentos/capture/CaptureOverlayService.kt"
  "$root/app/src/main/java/com/contentos/capture/ScreenCaptureService.kt"
  "$root/app/src/main/java/com/contentos/capture/core/MaterialAnalyzer.kt"
  "$root/app/src/main/java/com/contentos/capture/core/ScriptPackGenerator.kt"
  "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
  "$root/app/src/test/java/com/contentos/capture/MaterialAnalyzerTest.kt"
)

for file in "${required_files[@]}"; do
  test -f "$file"
done

grep -q "L1_SCREENSHOT" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "L2_LINK_TEXT" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "L3_RICH_MEDIA" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "enum class ContentType" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "originalImagePaths" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "userVideoPath" "$root/app/src/main/java/com/contentos/capture/model/ContentModels.kt"
grep -q "无法仅凭单张截图判断完整视频节奏" "$root/app/src/main/java/com/contentos/capture/core/MaterialAnalyzer.kt"
grep -q "无法仅凭单张截图判断评论区真实反应" "$root/app/src/main/java/com/contentos/capture/core/MaterialAnalyzer.kt"
grep -q "初步脚本草稿" "$root/app/src/main/java/com/contentos/capture/core/ScriptPackGenerator.kt"
grep -q "图文强化包" "$root/app/src/main/java/com/contentos/capture/core/ScriptPackGenerator.kt"
grep -q "富媒体强化包" "$root/app/src/main/java/com/contentos/capture/core/ScriptPackGenerator.kt"
grep -q "视频原文件仅支持用户主动上传/分享，不自动抓取" "$root/app/src/main/java/com/contentos/capture/MainActivity.kt"
grep -q "SYSTEM_ALERT_WINDOW" "$root/app/src/main/AndroidManifest.xml"
grep -q "FOREGROUND_SERVICE_MEDIA_PROJECTION" "$root/app/src/main/AndroidManifest.xml"

echo "content_os_capture static verification passed"
