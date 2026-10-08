# audioviz-bridge

轻量音频特征到 OSC/MIDI 的桥接库，专为现场 VJ 设计。

它不生成画面，不替代 Resolume 或 TouchDesigner。它只做一件事：
**从实时音频中提取节奏和能量，转成 OSC/MIDI 信号，发给你的播控软件。**

如果它崩溃或延迟异常，你关掉它，系统立刻回到手动模式。演出不受影响。

---

## 它是什么 / 它不是什么

**是：**
- 一个可以被嵌入现有信号链的 Python 库
- 一个带安全阀的音频分析中间件
- 一个 YAML 热加载的映射引擎

**不是：**
- 一个视觉生成器（画面由 Resolume / TouchDesigner 渲染）
- 一个独立应用（没有 GUI，没有主窗口）
- 一个时间码同步系统（做的是实时响应，不是帧级精确回放）

---

## 核心特性

- **Ableton Link 同步**：与 Ableton Live、Resolume 等设备共享 tempo 和 beat 相位
- **带置信度的 onset 检测**：发浮点数，不发布尔值。VJ 自己设阈值，低置信度信号不会误触
- **YAML 热加载**：改映射配置不用重启进程
- **安全阀机制**：静音超时自动停止发送，单后端故障不影响其他后端
- **可选依赖**：Ableton Link 是 extra，不用可以不装

---

## 安装

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <repo>
cd audioviz-bridge

# 基础安装（仅 OSC）
uv sync

# 带 Ableton Link 支持
uv sync --extra link
```

如果你不用 uv，标准 pip 也可以：

```bash
pip install -e .
pip install -e ".[link]"
```

---

## 快速开始

### 验证信号链（无需音频硬件）

```bash
# 终端 1：起一个 OSC 接收器
uv run python -c "
from pythonosc import dispatcher, osc_server

def handler(address, *args):
    print(address, args)

d = dispatcher.Dispatcher()
d.set_default_handler(handler)
s = osc_server.ThreadingOSCUDPServer(('127.0.0.1', 7000), d)
print('listening on 7000')
s.serve_forever()
"

# 终端 2：跑模拟源
uv run audioviz-bridge --config mappings.yaml --osc 127.0.0.1:7000 \
  --source simulate --bpm 128 --stats
```

终端 1 会打印出 `/visual/kick [0.87]、/visual/bass [0.42]` 这样的消息，说明合成音频 → FFT 分析 → onset 检测 → YAML 映射 → OSC 输出整条链路都通了。

### 真实演出

```bash
# 1. 改 mappings.yaml 里的 OSC 地址和阈值
# 2. 运行
uv run audioviz-bridge --config mappings.yaml --osc 127.0.0.1:7000 --stats
```

输出示例：

```bash
[audioviz-bridge] running. config=mappings.yaml osc=127.0.0.1:7000 midi=False
[stats] frames=1420 emitted=312 link=True tempo=128.0
```

然后在 Resolume 里把 OSC 输入端口设为 7000，用 `/visual/kick`、`/visual/bass` 等地址做 OSC Learn 绑定。

### 系统依赖

`audioviz-bridge` 依赖 PortAudio 系统库。如果首次运行报错
`OSError: PortAudio library not found`，请先安装：

- Ubuntu/Debian: `sudo apt install libportaudio2 portaudio19-dev`
- Fedora: `sudo dnf install portaudio portaudio-devel`
- macOS: `brew install portaudio`

Windows 用户通过 pip/uv 安装时通常会自动附带，无需额外操作。

---

## 配置 mappings.yaml

每个信号是一条路由。VJ 改这个文件不用重启进程。

```yaml
signals:
  # 底鼓脉冲：只有检测到低频 onset 时才触发
  - name: kick_pulse
    source: onset
    osc_address: /visual/kick
    trigger_on: onset
    gate_source: bass
    gate_threshold: 0.15
    confidence_threshold: 0.4
    range: [0.0, 1.0]
    min_interval: 0.05

  # 低频能量连续值：驱动画面尺寸/冲击
  - name: bass_level
    source: bass
    osc_address: /visual/bass
    range: [0.0, 1.0]

  # MIDI CC 输出示例：把 bass 能量发到 CC 1
  - name: bass_cc
    source: bass
    osc_address: ""
    midi_cc: 1
    midi_channel: 0
    range: [0.0, 1.0]
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 路由名称，仅用于日志和调试 |
| `source` | 是 | `beat` / `onset` / `rms` / `bass` / `mid` / `treble` |
| `osc_address` | 否 | OSC 地址，留空则不发送 OSC |
| `trigger_on` | 否 | `onset` 表示只在检测到瞬态时发送；`beat` 表示只在节拍脉冲时发送 |
| `confidence_threshold` | 否 | 低于此值的信号不发送，默认 0.0 |
| `gate_source` | 否 | 门控信号源，只有该信号超过 `gate_threshold` 时才发送 |
| `gate_threshold` | 否 | 门控阈值，默认 0.0 |
| `min_interval` | 否 | 最小发送间隔（秒），防止高频抖动 |
| `midi_cc` | 否 | MIDI CC 编号，设置后启用 MIDI 输出 |
| `midi_channel` | 否 | MIDI 通道，默认 0 |
| `range` | 否 | 输出缩放范围，默认 `[0.0, 1.0]` |

### source 可选值

| 值 | 含义 | 输出范围 |
|---|---|---|
| `beat` | Ableton Link 节拍脉冲（无 Link 时用内部时钟 fallback） | 0.0 - 1.0 |
| `onset` | 瞬态检测强度 | 0.0 - 1.0 |
| `rms` | 整体音量能量 | 0.0 - 1.0 |
| `bass` | 低频段（20-250Hz）能量 | 0.0 - 1.0 |
| `mid` | 中频段（250-2000Hz）能量 | 0.0 - 1.0 |
| `treble` | 高频段（2k-8kHz）能量 | 0.0 - 1.0 |

---

## 命令行参数

```
uv run audioviz-bridge --help
```

| 参数 | 说明 |
| --- |  --- |
| `--config, -c` | mappings.yaml 路径（必填） |
| --- |  --- |
| `--osc` | OSC 目标，格式 `IP:端口`，默认端口 7000 |
| `--midi` | 启用 MIDI CC 输出 |
| `--midi-port` | 虚拟 MIDI 端口名，默认 `audioviz-bridge` |
| `--device` | 音频输入设备索引或名称 |
| `--sample-rate` | 采样率，默认 48000 |
| `--block-size` | 音频块大小，默认 1024 |
| `--source` | `device`（真实输入）或 `simulate`（合成音频，默认 device） |
| `--bpm` | 模拟源的 BPM，默认 120 |
| `--no-link` | 禁用 Ableton Link |
| `--stats` | 每 5 秒打印统计信息 |

---

### 模拟源说明

`--source simulate` 生成一个合成音频模式：每拍一个 60Hz 底鼓、连续的 80Hz 贝斯、半拍一次的高频 hi-hat、以及 440Hz 旋律音。它走的是**和生产环境完全相同的分析管线**——同样的 FFT、频段能量计算、onset 检测。区别只是音频来自合成而非硬件。

用途：

-   WSL / 容器 / 服务器等无音频硬件的环境
-   验证 OSC 映射和播控软件绑定
-   开发时不需要插麦克风

真实演出时用默认的 `--source device` 即可。

## 安全阀机制

这是和“实验性音频分析项目”的核心区别。

**静音超时**：3 秒内没有音频输入，自动停止发送任何 OSC/MIDI。不会因为麦克风拔掉或音频接口断开而持续发送最后一帧的值。

**置信度门槛**：onset 检测发出的是 0.0-1.0 的浮点数，不是布尔值。VJ 在 Resolume 里设定触发阈值，复杂现场环境下的低置信度信号被自动过滤。

**门控机制**：`gate_source` + `gate_threshold` 确保只有当特定频段有能量时，才发送信号。例如只有低频 onset 才算底鼓，中高频的瞬态不会误触发。

**后端隔离**：OSC 发送失败不会影响 MIDI 发送，反之亦然。单个后端异常被静默处理，不会中断主循环。

---

## 与现有项目的关系

| 项目 | 定位 | 差异 |
|---|---|---|
| sound-to-light-osc | 完整应用，带 PyQt5 界面 | 你的库是中间件，不是应用 |
| aubio | 底层音频分析库 | 你的库处理 OSC、映射、安全阀 |
| Realtime_PyAudio_FFT | 频谱可视化工具 | 你的库面向 VJ 信号链，不是分析仪 |
| WLEDAudioSyncRTBeat | 独立可执行程序 | 你的库是库，不是程序 |

你的库不发明新技术，只把已有能力**按 VJ 工作流重新组装**。

---

## 故障排除

### `OSError: PortAudio library not found`

见上面「系统依赖：PortAudio」。

### `sounddevice.PortAudioError: Error querying device -1`

系统里没有可用的默认音频输入设备。先列出可用设备：

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices()); print('默认:', sd.default.device)"
```

如果输出是 `[-1, -1]`，说明系统完全没识别到音频设备。三种情况：

**A. 有硬件但音频服务没跑**

```bash
# PipeWire
systemctl --user start pipewire pipewire-pulse wireplumber
# 或 PulseAudio
systemctl --user start pulseaudio
```

**B. 服务器 / 容器 / WSL 没有声卡**
用模拟源验证信号链：

```bash
uv run audioviz-bridge -c mappings.yaml --osc 127.0.0.1:7000 \\
  --source simulate --stats
```

或加载虚拟声卡（Linux）：

```bash
sudo modprobe snd-aloop
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

**C. 有多个设备，需要指定**
从 `sd.query_devices()` 输出里找到 input 设备的编号，用 `--device <编号>` 指定。

### 没有 OSC 输出

-   检查 `--stats` 里 `frames` 是否在增长。不增长说明音频源有问题
-   检查 `mappings.yaml` 里的 `osc_address` 是否为空
-   检查 `confidence_threshold` 是否设得太高

### Ableton Link 不可用

-   确认安装了 extra：`uv sync --extra link`
-   确认 `--stats` 里 `link=True`
-   如果 Link 不可用，库会自动 fallback 到内部时钟，不会中断

### MIDI 端口打不开

-   macOS/Linux 支持虚拟 MIDI 端口，Windows 需要安装 loopMIDI
-   检查 `--midi-port` 名称是否和其他软件冲突

### 延迟太高

-   减小 `--block-size`（如 512），代价是 CPU 占用略增
-   检查音频输入设备的缓冲区设置

---
