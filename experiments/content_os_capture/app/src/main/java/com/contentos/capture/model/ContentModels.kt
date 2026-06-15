package com.contentos.capture.model

enum class MaterialLevel(
    val label: String,
    val promise: String,
) {
    L1_SCREENSHOT(
        label = "截图级",
        promise = "基于截图生成初步拆解和脚本草稿",
    ),
    L2_LINK_TEXT(
        label = "链接/正文级",
        promise = "补充文本线索后生成图文强化包",
    ),
    L3_RICH_MEDIA(
        label = "富媒体级",
        promise = "补充原图/多图、短录屏、关键帧或用户视频后生成富媒体强化包",
    ),
    L4_FULL_REVIEW(
        label = "完整复盘级",
        promise = "需要完整互动数据；V1 不支持",
    ),
}

enum class ContentType(
    val label: String,
) {
    IMAGE("图片"),
    VIDEO("视频"),
    UNKNOWN("未知"),
}

data class ClientProfile(
    val id: String,
    val name: String,
    val category: String = "家居/生活方式",
    val audience: String = "关注居家质感和实用搭配的人群",
    val persona: String = "克制、可信、实用的生活方式顾问",
    val sellingPoints: List<String> = listOf("提升空间质感", "好清洁", "适合日常拍摄"),
    val forbiddenClaims: List<String> = listOf("夸大功效", "照搬原文案"),
)

data class InspirationInputs(
    val contentType: ContentType = ContentType.UNKNOWN,
    val screenshotPath: String?,
    val sourceUrl: String? = null,
    val title: String? = null,
    val body: String? = null,
    val tags: List<String> = emptyList(),
    val commentHints: List<String> = emptyList(),
    val originalImagePaths: List<String> = emptyList(),
    val keyFramePaths: List<String> = emptyList(),
    val shortRecordingPath: String? = null,
    val userVideoPath: String? = null,
)

data class InspirationItem(
    val id: String,
    val client: ClientProfile,
    val capturedAtMillis: Long,
    val inputs: InspirationInputs,
    val materialLevel: MaterialLevel,
    val confidence: Float,
    val missingInputs: List<String>,
    val recognizedFacts: List<String>,
    val inferredSuggestions: List<String>,
)

data class Breakdown(
    val materialLevel: MaterialLevel,
    val confidence: Float,
    val recognizedFacts: List<String>,
    val inferredSuggestions: List<String>,
    val unavailableClaims: List<String>,
)

data class ScriptPack(
    val title: String,
    val materialLevel: MaterialLevel,
    val confidence: Float,
    val qualityLabel: String,
    val missingInputs: List<String>,
    val scripts: List<ScriptVariant>,
)

data class ScriptVariant(
    val name: String,
    val title: String,
    val firstThreeSeconds: String,
    val storyboard: List<String>,
    val voiceover: String,
    val coverText: String,
    val shootingChecklist: List<String>,
    val publishCopy: String,
)
