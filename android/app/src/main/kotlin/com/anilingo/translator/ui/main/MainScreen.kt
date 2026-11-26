package com.anilingo.translator.ui.main

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.anilingo.translator.engine.MobileTranslator
import com.anilingo.translator.model.AppStateBus
import com.anilingo.translator.model.MOBILE_LYRICS_PRESETS
import kotlinx.coroutines.launch

@Composable
fun AniLingoMainScreen(
    onToggleOverlay: () -> Unit,
    onPickRegion: () -> Unit,
    onToggleLiveScreen: () -> Unit,
    onStartSnip: () -> Unit,
    onToggleAudio: () -> Unit,
) {
    var selectedTab by remember { mutableIntStateOf(0) }
    val statusText by AppStateBus.statusText.collectAsState()

    val bgDark = Color(0xFF121521)
    val cardBg = Color(0xFF1B2032)
    val accentPink = Color(0xFFE05297)

    Scaffold(
        containerColor = bgDark,
        topBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color(0xFF171B2A))
                    .padding(top = 38.dp, start = 16.dp, end = 16.dp, bottom = 8.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "🌸 番译姬 AniLingo",
                        color = Color(0xFFFFB8D9),
                        fontSize = 20.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(
                        text = "手机悬浮歌词实时看番翻译",
                        color = Color(0xFF9AA6C4),
                        fontSize = 12.sp
                    )
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    text = statusText,
                    color = Color(0xFF8CE4FF),
                    fontSize = 12.sp
                )
                Spacer(Modifier.height(8.dp))
                TabRow(
                    selectedTabIndex = selectedTab,
                    containerColor = Color(0xFF171B2A),
                    contentColor = Color(0xFFFFB8D9)
                ) {
                    listOf("🎬 翻译台", "🎨 歌词样式", "📖 改词/词表", "⚙️ 引擎联动").forEachIndexed { idx, title ->
                        Tab(
                            selected = selectedTab == idx,
                            onClick = { selectedTab = idx },
                            text = { Text(title, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold) }
                        )
                    }
                }
            }
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(14.dp)
        ) {
            when (selectedTab) {
                0 -> DashboardTab(
                    cardBg = cardBg,
                    accentPink = accentPink,
                    onToggleOverlay = onToggleOverlay,
                    onPickRegion = onPickRegion,
                    onToggleLiveScreen = onToggleLiveScreen,
                    onStartSnip = onStartSnip,
                    onToggleAudio = onToggleAudio,
                )
                1 -> LyricsStyleTab(cardBg = cardBg)
                2 -> EditAndGlossaryTab(cardBg = cardBg, accentPink = accentPink)
                3 -> EngineSettingsTab(cardBg = cardBg, accentPink = accentPink)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DashboardTab(
    cardBg: Color,
    accentPink: Color,
    onToggleOverlay: () -> Unit,
    onPickRegion: () -> Unit,
    onToggleLiveScreen: () -> Unit,
    onStartSnip: () -> Unit,
    onToggleAudio: () -> Unit,
) {
    val ctx = LocalContext.current
    val overlayRunning by AppStateBus.overlayRunning.collectAsState()
    val liveScreen by AppStateBus.liveScreenActive.collectAsState()
    val liveAudio by AppStateBus.liveAudioActive.collectAsState()
    val engineCfg by AppStateBus.engineConfig.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Master Floating Window Switch Card
        Card(
            colors = CardDefaults.cardColors(containerColor = cardBg),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("🎵 第一步：开启全局音乐歌词级悬浮字幕窗", color = Color(0xFFFFD2E8), fontWeight = FontWeight.Bold)
                Text(
                    "开启后可切换到 B站、MX Player、浏览器等任意看番软件上方悬浮显示；轻触悬浮字幕即弹出迷你操作栏，支持拖拽、换肤、改词与触摸穿透锁定。",
                    color = Color(0xFFB5C0DA),
                    fontSize = 12.5.sp
                )
                Button(
                    onClick = onToggleOverlay,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (overlayRunning) Color(0xFFD97706) else accentPink
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        if (overlayRunning) "⏹️ 关闭全局悬浮歌词窗" else "🚀 开启全局悬浮歌词窗",
                        fontWeight = FontWeight.Bold
                    )
                }

                // Source language selector
                Text("源语言选择：", color = Color(0xFFD6DFF5), fontSize = 12.5.sp)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("ja" to "日语(生肉/日字)", "en" to "英语(英字)", "ko" to "韩语", "auto" to "自动识别").forEach { (code, label) ->
                        FilterChip(
                            selected = engineCfg.sourceLang == code,
                            onClick = {
                                AppStateBus.updateEngineConfig(ctx) { it.copy(sourceLang = code) }
                                MobileTranslator.clearCache()
                            },
                            label = { Text(label, fontSize = 12.sp) }
                        )
                    }
                }
            }
        }

        // Screen Region & One-Shot Snip Card
        Card(
            colors = CardDefaults.cardColors(containerColor = cardBg),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("📺 屏幕实时区域抓词 & 框选截屏翻译", color = Color(0xFF8CE4FF), fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(onClick = onPickRegion, modifier = Modifier.weight(1f)) {
                        Text("🖱️ 框选字幕区")
                    }
                    Button(
                        onClick = onToggleLiveScreen,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (liveScreen) Color(0xFFD97706) else Color(0xFF1F7A99)
                        ),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(if (liveScreen) "⏹️ 停止盯屏" else "▶️ 实时盯屏")
                    }
                }
                Button(
                    onClick = onStartSnip,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF39466E)),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("✂️ 立即手指框选截屏翻译（任意画面/气泡/标题）")
                }
            }
        }

        // Voice & Internal Audio Translation Card
        Card(
            colors = CardDefaults.cardColors(containerColor = cardBg),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("🎧 声音实时听译（说话麦克风 / 手机内部播放声音）", color = Color(0xFF9EFFD6), fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = engineCfg.audioSource == "mic",
                        onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(audioSource = "mic") } },
                        label = { Text("🎙️ 麦克风说话/外放声音") }
                    )
                    FilterChip(
                        selected = engineCfg.audioSource == "internal",
                        onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(audioSource = "internal") } },
                        label = { Text("🔊 手机系统内录(Android 10+)") }
                    )
                }
                Button(
                    onClick = onToggleAudio,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (liveAudio) Color(0xFFD97706) else accentPink
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(if (liveAudio) "⏹️ 停止声音实时听译" else "🎙️ 开始声音实时翻译")
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LyricsStyleTab(cardBg: Color) {
    val ctx = LocalContext.current
    val st by AppStateBus.style.collectAsState()
    val curOrig by AppStateBus.currentOriginal.collectAsState()
    val curTrans by AppStateBus.currentTranslated.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Live Style Preview Box
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Brush.horizontalGradient(listOf(Color(0xFF231934), Color(0xFF14293A))))
                .border(1.dp, Color(0x55FFB8D9), RoundedCornerShape(16.dp))
                .padding(18.dp),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = curTrans,
                    color = Color(st.colorBottom),
                    fontSize = st.baseFontSp.sp,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center
                )
                if (st.bilingual && curOrig.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = curOrig,
                        color = Color(st.origColor),
                        fontSize = (st.baseFontSp * 0.58f).sp,
                        textAlign = TextAlign.Center
                    )
                }
            }
        }

        Card(colors = CardDefaults.cardColors(containerColor = cardBg), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("🎨 听歌桌面歌词级主题预设", color = Color(0xFFFFD2E8), fontWeight = FontWeight.Bold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    MOBILE_LYRICS_PRESETS.forEach { preset ->
                        FilterChip(
                            selected = st.presetKey == preset.key,
                            onClick = { AppStateBus.applyPreset(ctx, preset) },
                            label = { Text(preset.title, fontSize = 12.sp) }
                        )
                    }
                }

                Text("基准字幕大小：${st.baseFontSp.toInt()} sp", color = Color.White, fontSize = 13.sp)
                Slider(
                    value = st.baseFontSp,
                    onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(baseFontSp = v) } },
                    valueRange = 14f..36f
                )

                Text("描边粗细：${"%.1f".format(st.strokeWidthDp)} dp", color = Color.White, fontSize = 13.sp)
                Slider(
                    value = st.strokeWidthDp,
                    onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(strokeWidthDp = v) } },
                    valueRange = 0f..6f
                )

                Text(
                    text = if (st.bgAlpha == 0) "底板透明度：0%（全透明不突兀）" else "底板透明度：${(st.bgAlpha * 100 / 255)}% 柔光胶囊",
                    color = Color.White,
                    fontSize = 13.sp
                )
                Slider(
                    value = st.bgAlpha.toFloat(),
                    onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(bgAlpha = v.toInt()) } },
                    valueRange = 0f..210f
                )

                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Text("长句字号智能自适应缩放", color = Color.White, modifier = Modifier.weight(1f))
                    Switch(
                        checked = st.autoScaleFont,
                        onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(autoScaleFont = c) } }
                    )
                }

                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Text("双语歌词对照显示（译文+原文）", color = Color.White, modifier = Modifier.weight(1f))
                    Switch(
                        checked = st.bilingual,
                        onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(bilingual = c) } }
                    )
                }
            }
        }
    }
}

@Composable
private fun EditAndGlossaryTab(cardBg: Color, accentPink: Color) {
    val ctx = LocalContext.current
    val curOrig by AppStateBus.currentOriginal.collectAsState()
    val curTrans by AppStateBus.currentTranslated.collectAsState()
    val glossary by AppStateBus.glossary.collectAsState()

    var editTrans by remember(curTrans) { mutableStateOf(curTrans) }
    var newSrc by remember { mutableStateOf("") }
    var newDst by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Card(colors = CardDefaults.cardColors(containerColor = cardBg), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("✏️ 直接修改当前悬浮字幕文字", color = Color(0xFFFFD2E8), fontWeight = FontWeight.Bold)
                OutlinedTextField(
                    value = editTrans,
                    onValueChange = { editTrans = it },
                    label = { Text("当前中文译文") },
                    modifier = Modifier.fillMaxWidth()
                )
                Button(
                    onClick = { AppStateBus.editCurrentSubtitle(curOrig, editTrans) },
                    colors = ButtonDefaults.buttonColors(containerColor = accentPink),
                    modifier = Modifier.align(Alignment.End)
                ) {
                    Text("立即更新到悬浮歌词")
                }
            }
        }

        Card(colors = CardDefaults.cardColors(containerColor = cardBg), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("📖 番剧专属人名 / 术语记忆表", color = Color(0xFF8CE4FF), fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = newSrc,
                        onValueChange = { newSrc = it },
                        label = { Text("外语原词") },
                        modifier = Modifier.weight(1f)
                    )
                    OutlinedTextField(
                        value = newDst,
                        onValueChange = { newDst = it },
                        label = { Text("指定译名") },
                        modifier = Modifier.weight(1f)
                    )
                }
                Button(
                    onClick = {
                        if (newSrc.isNotBlank() && newDst.isNotBlank()) {
                            AppStateBus.putGlossaryTerm(ctx, newSrc, newDst)
                            MobileTranslator.clearCache()
                            newSrc = ""
                            newDst = ""
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = accentPink),
                    modifier = Modifier.align(Alignment.End)
                ) {
                    Text("➕ 添加术语记忆")
                }

                glossary.entries.forEach { (k, v) ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF131726), RoundedCornerShape(8.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("$k  ➔  $v", color = Color.White, modifier = Modifier.weight(1f), fontSize = 13.sp)
                        Text(
                            text = "删除",
                            color = Color(0xFFFF7B9C),
                            fontSize = 12.sp,
                            modifier = Modifier.clickable {
                                AppStateBus.removeGlossaryTerm(ctx, k)
                                MobileTranslator.clearCache()
                            }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun EngineSettingsTab(cardBg: Color, accentPink: Color) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val cfg by AppStateBus.engineConfig.collectAsState()

    var apiBase by remember(cfg.llmApiBase) { mutableStateOf(cfg.llmApiBase) }
    var apiKey by remember(cfg.llmApiKey) { mutableStateOf(cfg.llmApiKey) }
    var modelName by remember(cfg.llmModel) { mutableStateOf(cfg.llmModel) }
    var pcLan by remember(cfg.pcLanUrl) { mutableStateOf(cfg.pcLanUrl) }
    var syncMsg by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Card(colors = CardDefaults.cardColors(containerColor = cardBg), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("⚡ 选择翻译引擎通道", color = Color(0xFFFFD2E8), fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(
                        "auto_free" to "免配置免费极速",
                        "deepseek" to "DeepSeek大模型",
                        "pc_lan" to "联动电脑端引擎"
                    ).forEach { (code, label) ->
                        FilterChip(
                            selected = cfg.transEngine == code,
                            onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(transEngine = code) } },
                            label = { Text(label, fontSize = 11.5.sp) }
                        )
                    }
                }

                OutlinedTextField(
                    value = apiBase,
                    onValueChange = { apiBase = it },
                    label = { Text("大模型 API Base URL") },
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = { Text("DeepSeek / OpenAI API Key（选填）") },
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = modelName,
                    onValueChange = { modelName = it },
                    label = { Text("模型名称（如 deepseek-chat）") },
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = pcLan,
                    onValueChange = { pcLan = it },
                    label = { Text("电脑端局域网桥接地址（如 http://192.168.1.8:18765）") },
                    modifier = Modifier.fillMaxWidth()
                )

                if (syncMsg.isNotBlank()) {
                    Text(syncMsg, color = Color(0xFF8CE4FF), fontSize = 12.sp)
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                val n = runCatching { MobileTranslator.syncGlossaryFromPcLan(pcLan) }.getOrDefault(-1)
                                syncMsg = if (n >= 0) "✅ 已成功连接电脑端（检测到 $n 条番剧术语）" else "⚠️ 无法连接电脑端，请检查同一 Wi-Fi 与地址"
                            }
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("测试连接电脑端")
                    }
                    Button(
                        onClick = {
                            AppStateBus.updateEngineConfig(ctx) {
                                it.copy(
                                    llmApiBase = apiBase.trim(),
                                    llmApiKey = apiKey.trim(),
                                    llmModel = modelName.trim(),
                                    pcLanUrl = pcLan.trim(),
                                    transEngine = if (apiKey.isNotBlank() && it.transEngine == "auto_free") "deepseek" else it.transEngine
                                )
                            }
                            MobileTranslator.clearCache()
                            syncMsg = "✅ 引擎设置已保存！"
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = accentPink),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("💾 保存设置")
                    }
                }
            }
        }
    }
}
