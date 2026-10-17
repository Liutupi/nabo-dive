# 深潜 DIVE · AI Passport 独立版固件

只有深潜一个游戏的 FoloToy AI Passport 固件：开机直接进入标题页，不需要配网、激活或联网。发布在 [AI Passport 玩法社区](https://ai-passport.folotoy.cn/plays/)。

带小智语音和其他小游戏的版本见 [ai-passport-nabo-xiaozhi-dive](https://github.com/Liutupi/ai-passport-nabo-xiaozhi-dive)，两者的深潜代码相同。

## 操作

| 按键 | 作用 |
| --- | --- |
| OK | 标题页开始；游戏中每按一次换方向；结束页再来一局 |
| 下键（按住） | 俯冲：速度翻倍、耗氧 1.5 倍 |
| 上键（单击） | 暂停 / 继续；结束页回到标题 |
| 上键（长按） | 切换静音，设置会保存 |

最深纪录保存在 NVS，断电不丢。5 分钟没有操作自动深睡，按任意键唤醒（设备会重新启动到标题页）。

## 结构

| 路径 | 说明 |
| --- | --- |
| `main/main.c` | 启动、按键映射、16 kHz 音频输出、静音和自动深睡 |
| `main/nabo_dive*.c/.h` | 深潜游戏本体：模型、动画、渲染、配乐音效、精灵图数据，与小智版逐字节相同 |
| `main/nabo_*_font_*.c` | 游戏用到的 LVGL 位图字体（思源黑体、Archivo Black、Space Mono），许可证同目录 |
| `main/muse_menu.h` | 游戏按键接口用到的枚举 |
| `components/bsp/` | FoloToy 官方 [ai-passport](https://github.com/folotoy/ai-passport) 的板级支持包，原样复制（MIT，见 `LICENSE.FoloToy`） |
| `tools/verify_firmware.py` | 改自官方脚本：检查合并镜像的分区布局 |

游戏直接驱动 ST7789（硬件垂直滚动），不经过 LVGL 刷屏；LVGL 只用来提供字体数据结构。

## 构建

需要 ESP-IDF 5.5.3，目标芯片 ESP32-C3（8 MB Flash，无 PSRAM）。依赖组件（LVGL 9.5、esp_lvgl_port 2.9.0、button 4.2、esp_codec_dev 1.6.2）由组件管理器按 `components/bsp/idf_component.yml` 自动下载。

```bash
cd firmware
idf.py set-target esp32c3
idf.py build
idf.py merge-bin -o nabo-dive-merged.bin
python3 tools/verify_firmware.py build
```

`build/nabo-dive-merged.bin` 是可从 `0x0` 刷写的完整固件，可用 [AI Passport 刷机工具](https://ai-passport.folotoy.cn/tools/web-flasher/) 的"本地固件刷机"安装。

## 验证记录

v1.0.0（2026-10-17）：

- 构建：PASS，应用 654,672 字节，合并镜像 720,208 字节，分区布局检查通过
- 深潜宿主测试（小智版仓库 `test_dive.py`，8 项）：PASS，游戏源码未改动
- 实机：作者用网页刷机工具从 `0x0` 安装后试玩正常

## 许可

`main/main.c`、`tools/` 与构建配置：MIT。`components/bsp/`：FoloToy，MIT。字体：OFL 1.1。`main/nabo_dive_sprites.c` 中的 NABO 形象与美术不随 MIT 授权，见仓库根目录 [NOTICE.md](../NOTICE.md)。
