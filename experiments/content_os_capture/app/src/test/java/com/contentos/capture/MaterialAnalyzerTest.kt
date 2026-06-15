package com.contentos.capture

import com.contentos.capture.core.MaterialAnalyzer
import com.contentos.capture.core.ScriptPackGenerator
import com.contentos.capture.model.ClientProfile
import com.contentos.capture.model.ContentType
import com.contentos.capture.model.InspirationInputs
import com.contentos.capture.model.MaterialLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MaterialAnalyzerTest {
    private val analyzer = MaterialAnalyzer()
    private val client = ClientProfile(id = "home-a", name = "家居客户A")

    @Test
    fun screenshotOnlyCreatesL1WithMissingInputsAndDraftScriptPack() {
        val item = analyzer.buildInspiration(
            id = "capture-1",
            client = client,
            capturedAtMillis = 1L,
            inputs = InspirationInputs(screenshotPath = "/private/capture.png"),
        )
        val breakdown = analyzer.buildBreakdown(item)
        val pack = ScriptPackGenerator().generate(item, breakdown)

        assertEquals(MaterialLevel.L1_SCREENSHOT, item.materialLevel)
        assertTrue(item.missingInputs.contains("补充链接"))
        assertTrue(item.missingInputs.contains("补充标题"))
        assertTrue(item.missingInputs.contains("补充10-30秒短录屏"))
        assertEquals("初步脚本草稿", pack.qualityLabel)
        assertEquals(3, pack.scripts.size)
    }

    @Test
    fun supplementingTitleOrLinkUpgradesToL2() {
        val item = analyzer.buildInspiration(
            id = "capture-2",
            client = client,
            capturedAtMillis = 2L,
            inputs = InspirationInputs(
                screenshotPath = "/private/capture.png",
                sourceUrl = "https://www.xiaohongshu.com/example",
                title = "小户型餐桌这样布置",
            ),
        )

        assertEquals(MaterialLevel.L2_LINK_TEXT, item.materialLevel)
        assertFalse(item.missingInputs.contains("补充链接"))
        assertFalse(item.missingInputs.contains("补充标题"))
        assertTrue(item.confidence > 0.66f)
    }

    @Test
    fun shortRecordingUpgradesToRichMediaLevel() {
        val item = analyzer.buildInspiration(
            id = "capture-3",
            client = client,
            capturedAtMillis = 3L,
            inputs = InspirationInputs(
                contentType = ContentType.VIDEO,
                screenshotPath = "/private/capture.png",
                shortRecordingPath = "/private/clip.mp4",
            ),
        )

        assertEquals(MaterialLevel.L3_RICH_MEDIA, item.materialLevel)
        assertFalse(item.missingInputs.contains("补充10-30秒短录屏"))
    }

    @Test
    fun screenshotLevelDoesNotClaimUnavailableVideoOrCommentFacts() {
        val item = analyzer.buildInspiration(
            id = "capture-4",
            client = client,
            capturedAtMillis = 4L,
            inputs = InspirationInputs(screenshotPath = "/private/capture.png"),
        )
        val breakdown = analyzer.buildBreakdown(item)
        val allGeneratedText = (
            breakdown.recognizedFacts +
                breakdown.inferredSuggestions
            ).joinToString(" ")

        assertFalse(allGeneratedText.contains("评论区真实反应"))
        assertFalse(allGeneratedText.contains("完整视频节奏"))
        assertTrue(breakdown.unavailableClaims.any { it.contains("完整视频节奏") })
        assertTrue(breakdown.unavailableClaims.any { it.contains("评论区真实反应") })
    }

    @Test
    fun imageScreenshotSuggestsOriginalImagesAndOriginalImagesUpgradeToL3() {
        val screenshotOnly = analyzer.buildInspiration(
            id = "capture-image-1",
            client = client,
            capturedAtMillis = 5L,
            inputs = InspirationInputs(
                contentType = ContentType.IMAGE,
                screenshotPath = "/private/capture.png",
            ),
        )
        val richImage = analyzer.buildInspiration(
            id = "capture-image-2",
            client = client,
            capturedAtMillis = 6L,
            inputs = InspirationInputs(
                contentType = ContentType.IMAGE,
                screenshotPath = "/private/capture.png",
                originalImagePaths = listOf("/private/original-1.jpg", "/private/original-2.jpg"),
            ),
        )

        assertEquals(MaterialLevel.L1_SCREENSHOT, screenshotOnly.materialLevel)
        assertTrue(screenshotOnly.missingInputs.contains("补充原图/多图"))
        assertEquals(MaterialLevel.L3_RICH_MEDIA, richImage.materialLevel)
        assertFalse(richImage.missingInputs.contains("补充原图/多图"))
    }

    @Test
    fun videoScreenshotSuggestsShortRecordingAndDoesNotClaimPaceUntilRichMedia() {
        val videoScreenshot = analyzer.buildInspiration(
            id = "capture-video-1",
            client = client,
            capturedAtMillis = 7L,
            inputs = InspirationInputs(
                contentType = ContentType.VIDEO,
                screenshotPath = "/private/capture.png",
                title = "厨房改造前三秒",
            ),
        )
        val videoBreakdown = analyzer.buildBreakdown(videoScreenshot)
        val richVideo = analyzer.buildInspiration(
            id = "capture-video-2",
            client = client,
            capturedAtMillis = 8L,
            inputs = InspirationInputs(
                contentType = ContentType.VIDEO,
                screenshotPath = "/private/capture.png",
                keyFramePaths = listOf("/private/frame-1.jpg", "/private/frame-2.jpg"),
            ),
        )

        assertEquals(MaterialLevel.L2_LINK_TEXT, videoScreenshot.materialLevel)
        assertTrue(videoScreenshot.missingInputs.contains("补充10-30秒短录屏"))
        assertTrue(videoBreakdown.unavailableClaims.any { it.contains("镜头变化") })
        assertEquals(MaterialLevel.L3_RICH_MEDIA, richVideo.materialLevel)
    }

    @Test
    fun richMediaScriptPackUsesMediaSpecificExecutionLanguage() {
        val imageItem = analyzer.buildInspiration(
            id = "capture-image-3",
            client = client,
            capturedAtMillis = 9L,
            inputs = InspirationInputs(
                contentType = ContentType.IMAGE,
                screenshotPath = "/private/capture.png",
                originalImagePaths = listOf("/private/original.jpg"),
            ),
        )
        val videoItem = analyzer.buildInspiration(
            id = "capture-video-3",
            client = client,
            capturedAtMillis = 10L,
            inputs = InspirationInputs(
                contentType = ContentType.VIDEO,
                screenshotPath = "/private/capture.png",
                userVideoPath = "/private/user-video.mp4",
            ),
        )
        val generator = ScriptPackGenerator()
        val imagePack = generator.generate(imageItem, analyzer.buildBreakdown(imageItem))
        val videoPack = generator.generate(videoItem, analyzer.buildBreakdown(videoItem))

        assertEquals("富媒体强化包", imagePack.qualityLabel)
        assertTrue(imagePack.scripts.first().voiceover.contains("构图"))
        assertTrue(imagePack.scripts.first().voiceover.contains("材质"))
        assertEquals("富媒体强化包", videoPack.qualityLabel)
        assertTrue(videoPack.scripts.first().voiceover.contains("前三秒"))
        assertTrue(videoPack.scripts.first().voiceover.contains("镜头节奏"))
    }
}
