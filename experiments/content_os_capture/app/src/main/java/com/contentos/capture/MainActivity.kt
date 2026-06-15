package com.contentos.capture

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.contentos.capture.core.MaterialAnalyzer
import com.contentos.capture.core.ScriptPackGenerator
import com.contentos.capture.model.ClientProfile
import com.contentos.capture.model.ContentType
import com.contentos.capture.model.InspirationInputs
import com.contentos.capture.model.InspirationItem
import com.contentos.capture.model.ScriptPack

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    CapturePrototypeApp(
                        onStartCapture = { startCaptureFlow() },
                        initialSharedText = intent?.getStringExtra(Intent.EXTRA_TEXT).orEmpty(),
                    )
                }
            }
        }
    }

    private fun startCaptureFlow() {
        if (!Settings.canDrawOverlays(this)) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"),
            )
            startActivity(intent)
            return
        }
        startService(Intent(this, CaptureOverlayService::class.java))
        setResult(Activity.RESULT_OK)
    }
}

@Composable
fun CapturePrototypeApp(
    onStartCapture: () -> Unit,
    initialSharedText: String,
) {
    val analyzer = remember { MaterialAnalyzer() }
    val generator = remember { ScriptPackGenerator() }
    val client = remember { ClientProfile(id = "home-a", name = "家居客户A") }
    val inspirations = remember { mutableStateListOf<InspirationItem>() }
    var selectedPack by remember { mutableStateOf<ScriptPack?>(null) }
    var note by remember { mutableStateOf(initialSharedText) }
    var contentType by remember { mutableStateOf(ContentType.UNKNOWN) }
    var includeOriginalImages by remember { mutableStateOf(false) }
    var includeShortRecording by remember { mutableStateOf(false) }
    var includeUserVideo by remember { mutableStateOf(false) }
    var includeKeyFrames by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF7F8FA))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Content OS 灵感采集", style = MaterialTheme.typography.headlineSmall)
        Text("独立离线原型：验证截图级灵感卡、材料完整度和脚本执行包。")

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("当前客户：${client.name}", fontWeight = FontWeight.Bold)
                Text("品类：${client.category}")
                Text("内容类型")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ContentTypeButton("图片", contentType == ContentType.IMAGE) {
                        contentType = ContentType.IMAGE
                        includeShortRecording = false
                        includeUserVideo = false
                        includeKeyFrames = false
                    }
                    ContentTypeButton("视频", contentType == ContentType.VIDEO) {
                        contentType = ContentType.VIDEO
                        includeOriginalImages = false
                    }
                    ContentTypeButton("未知", contentType == ContentType.UNKNOWN) {
                        contentType = ContentType.UNKNOWN
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onStartCapture) {
                        Text("开启灵感采集")
                    }
                    Button(
                        onClick = {
                            val item = analyzer.buildInspiration(
                                id = "capture-${inspirations.size + 1}",
                                client = client,
                                capturedAtMillis = System.currentTimeMillis(),
                                inputs = InspirationInputs(
                                    contentType = contentType,
                                    screenshotPath = "/mock/current-screen.png",
                                    sourceUrl = note.takeIf { it.startsWith("http") },
                                    title = note.takeIf { it.isNotBlank() && !it.startsWith("http") },
                                    originalImagePaths = if (includeOriginalImages) {
                                        listOf("/mock/original-1.jpg", "/mock/original-2.jpg")
                                    } else {
                                        emptyList()
                                    },
                                    shortRecordingPath = if (includeShortRecording) "/mock/clip.mp4" else null,
                                    userVideoPath = if (includeUserVideo) "/mock/user-video.mp4" else null,
                                    keyFramePaths = if (includeKeyFrames) {
                                        listOf("/mock/frame-1.jpg", "/mock/frame-2.jpg")
                                    } else {
                                        emptyList()
                                    },
                                ),
                            )
                            inspirations.add(0, item)
                        },
                    ) {
                        Text("模拟收藏截图")
                    }
                }
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("可选：补充链接或标题") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { includeOriginalImages = !includeOriginalImages }) {
                        Text(if (includeOriginalImages) "已补原图/多图" else "补原图/多图")
                    }
                    TextButton(onClick = { includeShortRecording = !includeShortRecording }) {
                        Text(if (includeShortRecording) "已补短录屏" else "补短录屏")
                    }
                    TextButton(onClick = { includeKeyFrames = !includeKeyFrames }) {
                        Text(if (includeKeyFrames) "已补关键帧" else "补关键帧")
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { includeUserVideo = !includeUserVideo }) {
                        Text(if (includeUserVideo) "已补用户视频" else "补用户视频")
                    }
                    TextButton(
                        onClick = {
                            includeOriginalImages = false
                            includeShortRecording = false
                            includeKeyFrames = false
                            includeUserVideo = false
                            note = ""
                        },
                    ) {
                        Text("清空补充材料")
                    }
                }
                Text("视频原文件仅支持用户主动上传/分享，不自动抓取。")
            }
        }

        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(inspirations) { item ->
                InspirationCard(
                    item = item,
                    onGenerate = {
                        selectedPack = generator.generate(item, analyzer.buildBreakdown(item))
                    },
                )
            }
        }

        selectedPack?.let { pack ->
            ScriptPackCard(pack = pack)
        }
    }
}

@Composable
private fun ContentTypeButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    if (selected) {
        Button(onClick = onClick) { Text(label) }
    } else {
        TextButton(onClick = onClick) { Text(label) }
    }
}

@Composable
private fun InspirationCard(
    item: InspirationItem,
    onGenerate: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("内容类型：${item.inputs.contentType.label}")
                    Text(item.materialLevel.label, fontWeight = FontWeight.Bold)
                    Text("置信度 ${(item.confidence * 100).toInt()}%")
                }
                Button(onClick = onGenerate) {
                    Text("生成脚本包")
                }
            }
            Text(item.materialLevel.promise)
            Text("缺失材料：${item.missingInputs.joinToString("、").ifBlank { "无" }}")
            Text("升级建议：${upgradeHint(item.inputs.contentType)}")
            Text("已识别事实：${item.recognizedFacts.joinToString("；")}")
            Text("推测建议：${item.inferredSuggestions.joinToString("；")}")
        }
    }
}

private fun upgradeHint(contentType: ContentType): String {
    return when (contentType) {
        ContentType.IMAGE -> "可补充原图/多图，提升视觉拆解质量"
        ContentType.VIDEO -> "可补充10-30秒短录屏，升级节奏拆解"
        ContentType.UNKNOWN -> "可补充原图/多图或短录屏，提升拆解质量"
    }
}

@Composable
private fun ScriptPackCard(pack: ScriptPack) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(pack.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("${pack.qualityLabel} · 置信度 ${(pack.confidence * 100).toInt()}%")
            Text("补充建议：${pack.missingInputs.joinToString("、").ifBlank { "当前材料足够" }}")
            pack.scripts.forEach { script ->
                Spacer(modifier = Modifier.height(6.dp))
                Text(script.name, fontWeight = FontWeight.Bold)
                Text("标题：${script.title}")
                Text("前三秒：${script.firstThreeSeconds}")
                Text("拍摄清单：${script.shootingChecklist.joinToString("、")}")
            }
        }
    }
}
