# 给 Codex 的提示词

分四轮，每轮结束你检查一次再进下一轮。每段提示词都能在新会话里单独使用。在仓库根目录 `ai-passport-nabo-xiaozhi/` 下启动 Codex。

---

## 第 1 轮：造型设计（你来选）

```
请先完整阅读 game-art/dive/ART_BRIEF.md，这是美术规格，必须遵守。

任务：基于你已知的 NABO 形象，设计 NABO 的潜水造型，只做设计，不做动画。

1. 出 3 个造型方案，放在 game-art/dive/design/option_a.png、option_b.png、option_c.png。
   每个方案包含：标准朝向（往左下潜、身体约 50°、脸 3/4 朝向观众）的全身图、正面图、配色色块。
   三个方案在服装改动、配色、描边或边缘光处理、简化程度上有所区别。
2. 每个方案另外缩小到 56 px 高，分别放在深蓝 #0B2A4A 和近黑 #04070D 背景上，
   放大 4 倍（最近邻）展示，用来检查小尺寸下的辨识度。
3. 画风：2D 卡通，平涂加两阶赛璐珞阴影，粗描边，不要软 3D 渲染。
4. 在 design/README.md 里用几句话说明每个方案的取舍。

只在 game-art/dive/ 下工作，不要修改其他目录。完成后告诉我三张图的路径。
```

**你要检查的：** 56 px 那张图里还认不认得出是 NABO。选一个方案，或者说明要怎么混合。

---

## 第 2 轮：骨骼和渲染管线 + 第一个动作

```
请先完整阅读 game-art/dive/ART_BRIEF.md。造型定稿是 game-art/dive/design/option_?.png（我选的方案，以及要调整的地方：____）。

任务：搭建骨骼拼接动画管线，先只做 swim 一个动作，用来验证流畅度。

1. 按 ART_BRIEF 第 4 节，把定稿角色拆成 SVG 部件，放在 game-art/dive/rig/，
   支点和图层层级写在 rig/rig.json。表情（眼睛、嘴）做成可替换的部件。
2. 在 game-art/dive/tools/ 写渲染脚本，支持 --anim、--angle、--scale、--mirror 参数，
   输出 256×256 RGBA PNG，锚点固定在 (128,128) 并对准胸口。
   关键帧加缓动曲线，不要线性插值；飘动部件用跟随（比身体慢半拍）。
3. 渲染 swim 的 8 帧到 frames/swim/01.png … 08.png，12 fps 循环，首尾无缝。
4. 输出 preview/swim_4x.gif（4 倍放大），以及 preview/swim_actual.gif
   （实际 56 px 高，五层背景色并排，颜色先用 #3FA9D6、#1B5E8C、#0B2A4A、#061528、#04070D）。
5. 再输出一张 preview/swim_onion.png：8 帧半透明叠在一起，用来检查锚点是否稳定。
6. tools/README.md 写明安装依赖和渲染命令。

只在 game-art/dive/ 下工作。完成后告诉我预览文件的路径，并说明你自己检查过的验收项。
```

**你要检查的：** 打开 `swim_4x.gif` 看循环顺不顺、有没有抖；看 `swim_actual.gif` 实际大小的效果。**这一步满意了再继续**，不满意就让它改关键帧，改起来很便宜。

---

## 第 3 轮：其余 NABO 动作

```
请先完整阅读 game-art/dive/ART_BRIEF.md。骨骼和渲染脚本已经在 game-art/dive/rig/ 和 tools/ 里，swim 动作已经确认。

任务：用同一套骨骼和脚本，渲染 ART_BRIEF 第 6 节里的其余全部动作：
gulp、lowair、out、hit、dash_in、dash、dash_out（必需），turn（推荐），nearmiss、entry、record（可选）。

要求：
- 不改动已经确认的部件外观；需要的新表情（鼓腮、闭眼、×_× 眼睛、惊讶、开心）作为新的可替换部件加入。
- turn 的第 3 帧是左右对称的正面姿势，需要为头部和身体增加正面朝向的部件。
- hit 的最后一帧要能自然接回 swim 第 1 帧。
- gulp 在 manifest 的 events 里标出"吞下"是第几帧。
- 每个动作都输出 4 倍 GIF、实际尺寸 GIF 和叠帧图到 preview/。
- 生成 game-art/dive/manifest.json（格式见 ART_BRIEF 第 10 节），包含所有动作。

只在 game-art/dive/ 下工作。完成后列出每个动作的帧数，并对照第 11 节验收清单逐项说明。
```

---

## 补充：单独做俯冲动作

如果第 2 轮的 swim 已经确认，想先做俯冲，用这段：

```
请先完整阅读 game-art/dive/ART_BRIEF.md，特别是第 6 节的俯冲三组动作和下面那段引擎说明。
骨骼和渲染脚本已经在 game-art/dive/rig/ 和 tools/ 里，swim 动作已经确认。

任务：用同一套骨骼和脚本做 NABO 的俯冲动作：
1. dash_in（3 帧，不循环）：从 swim 收拢成流线型，双臂向前并拢、腿并拢绷直。
2. dash（4 帧，循环）：保持流线型，只有脚小幅快速打水，飘动部件被水流拉直并高频抖动。
3. dash_out（3 帧，不循环）：张开手脚减速，最后一帧能接回 swim 第 1 帧。

要求：
- 仍按标准朝向（往左下、约 50°）绘制，锚点 (128,128) 不变。
- 不要画拉伸、速度线和尾迹，这些由引擎负责。
- 输出到 frames/dash_in/、frames/dash/、frames/dash_out/，并更新 manifest.json。
- 输出 preview/dash_sequence_4x.gif：swim 2 圈 → dash_in → dash 3 圈 → dash_out → swim 1 圈，连续播放，用来检查衔接是否顺。
- 每个动作也输出实际尺寸 GIF 和叠帧图。

只在 game-art/dive/ 下工作。完成后告诉我预览文件的路径。
```

**你要检查的：** `dash_sequence_4x.gif` 里，进入和退出俯冲的两个衔接点有没有跳帧。

---

## 第 3 轮（按当前原型精简版）

swim、dash_in、dash、dash_out 已经接进原型，用这段补齐其余动作：

```
请先完整阅读 game-art/dive/ART_BRIEF.md（第 3 节描边要求和第 6 节动作清单已更新）。
骨骼、渲染脚本、swim 和三段俯冲动作已经确认，并已接入原型；不要改动已确认的动作和部件外观。
皮肤：____（填 a / b / c，或"三套都做"）。

任务一：外描边改成深色
把所有皮肤部件的白色外描边改为深色（各部位固有色的深色，参考值 #101E34），然后重新渲染已确认的 swim、dash_in、dash、dash_out。只改描边颜色，不动姿势和时间轴。

任务二：补齐动作（同一套骨骼和脚本）
必需：
- gulp（3 帧，12 fps，不循环）：张嘴一吞，腮帮鼓起后回落。在 events 里标出"吞下"是第几帧。
- hit（4 帧，12 fps，不循环）：被撞歪，眼睛变 ×_× 或螺旋，嘴里喷气泡；最后一帧能接回 swim 第 1 帧。不是死亡动作。
- lowair（4 帧，16 fps，循环）：鼓腮憋气、表情难受，划水幅度比 swim 小、更急。
- out（6 帧，12 fps，不循环）：吐出最后一口气、闭眼，身体放松慢慢翻成仰面漂浮。
- turn（3 帧，24 fps，不循环）：从标准朝向转到正面，第 3 帧必须左右对称（引擎镜像第 2、1 帧完成后半段）。这是玩家每次按键都会播放的动作，要短而干脆，不要拖。
可选：
- nearmiss（2 帧）：眼睛瞪大、身体一缩。
- record（3 帧）：开心的表情或手势。

需要的新表情（鼓腮、闭眼、×_× 眼、惊讶、开心）作为可替换部件加进 rig。

要求：
- 仍按标准朝向（往左下约 50°）绘制，锚点 (128,128)，和已确认动作用同一个统一缩放比例。
- 不画镜像、倾斜、拉伸、发光、拖尾、受光边，这些由引擎负责。
- manifest.json 沿用现在的结构：每个动作写 loop、fps、frame_count、skin_frames、events。原型会自动读取新动作。
- 每个动作输出 4 倍 GIF、实际尺寸 GIF 和叠帧图到 preview/；另外输出 preview/hit_sequence_4x.gif（swim → hit → swim）和 preview/turn_sequence_4x.gif（swim → turn → 镜像 turn → 镜像 swim），用来检查衔接。

只在 game-art/dive/ 下工作。完成后对照 ART_BRIEF 第 11 节验收清单逐项说明。
```

**你要检查的：** `hit_sequence_4x.gif` 和 `turn_sequence_4x.gif` 里的两个衔接点有没有跳帧；`turn` 看起来够不够干脆。

---

## 第 4 轮：海洋生物、气泡、配色、界面

```
请先完整阅读 game-art/dive/ART_BRIEF.md。NABO 的定稿和 manifest.json 已经完成，新素材的画风要和 NABO 保持一致。

任务：
1. 按第 7 节制作水母（大小两种）、鮟鱇、三种气泡、气泡破裂、海底喷口的帧动画。
   能用 SVG 加脚本生成的就用同样的管线生成，保证帧间一致。
2. 按第 8 节写 palette/zones.json，五层的颜色都附上 RGB565 值。
   出一张 design/zones.png：五层各一个 240×320 的场景示意，放上 NABO、气泡、生物和岩壁颜色，检查每一层的对比度。
3. 按第 9 节在 ui/ 中出四张 240×320 原尺寸界面稿：标题、游戏中 HUD、游戏结束、破纪录。
   字体只用 Space Mono、Archivo Black、思源黑体。
4. 把新素材加进 manifest.json 的 sprites 部分，并输出对应的 preview GIF。

只在 game-art/dive/ 下工作。完成后对照第 11 节验收清单逐项说明。
```

---

## 完成之后

告诉我素材已经就绪就行。我会读 `manifest.json`，写转换脚本把帧量化成 RGB565 调色板 + alpha 压缩格式，接进原型里调动画节奏。需要别的角度或尺寸时，我直接调用 `tools/` 里的渲染脚本。
