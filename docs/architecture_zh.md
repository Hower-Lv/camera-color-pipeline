# Log 恢复与 LUT 部署管线架构

## 1. 为什么需要总项目

项目以未知 Log 曲线恢复和 `.cube` LUT 部署为主线。静态色彩标定提供 XYZ 目标与空间校正，防止照度不均或目标值错误被误判为 Log/LUT 问题。总项目负责规定阶段契约：上一阶段必须输出什么、下一阶段可以假设什么、哪些误差必须继续传递到最终报告。

## 2. 阶段契约

| 阶段 | 输入 | 输出 | 必须记录的边界 |
|---|---|---|---|
| 测量点策略 | 黑场、受控曝光、局部白场、同位置配对 | 选择性校正后的成对坐标 | 数据类型、空间因子、是否改动横轴 |
| HLG 路径 | 配准的 HLG/Log | HLG 相对线性轴到 Log 码值 | legal/full range、位深、HLG 逆 OETF |
| RAW 路径 | 标定后的 RAW 相对线性值/Log | RAW 相对线性轴到 Log 码值 | 黑电平、线性化、曝光基准、空间策略 |
| 双路径一致性 | 两条 Log 拟合曲线 | 单调共识 tone curve | 共同输入范围、曲线分歧 RMSE |
| 公开模板比较 | 相对线性值、Log 码值、拍摄组 | 统一自由度下的模板排名 | 公式来源、有效域、留出 RMSE、模板等价性 |
| 校准支撑 | 反射率、光源 SPD、线性白场 | XYZ、二维平场、颜色模型 | 光谱范围、FOV、光源、曝光范围 |
| LUT 构建 | 逆 tone、颜色模型、白点 | 标准 `.cube` | 网格尺寸、输出色域、传递函数 |
| 最终验证 | 回读 `.cube`、留出样本、兼容 LUT | DeltaE00、灰轴、质量门槛 | 插值、裁切、输入编码、适用域 |

## 3. 选择性平场契约

总项目不再把“平场”当作对所有测量点统一执行的步骤。黑场保持零输入和实测码值；G40 一类受控曝光点只把 RAW 线性位置因子乘入横轴；RAW/视频局部白场保留其空间梯度；HLG/Log 同位置配对保持原始一一对应。任何一类都不修改实测 Log 纵轴。

```text
black:       (0, measured code) -> unchanged
controlled:  (x, y, f_xy)       -> (x*f_xy, y)
local field: (x_local, y_local)  -> unchanged
paired:      (x_HLG, y_Log)      -> unchanged
```

该策略先于曲线拟合执行，并作为结构化记录写入报告。完整接口见 [`selective_flat_field_policy_zh.md`](selective_flat_field_policy_zh.md)。

## 4. 双路径共识

代码按三个模块组织：

1. `hlg_path.py` 只接收 HLG 与 Log；
2. `raw_path.py` 只接收已经标定到相对场景线性轴的 RAW 与 Log，不接收 HLG；
3. `integration.py` 是实际使用入口，调用前两个模块并形成共识曲线。

HLG 路径使用标准逆 OETF 得到相对场景线性坐标；RAW 路径使用完成黑电平、线性化、曝光归一和选择性空间校正后的独立 RAW 横轴。两条路径分别拟合目标 Log：

```text
y_A(x) = fitted Log from paired HLG and Log
y_B(x) = fitted Log from calibrated RAW and Log
y_consensus(x) = monotonic((y_A(x) + y_B(x)) / 2)
```

主编排器不直接调用任一单路径函数，只调用 `reconstruct_dual_path()`。总项目同时在共同实测域报告 `RMSE(y_A - y_B)`。该值不是普通拟合残差，而是两组独立测量假设之间的一致性指标。一致性不通过时，禁止只凭平均曲线生成“可信” LUT。

## 5. 公开 Log 模板比较

项目将 DJI D-Log、Insta360 I-Log、OPPO O-Log2、ARRI LogC4、Sony S-Log3 和 Panasonic V-Log 放入统一模板注册表。所有模板采用相同的输入尺度、输出增益和可选偏置自由度，并按完整拍摄组留出验证。

模板排名回答的是“哪一种公开函数形状能更好描述当前测量域”，不能回答“相机内部究竟使用了哪家公式”。若两个模板在自由尺度变换后数值等价，报告保留模板间最大差异，不从微小误差差别推导厂商 ISP 结构。

## 6. 空间变换不能写入普通 3D LUT

二维平场是 `F(x, y, channel)`，普通 3D LUT 是 `L(R, G, B)`。二者自变量不同，因此总项目固定执行顺序：

```text
RAW linearization -> geometry check -> 2D flat field -> sampling -> tone and color transform
```

RAW 派生平场只允许在线性域和已标定几何下使用。输出 `.cube` 的注释和报告都明确注明平场属于外部前处理，LUT 训练样本来自平场后的图像，但 LUT 文件本身不含位置校正。

## 7. LUT 对照的有效性边界

同一输入编码和色域定义下的自建 LUT 与官方 LUT 可以进入正式 DeltaE00 排名。友商 LUT 若要求 LogC4、O-Log2 或 I-Log 输入，而源图是 D-Log M，则只保留诊断图，不进入有效色准排名。公平跨厂商比较必须先为每个 LUT 提供其定义要求的输入数据。

## 8. 质量门槛

总状态不是训练误差的别名，而是所有阶段逻辑与指标的合取：

```text
PASS = flat-field residual pass
   AND static CCM pass
   AND HLG path pass
   AND RAW path pass
   AND cross-path agreement pass
   AND final-file DeltaE00 pass
   AND gray-axis monotonicity pass
```

任何一项失败，都应保留产物用于诊断，但整次运行标记为失败。

## 9. 可追溯性

`provenance.json` 对配置和产物写入 SHA-256、文件大小和状态。它解决的是“用于结论的 LUT 是否就是当前展示的 LUT”，而不是替代原始素材归档系统。
