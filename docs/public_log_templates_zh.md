# 公开 Log 模板、统一拟合与声明边界

## 1. 模板范围

项目当前注册六种公开 Log 形状：

| Key | 模板 | 实现依据 |
|---|---|---|
| `dji_d_log` | DJI D-Log | DJI D-Log / D-Gamut 白皮书中的分段常数 |
| `insta360_i_log` | Insta360 I-Log | I-Log 公开传递常数 |
| `oppo_o_log2` | OPPO O-Log2 | O-Log2 公开传递常数 |
| `arri_logc4` | ARRI LogC4 | ARRI LogC4 规范中的正输入 Log 分支 |
| `sony_s_log3` | Sony S-Log3 | Sony S-Log3 技术资料中的反射率输入公式 |
| `panasonic_v_log` | Panasonic V-Log | Panasonic V-Log / V-Gamut 参考手册 |

建议核对的公开来源：

- [DJI D-Log / D-Gamut Whitepaper](https://dl.djicdn.com/downloads/zenmuse_x7/20171010/D-Log_D-Gamut_Whitepaper.pdf)
- [ARRI LogC4](https://www.arri.com/en/learn-help/learn-help-camera-system/image-science/log-c4)
- [Sony S-Log](https://pro.sony/ue_US/technology/s-log)
- [Panasonic V-Log/V-Gamut Reference Manual](https://pro-av.panasonic.net/en/cinema_camera_varicam_eva/support/pdf/VARICAM_V-Log_V-Gamut.pdf)

公式常数属于公开技术事实；厂商商标和产品名称归各自权利人所有。本项目不是任何厂商的官方实现。

## 2. 统一拟合自由度

对每个公开模板 `T_k(x)`，项目拟合：

```text
y_hat = offset + gain * (T_k(scale * x) - T_k(0))
```

默认只拟合正的输入尺度 `scale` 和输出增益 `gain`，并固定 `offset=0`。只有显式使用 `--fit-offset` 时才增加偏置自由度。所有模板采用相同自由度、尺度搜索范围和误差定义，避免某个模板因参数更多而天然占优。

## 3. 按完整拍摄组留出

CSV 提供 `capture_id` 时，程序每次留出一整组拍摄，用其他组重新拟合，再预测被留出的全部样本。最终排名使用聚合后的 leave-group-out RMSE，而不是训练 RMSE。

这种划分防止同一视频或照片中的相邻点同时进入训练与验证，降低把单次曝光、白平衡或局部噪声记忆成 Log 形状的风险。

## 4. 模板等价性

报告在实测线性范围内计算每对拟合曲线的最大绝对差和曲线间 RMSE。若两个公开模板经过输入尺度与输出增益调整后几乎重合，应把它们视为当前数据域内的等价函数族，不能依据极小的残差差异判断相机使用了其中某一家公式。

例如，若实测数据只覆盖正输入对数段，O-Log2 与 LogC4 的正输入主体可能在自由尺度变换后表现为数值等价。LogC4 的负输入延伸未被测量时，不参与可辨识结论。

## 5. 可以与不能得出的结论

可以得出：

- 哪种公开函数形状更能描述当前相对线性坐标与目标 Log 码值；
- 训练误差、按拍摄组留出误差和有效输入范围；
- 多个模板在当前数据域内是否数值等价。

不能得出：

- 厂商内部唯一真实 OETF；
- 传感器电子数或绝对物理曝光；
- RAW、HLG 和 Log 必然共享同一 ISP 前端；
- 在未测量暗部、负输入或高光范围内的模板优劣。
