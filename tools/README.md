# NABO DIVE：精简第三轮 v4

本轮按用户更新的 CODEX_PROMPTS“第3轮（按当前原型精简版）”制作，三套皮肤全部保留。旧 swim8、dash_in3、dash4、dash_out3 只把浅色外描边改为深色；四份动作JSON、原24骨骼定义、姿势及源帧alpha轮廓保持。新增 gulp、hit、lowair、out、turn，合计60张新帧；九动作总计114张。**新旧动画均待用户确认，本轮未操作原型或固件，未以文档模板中的“已确认/已接入”代替验收证据。**

## 动作和帧率

| 动作 | 帧数 | fps | 循环 | 行为 |
| --- | --- | --- | --- | --- |
| swim | 8 | 12 | 是 | 原动作，仅改描边颜色。 |
| dash_in | 3 | 12 | 否 | 原动作，仅改描边颜色。 |
| dash | 4 | 12 | 是 | 原动作，仅改描边颜色。 |
| dash_out | 3 | 12 | 否 | 原动作，仅改描边颜色。 |
| gulp | 3 | 12 | 否 | 张口、鼓腮吞咽、回落；events.swallow=2，帧号从1起。 |
| hit | 4 | 12 | 否 | 头肩局部受击、×眼和短距口边喷气泡、恢复；最后导出帧与当前swim首帧精确一致。 |
| lowair | 4 | 16 | 是 | 难受挤眼、鼓腮憋气、小幅急促划水。 |
| out | 6 | 12 | 否 | 最后吐气、闭眼、脸胸转向观众、四肢逐渐松开成为仰漂投影。 |
| turn | 3 | 24 | 否 | 标准姿势→转向中间投影→正面；第3帧人体轮廓和关节左右对称。 |

新版提示词明确给出的 lowair16fps、turn24fps 覆盖 ART_BRIEF 第6节旧的“统一12fps”总述。manifest保留默认fps12，同时每动作均写各自fps、loop、frame_count、skin_frames、events。可选 nearmiss/record 和第4轮海洋素材/界面本轮未做。

## 重建与参数

依赖 Python3、CairoSVG、Pillow、NumPy 与系统Cairo；当前Mac已有依赖。

```sh
# 缺少Python依赖的新环境：
python3 -m pip install cairosvg pillow numpy

# 仓库根目录，使用当前rig直接重导出：
python3 -B game-art/dive/tools/render.py --skin all --anim all --self-check
python3 -B game-art/dive/tools/render.py --skin b --anim lowair
python3 -B game-art/dive/tools/validate_round3.py

# 从保留作者基线完整重建：
python3 -B game-art/dive/tools/revise_motion.py
python3 -B game-art/dive/tools/build_transitions.py
python3 -B game-art/dive/tools/build_expressions.py --qa
python3 -B game-art/dive/tools/build_front_assets.py --replace-generated
python3 -B game-art/dive/tools/build_round3.py
python3 -B game-art/dive/tools/render.py --skin all --anim all --self-check
```

这些作者脚本会覆盖自己生成的当前rig/关键帧；后续有人工修改时应先保留版本。原v1、v2、v3均在history中，分别有116、214、304文件SHA快照；旧交付包也仍在原目录。`build_rig.py` 是最早作者脚本，不作为当前入口。旧 `validate_swim.py` 属于前轮，当前以 `validate_round3.py` 为准。

渲染器支持 `--skin a|b|c|all`、`--anim swim|dash_in|dash|dash_out|gulp|hit|lowair|out|turn|all`、`--angle 50`、`--scale 1`、`--mirror`、`--self-check`。非默认角度/缩放输出至 frames/variants 与对应preview，不覆盖标准版本。--scale围绕胸口改变几何，画布始终256×256；碰到画布边缘会报错。

## 共享骨架、表情和投影

原24骨骼及绑定支点保持，新增 mouth_bubbles（head子节点、支点124,99），默认空槽；旧时间轴缺此通道按0处理。所有皮肤共用姿势、时序、表情和投影。眼/嘴表达映射在 rig.expressions，SVG位于 common/expressions；眼槽包含镜框，替换后不再叠原中性眼。口边气泡仅用于明确要求的hit/out，不是游泳尾迹。新增开心/惊讶表情仅作为可替换资产，并未擅自增加可选动作。

外描边统一深色 #101E34，原部件内部深色线保持；白帽、白衣、白鞋属于固有色，不能把这些白色填充删掉。没有受光边、光晕、持续气泡尾迹或引擎位移/挤压拉伸。色板将原rim项换为深色，仍是A/C19色、B20色及16级alpha。

turn/out使用新绘制的正面矢量部件，仍采用同骨骼父层级及投影支点。rig.front_views包含前伸、放松两套映射。out通过脸胸朝向、肢体放松与投影长度/方向变化表现翻仰；其标准运动朝向保持50°，没有把旧整张PNG旋90°。turn由动作自身的朝向投影50°→70°→90°转为屏幕竖直正面；这与引擎额外±15°倾斜不同。元数据分别记录 front_mix、relaxed_mix、facing_angle、projected_joint_pivots、projected_rotations_degrees 与实际joints_world。

turn第3帧的正面几何、眼镜、帽形与ECG对称；正常可读的“NABO”字样不可能自身镜像，单独以SVG id=nabo-wordmark标记。标准朝向终帧均衡少量Cairo边缘量化差异，alpha严格水平对称；RGB仅该字样及其镜像小mask区域豁免。自定义角度保留真实SVG投影，不强制画布竖轴均衡。

## 输出与接缝

| 内容 | 相对game-art/dive路径 |
| --- | --- |
| 全部源帧、锚点/支点/表情/投影元数据 | frames/{a,b,c}/{动作}/01.png…、metadata.json |
| 各动作三皮肤实际尺寸/4倍GIF | preview/{动作}_compare_actual.gif、_compare_4x.gif |
| 每皮肤预览与透明小帧 | preview/{a,b,c}/{动作}_{actual,4x}.gif、{动作}_actual_frames/ |
| 各动作叠帧和逐帧总览 | preview/{a,b,c}/{动作}_onion.png、_onion_4x.png；preview/{动作}_contact.png、_compare_onion.png |
| 撞击/转身衔接 | preview/{hit,turn}_sequence_{actual,4x}.gif |
| 原完整俯冲流程，现深色描边 | preview/dash_sequence_{actual,4x}.gif |
| 60新源帧实际尺寸检查表 | preview/qa/round3-new-actual-contact.png |
| 接缝静态检查 | preview/qa/hit-seams.png、turn-five-frame-contact.png |
| 技术验收/视觉记录 | preview/qa/round3-validation.json、visual-review.json |

hit流程为swim8→hit4→swim一圈（从S1继续，最后S0），20逻辑帧，12fps；受击第一帧局部冲击是表演，恢复末帧精确S0。任意swim相位即时受击仍需要运行时混合。

turn流程为swim8→T0,T1,T2,mirror(T1),mirror(T0)→mirror swim一圈（从S1继续），21逻辑帧。完整转身只用5个24fps帧，正面只出现一次，约0.208秒。镜像只存在诊断预览，使用已保存实际尺寸RGBA的水平反转，没有交付重复镜像源帧。turn流程单次播放，结束在右下方向，不把右游硬切回左游。两个流程的时间表在 preview/qa/{hit,turn}-sequence.json。

原俯冲仍为swim两圈→in3→dash三圈→out3→swim一圈，共42帧、3.5秒，固定进入/退出相位0。三帧过渡没有解决任意相位切换；后续引擎需混合或相位门控。本轮不改引擎。

## 固定比例与GIF时间

**全部九动作保留上一轮固定缩放0.25779258710765557**，不会新增动作后重新fit或逐帧居中。正式源帧256×256RGBA、胸口128,128；实际尺寸透明画布96×96、胸口48,48。旧四动作50–56px；新gulp/hit约53px、lowair52–54px、out51–55px，turn中间57px/正面58px是同一比例下的视角变化，如实保留。4倍均严格最近邻放大小尺寸栅格。

五背景为 #3FA9D6、#1B5E8C、#0B2A4A、#061528、#04070D。GIF编码固定这些背景的精确RGB索引；角色的多背景alpha合成颜色允许GIF256色量化近似。GIF只有10ms粒度，累计时间用精确分数并half-up到百分之一秒：lowair4帧250ms，turn3帧130ms（精确源时长125ms），混帧率turn流程1540ms（精确37/24秒），hit流程1670ms（精确5/3秒）。PNG/manifest保留原fps。

## 验收状态

程序验收独立检查：114源帧重渲一致、54旧帧仅改深色描边、旧四时间轴/24骨定义保持、27组统一比例、帧率/事件/manifest、胸口、颜色/alpha、循环、hit恢复、turn对称及词标小mask、混帧率流程逐帧像素来源、原设计与历史快照。

已逐帧目视五新动作总览、60帧实际尺寸蓝/黑表、hit前后接缝及完整5帧转身投影，修正out中段前臂压缩/遮挡。吞咽嘴形在实际尺寸很细微；请结合4倍图判断。浏览器此前拒绝本地file://播放，已停止且未绕过；未完成连续浏览器播放视觉验收。机器检查、逐帧检查、连续播放、用户确认分别记录，不互相替代。

本轮只在game-art/dive写入，未覆盖用户更新的ART_BRIEF/CODEX_PROMPTS。第3轮完成后停下，等待用户确认，不自动进入第4轮。
