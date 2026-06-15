package com.contentos.capture.core

import com.contentos.capture.model.Breakdown
import com.contentos.capture.model.ClientProfile
import com.contentos.capture.model.ContentType
import com.contentos.capture.model.InspirationInputs
import com.contentos.capture.model.InspirationItem
import com.contentos.capture.model.MaterialLevel
import kotlin.math.max
import kotlin.math.min

class MaterialAnalyzer {
    fun buildInspiration(
        id: String,
        client: ClientProfile,
        capturedAtMillis: Long,
        inputs: InspirationInputs,
    ): InspirationItem {
        val level = classify(inputs)
        val missing = missingInputs(level, inputs)
        val confidence = confidenceFor(level, inputs)
        val facts = recognizedFacts(level, inputs, client)
        val suggestions = inferredSuggestions(level, client)
        return InspirationItem(
            id = id,
            client = client,
            capturedAtMillis = capturedAtMillis,
            inputs = inputs,
            materialLevel = level,
            confidence = confidence,
            missingInputs = missing,
            recognizedFacts = facts,
            inferredSuggestions = suggestions,
        )
    }

    fun buildBreakdown(item: InspirationItem): Breakdown {
        val unavailable = mutableListOf<String>()
        if (item.materialLevel == MaterialLevel.L1_SCREENSHOT) {
            unavailable += "无法仅凭单张截图判断完整视频节奏"
            unavailable += "无法仅凭单张截图判断评论区真实反应"
            unavailable += "无法仅凭单张截图判断转化或互动数据"
        }
        if (item.inputs.contentType == ContentType.VIDEO && item.materialLevel != MaterialLevel.L3_RICH_MEDIA) {
            unavailable += "缺少短录屏，暂不分析镜头变化和口播节奏"
        }
        return Breakdown(
            materialLevel = item.materialLevel,
            confidence = item.confidence,
            recognizedFacts = item.recognizedFacts,
            inferredSuggestions = item.inferredSuggestions,
            unavailableClaims = unavailable,
        )
    }

    fun classify(inputs: InspirationInputs): MaterialLevel {
        if (hasRichMedia(inputs)) {
            return MaterialLevel.L3_RICH_MEDIA
        }
        if (
            !inputs.sourceUrl.isNullOrBlank() ||
            !inputs.title.isNullOrBlank() ||
            !inputs.body.isNullOrBlank() ||
            inputs.tags.isNotEmpty() ||
            inputs.commentHints.isNotEmpty()
        ) {
            return MaterialLevel.L2_LINK_TEXT
        }
        return MaterialLevel.L1_SCREENSHOT
    }

    private fun hasRichMedia(inputs: InspirationInputs): Boolean {
        return inputs.originalImagePaths.isNotEmpty() ||
            inputs.keyFramePaths.isNotEmpty() ||
            !inputs.shortRecordingPath.isNullOrBlank() ||
            !inputs.userVideoPath.isNullOrBlank()
    }

    private fun missingInputs(level: MaterialLevel, inputs: InspirationInputs): List<String> {
        val missing = mutableListOf<String>()
        if (inputs.sourceUrl.isNullOrBlank()) missing += "补充链接"
        if (inputs.title.isNullOrBlank()) missing += "补充标题"
        if (inputs.body.isNullOrBlank()) missing += "补充正文"
        when (inputs.contentType) {
            ContentType.IMAGE -> {
                if (inputs.originalImagePaths.isEmpty()) missing += "补充原图/多图"
            }
            ContentType.VIDEO -> {
                if (
                    inputs.keyFramePaths.isEmpty() &&
                    inputs.shortRecordingPath.isNullOrBlank() &&
                    inputs.userVideoPath.isNullOrBlank()
                ) {
                    missing += "补充10-30秒短录屏"
                }
            }
            ContentType.UNKNOWN -> {
                if (inputs.originalImagePaths.isEmpty()) missing += "补充原图/多图"
                if (
                    inputs.keyFramePaths.isEmpty() &&
                    inputs.shortRecordingPath.isNullOrBlank() &&
                    inputs.userVideoPath.isNullOrBlank()
                ) {
                    missing += "补充10-30秒短录屏"
                }
            }
        }
        return when (level) {
            MaterialLevel.L1_SCREENSHOT -> missing
            MaterialLevel.L2_LINK_TEXT -> missing.filter { it != "补充链接" || inputs.sourceUrl.isNullOrBlank() }
            MaterialLevel.L3_RICH_MEDIA -> missing.filter {
                it != "补充原图/多图" && it != "补充10-30秒短录屏"
            }
            MaterialLevel.L4_FULL_REVIEW -> emptyList()
        }
    }

    private fun confidenceFor(level: MaterialLevel, inputs: InspirationInputs): Float {
        val base = when (level) {
            MaterialLevel.L1_SCREENSHOT -> 0.42f
            MaterialLevel.L2_LINK_TEXT -> 0.66f
            MaterialLevel.L3_RICH_MEDIA -> 0.78f
            MaterialLevel.L4_FULL_REVIEW -> 0.9f
        }
        val boost = listOf(
            inputs.sourceUrl,
            inputs.title,
            inputs.body,
            inputs.shortRecordingPath,
            inputs.userVideoPath,
        ).count { !it.isNullOrBlank() } * 0.04f
        val mediaBoost = (inputs.originalImagePaths.size + inputs.keyFramePaths.size).coerceAtMost(3) * 0.03f
        return min(0.92f, max(0.2f, base + boost + mediaBoost))
    }

    private fun recognizedFacts(
        level: MaterialLevel,
        inputs: InspirationInputs,
        client: ClientProfile,
    ): List<String> {
        val facts = mutableListOf(
            "已捕获当前屏幕截图",
            "内容类型：${inputs.contentType.label}",
            "当前客户品类：${client.category}",
        )
        if (!inputs.title.isNullOrBlank()) facts += "已补充标题：${inputs.title}"
        if (!inputs.sourceUrl.isNullOrBlank()) facts += "已补充来源链接"
        if (inputs.tags.isNotEmpty()) facts += "已补充标签：${inputs.tags.joinToString("、")}"
        if (inputs.originalImagePaths.isNotEmpty()) facts += "已补充原图/多图"
        if (inputs.keyFramePaths.isNotEmpty()) facts += "已补充关键帧序列"
        if (!inputs.shortRecordingPath.isNullOrBlank()) facts += "已补充短录屏片段"
        if (!inputs.userVideoPath.isNullOrBlank()) facts += "已补充用户主动提供的视频"
        return facts
    }

    private fun inferredSuggestions(
        level: MaterialLevel,
        client: ClientProfile,
    ): List<String> {
        val suggestions = mutableListOf(
            "可先围绕${client.category}做视觉场景和封面表达转译",
            "脚本应体现${client.persona}",
        )
        if (level == MaterialLevel.L1_SCREENSHOT) {
            suggestions += when (client.category) {
                else -> "当前只输出初步脚本草稿，建议补充链接、标题或富媒体素材提升质量"
            }
        } else {
            suggestions += "可结合文本线索强化卖点、情绪和内容结构"
        }
        if (level == MaterialLevel.L3_RICH_MEDIA) {
            suggestions += "可进一步加入构图、材质、前三秒或镜头节奏建议"
        }
        return suggestions
    }
}
