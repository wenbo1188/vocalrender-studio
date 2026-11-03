# VocalRender Studio

为 [VocalRender](https://github.com/pymaster17/VocalRender)（乐谱原生的歌声合成模型）设计的创作界面，沿用主流歌声合成软件的“轨道 + 钢琴卷帘”工作流，编辑逻辑和请求格式与 VocalRender 的真实输入一致。

提供两个版本，功能相同：

- **网页版**：根目录的 `index.html`，单文件、无需构建，用浏览器直接打开。
- **Windows 桌面版**：`desktop/` 目录，Electron 打包，Windows 11 外观，另有工程文件、WAV 导出、双击打开 `.vrproj` 等桌面功能。仓库只包含源码，生成 exe 的方法见 [desktop/README.md](desktop/README.md)。

## 功能

- **钢琴卷帘**：上下拖动音符改音高，拖右边缘改时值（吸附模型支持的 12 种音符，后续音符自动顺延），双击填词，Tab 跳到下一个音符。
- **歌词约定**：每个音符一个汉字；`-` 表示延续上一个字（一字多音）；`SP` 休止；`AP` 换气。
- **批量歌词**：输入一句歌词按顺序填入音符；空卷帘会自动生成四分音符。
- **参考声线**：内置 GTSinger 的 6 段参考（Alto-1/2/3、Tenor-1/2/3），也可上传 2–8 秒清唱（需确认使用授权）。键盘和网格上标出所选声线的建议音域。
- **按乐句渲染**：在休止处自动分句、逐句提交（单次上限 64 个字/休止单元、128 个事件）。状态依次为未渲染 → 排队中 → 渲染中 → 已渲染 / 已修改。
- **多版本**：同一乐句可生成多个版本对比挑选；改乐谱、声线、模型或生成参数后，受影响的乐句标为需重新渲染。
- **音高线**：渲染完成后在卷帘上画出该版本的实际音高（F0）曲线，可看到滑音、颤音和尾音下滑；乐谱改动后曲线变虚线便于对照。服务返回 `f0` 时直接使用，否则前端用 YIN 算法从结果音频提取。
- **钢琴预听**：点击、拖动音符和播放未渲染乐句时使用合成钢琴音。
- **生成参数**：`cfg_value`、`inference_timesteps`、`temperature`、`fsq_temperature`、`prompt_max_frames`、`max_len`、`lyrics_only`、随机种子，附“稳定 / 均衡 / 生动”预设。
- **校验**：实时标出非中文歌词、连音前无字、超出单次上限、超出音域等问题，可一键跳转。
- **其他**：伴奏导入同步播放、导入 VocalRender 标注 JSON、打开 `.vrproj` 工程、撤销/重做、快捷键（按 `?` 查看）、自动保存。

## 服务接口

默认是**演示模式**：渲染在本地模拟，人声用共振峰合成器近似。在设置里切到“连接 VocalRender 服务”并填写服务地址后，会调用以下端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 连接测试 |
| GET | `/voices` | 内置参考声线 |
| POST | `/voices` | 上传参考音频（multipart），返回 `upload_id` |
| POST | `/render` | 提交一个乐句，返回 `job_id` |
| GET | `/jobs/{job_id}` | `status`：queued / running / succeeded / failed；`progress` 0–1；`audio_url`；可选 `f0: {hop_s, hz[]}`（无声帧为 0） |
| GET | `/jobs/{job_id}/audio` | 48 kHz WAV |
| POST | `/score/import` | 把 ABC / MusicXML 解析成 word·pitch·note·pitch2word |

`POST /render` 请求体（`score` 字段与 VocalRender 标注 JSON 一致）：

```json
{
  "checkpoint": "VocalRender-Pro",
  "score": {
    "item_name": "proj_p01",
    "word": ["晚", "风", "吹", "过", "旧", "街", "口", "SP"],
    "pitch": [64, 67, 69, 67, 64, 62, 60, 62, 0],
    "note": ["<NOTE_8>", "<NOTE_8>", "<NOTE_4>", "<NOTE_8>", "<NOTE_8>", "<NOTE_4>", "<NOTE_DOT_4>", "<NOTE_8>", "<NOTE_2>"],
    "pitch2word": [0, 1, 2, 3, 4, 5, 6, 6, 7],
    "bpm": 90
  },
  "prompt_audio": { "preset": "Alto-1" },
  "generation": {
    "cfg_value": 2.0, "inference_timesteps": 10, "temperature": 1.0,
    "fsq_temperature": 0, "max_len": 2000, "prompt_max_frames": 50,
    "lyrics_only": false, "seed": null
  },
  "output": { "sample_rate": 48000, "format": "wav" }
}
```

服务端可基于官方仓库的 `demo/app.py` 或 `scripts/infer_vocalrender_svs_single.py` 封装，生成参数名与该脚本的命令行参数一致。网页版直接从浏览器请求，服务端需要允许跨域（CORS）；桌面版由主进程发请求，没有这个限制。

### 用模拟服务试用远程模式

`tools/mock_vocalrender_server.py` 实现了上面的接口，返回跟随乐谱的简单合成音（不是真实歌声），只需 Python 3，不需要 GPU：

```bash
python tools/mock_vocalrender_server.py          # http://127.0.0.1:8000/v1
python tools/mock_vocalrender_server.py --no-f0  # 不返回 f0，由前端自己提取音高线
```

然后在编辑器的设置里把服务地址填为 `http://127.0.0.1:8000/v1`。

## 目录结构

```
index.html                      网页版（也是桌面版的界面来源）
desktop/                        Windows 桌面版（Electron），构建说明见 desktop/README.md
tools/mock_vocalrender_server.py  模拟渲染服务
.github/workflows/build-windows.yml  在 GitHub Actions 上构建 exe
```
