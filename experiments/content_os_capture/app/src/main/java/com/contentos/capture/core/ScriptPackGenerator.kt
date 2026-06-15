package com.contentos.capture.core

import com.contentos.capture.model.Breakdown
import com.contentos.capture.model.ClientProfile
import com.contentos.capture.model.ContentType
import com.contentos.capture.model.InspirationItem
import com.contentos.capture.model.MaterialLevel
import com.contentos.capture.model.ScriptPack
import com.contentos.capture.model.ScriptVariant

class ScriptPackGenerator {
    fun generate(
        item: InspirationItem,
        breakdown: Breakdown,
    ): ScriptPack {
        val qualityLabel = when (item.materialLevel) {
            MaterialLevel.L1_SCREENSHOT -> "初步脚本草稿"
            MaterialLevel.L2_LINK_TEXT -> "图文强化包"
            MaterialLevel.L3_RICH_MEDIA -> "富媒体强化包"
            MaterialLevel.L4_FULL_REVIEW -> "复盘级脚本包"
        }
        return ScriptPack(
            title = "${item.client.name} · ${qualityLabel}",
            materialLevel = item.materialLevel,
            confidence = breakdown.confidence,
            qualityLabel = qualityLabel,
            missingInputs = item.missingInputs,
            scripts = listOf(
                buildVariant("场景种草版", item.client, item.materialLevel, item.inputs.contentType),
                buildVariant("问题解决版", item.client, item.materialLevel, item.inputs.contentType),
                buildVariant("清单收藏版", item.client, item.materialLevel, item.inputs.contentType),
            ),
        )
    }

    private fun buildVariant(
        name: String,
        client: ClientProfile,
        level: MaterialLevel,
        contentType: ContentType,
    ): ScriptVariant {
        val caution = when (level) {
            MaterialLevel.L1_SCREENSHOT -> "基于截图可见信息，先做原创转译，不判断原视频完整节奏。"
            MaterialLevel.L2_LINK_TEXT -> "结合补充文本线索，强化内容结构和卖点表达。"
            MaterialLevel.L3_RICH_MEDIA -> when (contentType) {
                ContentType.IMAGE -> "结合原图/多图，强化构图、材质、细节和场景表达。"
                ContentType.VIDEO -> "结合用户提供的视频片段/关键帧，强化前三秒、镜头节奏和字幕/口播结构。"
                ContentType.UNKNOWN -> "结合富媒体材料，强化视觉细节、内容节奏和执行信息。"
            }
            MaterialLevel.L4_FULL_REVIEW -> "结合完整复盘数据，强化结构选择和发布策略。"
        }
        return ScriptVariant(
            name = name,
            title = "${client.category}｜$name",
            firstThreeSeconds = "先展示一个真实居家场景痛点，再切到解决后的空间质感。",
            storyboard = listOf(
                "镜头1：展示桌面或家居空间的原始状态",
                "镜头2：放入核心产品或布置元素，突出变化",
                "镜头3：近景展示材质、清洁或搭配细节",
                "镜头4：回到整体空间，给出收藏/评论引导",
            ),
            voiceover = "$caution 用${client.persona}的语气说明这个布置为什么实用、好看、容易复刻。",
            coverText = "这个家居细节，真的能改变空间质感",
            shootingChecklist = listOf(
                "自然光桌面或客厅场景",
                "产品近景和整体前后对比",
                "一段手部整理或清洁动作",
                "封面截图候选2张",
            ),
            publishCopy = "把一个小细节做好，整个空间会显得更干净、更有秩序。你家最想先改哪里？",
        )
    }
}
