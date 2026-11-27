package com.anilingo.translator.ui.main

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
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

private val CanvasBg = Color(0xFFF5F7FA)
private val CardWhite = Color(0xFFFFFFFF)
private val CardBorder = Color(0xFFE5E9F0)
private val PrimaryBlue = Color(0xFF2563EB)
private val StopRedBg = Color(0xFFFEE2E2)
private val StopRedText = Color(0xFFDC2626)
private val TextMain = Color(0xFF0F172A)
private val TextSub = Color(0xFF64748B)

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

    Scaffold(
        containerColor = CanvasBg,
        topBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(CardWhite)
                    .padding(top = 40.dp, start = 18.dp, end = 18.dp, bottom = 0.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(30.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(PrimaryBlue),
                        contentAlignment = Alignment.Center
                    ) {
                        Text("译", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    }
                    Spacer(Modifier.width(10.dp))
                    Text("轻译", color = TextMain, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(10.dp))
                    Text(statusText, color = TextSub, fontSize = 12.sp)
                }
                Spacer(Modifier.height(10.dp))
                TabRow(
                    selectedTabIndex = selectedTab,
                    containerColor = CardWhite,
                    contentColor = PrimaryBlue
                ) {
                    listOf("实时翻译", "字幕外观", "词表记录", "偏好设置").forEachIndexed { idx, title ->
                        Tab(
                            selected = selectedTab == idx,
                            onClick = { selectedTab = idx },
                            text = {
                                Text(
                                    text = title,
                                    fontSize = 13.sp,
                                    fontWeight = if (selectedTab == idx) FontWeight.Bold else FontWeight.Medium,
                                    color = if (selectedTab == idx) PrimaryBlue else TextSub
                                )
                            }
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
                .padding(16.dp)
        ) {
            when (selectedTab) {
                0 -> DashboardTab(
                    onToggleOverlay = onToggleOverlay,
                    onPickRegion = onPickRegion,
                    onToggleLiveScreen = onToggleLiveScreen,
                    onStartSnip = onStartSnip,
                    onToggleAudio = onToggleAudio,
                )
                1 -> LyricsStyleTab()
                2 -> EditAndGlossaryTab()
                3 -> EngineSettingsTab()
            }
        }
    }
}

@Composable
private fun CleanCard(content: @Composable () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = CardWhite),
        border = BorderStroke(1.dp, CardBorder),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            content()
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DashboardTab(
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
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        CleanCard {
            Text("全局悬浮字幕", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text("开启后可在其他视频软件上方悬浮显示字幕，轻触字幕可展开快捷控制条。", color = TextSub, fontSize = 12.5.sp)
            Button(
                onClick = onToggleOverlay,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (overlayRunning) StopRedBg else PrimaryBlue,
                    contentColor = if (overlayRunning) StopRedText else Color.White,
                ),
                shape = RoundedCornerShape(9.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (overlayRunning) "关闭悬浮字幕" else "开启悬浮字幕", fontWeight = FontWeight.SemiBold)
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("ja" to "日语", "en" to "英语", "ko" to "韩语", "auto" to "自动识别").forEach { (code, label) ->
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

        CleanCard {
            Text("屏幕区域与截图翻译", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text("框选固定字幕区域自动实时翻译，或随时单次框选画面翻译。", color = TextSub, fontSize = 12.5.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = onPickRegion,
                    shape = RoundedCornerShape(9.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("框选区域")
                }
                Button(
                    onClick = onToggleLiveScreen,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (liveScreen) StopRedBg else PrimaryBlue,
                        contentColor = if (liveScreen) StopRedText else Color.White,
                    ),
                    shape = RoundedCornerShape(9.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text(if (liveScreen) "停止翻译" else "开始翻译", fontWeight = FontWeight.SemiBold)
                }
            }
            OutlinedButton(
                onClick = onStartSnip,
                shape = RoundedCornerShape(9.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("框选截屏翻译")
            }
        }

        CleanCard {
            Text("声音实时翻译", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text("识别麦克风说话声或手机系统内部播放原声。", color = TextSub, fontSize = 12.5.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = engineCfg.audioSource == "mic",
                    onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(audioSource = "mic") } },
                    label = { Text("麦克风说话") }
                )
                FilterChip(
                    selected = engineCfg.audioSource == "internal",
                    onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(audioSource = "internal") } },
                    label = { Text("手机系统内录") }
                )
            }
            Button(
                onClick = onToggleAudio,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (liveAudio) StopRedBg else PrimaryBlue,
                    contentColor = if (liveAudio) StopRedText else Color.White,
                ),
                shape = RoundedCornerShape(9.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (liveAudio) "停止听译" else "开始听译", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LyricsStyleTab() {
    val ctx = LocalContext.current
    val st by AppStateBus.style.collectAsState()
    val curOrig by AppStateBus.currentOriginal.collectAsState()
    val curTrans by AppStateBus.currentTranslated.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(Brush.horizontalGradient(listOf(Color(0xFF334155), Color(0xFF475569))))
                .padding(20.dp),
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

        CleanCard {
            Text("预设主题", color = TextMain, fontWeight = FontWeight.Bold, fontSize = 14.sp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MOBILE_LYRICS_PRESETS.forEach { preset ->
                    FilterChip(
                        selected = st.presetKey == preset.key,
                        onClick = { AppStateBus.applyPreset(ctx, preset) },
                        label = { Text(preset.title, fontSize = 12.sp) }
                    )
                }
            }

            Text("文字大小：${st.baseFontSp.toInt()} sp", color = TextMain, fontSize = 13.sp)
            Slider(
                value = st.baseFontSp,
                onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(baseFontSp = v) } },
                valueRange = 14f..36f
            )

            Text("描边粗细：${"%.1f".format(st.strokeWidthDp)} dp", color = TextMain, fontSize = 13.sp)
            Slider(
                value = st.strokeWidthDp,
                onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(strokeWidthDp = v) } },
                valueRange = 0f..6f
            )

            Text(
                text = if (st.bgAlpha == 0) "底板透明：全透明" else "底板透明：${(st.bgAlpha * 100 / 255)}%",
                color = TextMain,
                fontSize = 13.sp
            )
            Slider(
                value = st.bgAlpha.toFloat(),
                onValueChange = { v -> AppStateBus.updateStyle(ctx) { it.copy(bgAlpha = v.toInt()) } },
                valueRange = 0f..200f
            )

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("长句自动缩放字号", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.autoScaleFont,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(autoScaleFont = c) } }
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("显示双语对照", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.bilingual,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(bilingual = c) } }
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("6 秒无新台词自动淡出隐藏", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.autoHideSeconds > 0,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(autoHideSeconds = if (c) 6 else 0) } }
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("底板贴合文字宽度", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.fitBgToText,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(fitBgToText = c) } }
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("保留上一句防语速过快", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.keepPrevLine,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(keepPrevLine = c) } }
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("底部锚定防跳动", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.5.sp)
                Switch(
                    checked = st.anchorBottom,
                    onCheckedChange = { c -> AppStateBus.updateStyle(ctx) { it.copy(anchorBottom = c) } }
                )
            }

            Text("显示模式", color = TextMain, fontWeight = FontWeight.Bold, fontSize = 13.5.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = st.displayMode == "subtitle",
                    onClick = { AppStateBus.updateStyle(ctx) { it.copy(displayMode = "subtitle") } },
                    label = { Text("标准字幕（影院双句）", fontSize = 12.sp) }
                )
                FilterChip(
                    selected = st.displayMode == "danmaku",
                    onClick = { AppStateBus.updateStyle(ctx) { it.copy(displayMode = "danmaku") } },
                    label = { Text("轻量弹幕流", fontSize = 12.sp) }
                )
            }
        }
    }
}

@Composable
private fun EditAndGlossaryTab() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val curOrig by AppStateBus.currentOriginal.collectAsState()
    val curTrans by AppStateBus.currentTranslated.collectAsState()
    val glossary by AppStateBus.glossary.collectAsState()
    val cfg by AppStateBus.engineConfig.collectAsState()

    var editTrans by remember(curTrans) { mutableStateOf(curTrans) }
    var newSrc by remember { mutableStateOf("") }
    var newDst by remember { mutableStateOf("") }
    var glossSyncTip by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        CleanCard {
            Text("修改当前译文", color = TextMain, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            OutlinedTextField(
                value = editTrans,
                onValueChange = { editTrans = it },
                label = { Text("中文译文") },
                modifier = Modifier.fillMaxWidth()
            )
            Button(
                onClick = { AppStateBus.editCurrentSubtitle(curOrig, editTrans) },
                colors = ButtonDefaults.buttonColors(containerColor = PrimaryBlue),
                shape = RoundedCornerShape(9.dp),
                modifier = Modifier.align(Alignment.End)
            ) {
                Text("应用修改")
            }
        }

        CleanCard {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("专有名词词表", color = TextMain, fontWeight = FontWeight.Bold, fontSize = 15.sp, modifier = Modifier.weight(1f))
                if (cfg.pcLanUrl.isNotBlank()) {
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                val n = runCatching { MobileTranslator.syncGlossaryFromPcLan(ctx, cfg.pcLanUrl) }.getOrDefault(-1)
                                glossSyncTip = if (n >= 0) "已与电脑端双向同步，共 $n 条词条" else "同步失败，请检查电脑端局域网连接"
                            }
                        },
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("同步电脑词表", fontSize = 12.sp)
                    }
                }
            }
            if (glossSyncTip.isNotBlank()) {
                Text(glossSyncTip, color = PrimaryBlue, fontSize = 12.sp)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = newSrc,
                    onValueChange = { newSrc = it },
                    label = { Text("外语原词") },
                    modifier = Modifier.weight(1f)
                )
                OutlinedTextField(
                    value = newDst,
                    onValueChange = { newDst = it },
                    label = { Text("固定译名") },
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
                colors = ButtonDefaults.buttonColors(containerColor = PrimaryBlue),
                shape = RoundedCornerShape(9.dp),
                modifier = Modifier.align(Alignment.End)
            ) {
                Text("添加词条")
            }

            glossary.entries.forEach { (k, v) ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFFF8FAFC), RoundedCornerShape(8.dp))
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("$k  →  $v", color = TextMain, modifier = Modifier.weight(1f), fontSize = 13.sp)
                    Text(
                        text = "删除",
                        color = StopRedText,
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

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EngineSettingsTab() {
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
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        CleanCard {
            Text("翻译引擎", color = TextMain, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    "auto_free" to "自动竞速（推荐）",
                    "cn_direct" to "国内直连免代理",
                    "deepseek" to "DeepSeek 大模型",
                    "pc_lan" to "联动电脑端"
                ).forEach { (code, label) ->
                    FilterChip(
                        selected = cfg.transEngine == code,
                        onClick = { AppStateBus.updateEngineConfig(ctx) { it.copy(transEngine = code) } },
                        label = { Text(label, fontSize = 12.sp) }
                    )
                }
            }

            OutlinedTextField(
                value = apiBase,
                onValueChange = { apiBase = it },
                label = { Text("大模型接口地址") },
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                label = { Text("API Key（选填）") },
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = modelName,
                onValueChange = { modelName = it },
                label = { Text("模型名称") },
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = pcLan,
                onValueChange = { pcLan = it },
                label = { Text("电脑端局域网地址（如 http://192.168.1.8:18765）") },
                modifier = Modifier.fillMaxWidth()
            )

            if (syncMsg.isNotBlank()) {
                Text(syncMsg, color = PrimaryBlue, fontSize = 12.sp)
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            val n = runCatching { MobileTranslator.syncGlossaryFromPcLan(ctx, pcLan) }.getOrDefault(-1)
                            syncMsg = if (n >= 0) "双向同步成功，当前词表共 $n 条" else "无法连接电脑端，请确认处于同一 Wi-Fi"
                        }
                    },
                    shape = RoundedCornerShape(9.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("同步电脑词表")
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
                        syncMsg = "设置已保存"
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryBlue),
                    shape = RoundedCornerShape(9.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("保存设置")
                }
            }
        }
    }
}
