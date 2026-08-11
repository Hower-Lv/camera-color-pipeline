# Log 恢复与 LUT 部署管线架构

## 1. 为什么需要总项目

项目以未知 Log 曲线恢复和 `.cube` LUT 部署为主线。静态色彩标定提供 XYZ 目标与空间校正，防止照度不均或目标值错误被误判为 Log/LUT 问题。总项目负责规定阶段契约：上一阶段必须输出什么、下一阶段可以假设什么、哪些误差必须继续传递到最终报告。

## 2. 阶段契约

| 阶段 | 输入 | 输出 | 必须记录的边界 |
|---|---|---|---|
| Log 恢复 | 配准的 HLG/Log，可选 RAW | 相对线性轴到 Log 码值 | legal/full range、位深、公共前端假设 |
| 双路径一致性 | 两条 Log 拟合曲线 | 单调共识 tone curve | 共同输入范围、曲线分歧 RMSE |
| 校准支撑 | 反射率、光源 SPD、线性白场 | XYZ、二维平场、颜色模型 | 光谱范围、FOV、光源、曝光范围 |
| LUT 构建 | 逆 tone、颜色模型、白点 | 标准 `.cube` | 网格尺寸、输出色域、传递函数 |
| 最终验证 | 回读 `.cube`、留出样本 | DeltaE00、灰轴、质量门槛 | 插值、裁切、适用域 |

## 3. 双路径共识

方法 A 使用 HLG 标准逆 OETF 得到相对场景线性坐标；方法 B 使用 RAW 到逆 HLG RGB 的仿射公共前端。两条路径都拟合目标 Log：

```text
y_A(x) = fitted Log from paired HLG and Log
y_B(x) = fitted Log from RAW, HLG and Log
y_consensus(x) = monotonic((y_A(x) + y_B(x)) / 2)
```

总项目同时报告 `RMSE(y_A - y_B)`。该值不是普通拟合残差，而是两组建模假设之间的一致性指标。一致性不通过时，禁止只凭平均曲线生成“可信” LUT。

## 4. 空间变换不能写入普通 3D LUT

二维平场是 `F(x, y, channel)`，普通 3D LUT 是 `L(R, G, B)`。二者自变量不同，因此总项目固定执行顺序：

```text
RAW linearization -> 2D flat field -> demosaic / sampling -> tone and color transform
```

输出 `.cube` 的注释和报告都明确注明平场属于外部前处理。

## 5. 质量门槛

总状态不是训练误差的别名，而是所有阶段逻辑与指标的合取：

```text
PASS = flat-field residual pass
   AND static CCM pass
   AND paired Log method A pass
   AND paired Log method B pass
   AND cross-method agreement pass
   AND final-file DeltaE00 pass
   AND gray-axis monotonicity pass
```

任何一项失败，都应保留产物用于诊断，但整次运行标记为失败。

## 6. 可追溯性

`provenance.json` 对配置和产物写入 SHA-256、文件大小和状态。它解决的是“用于结论的 LUT 是否就是当前展示的 LUT”，而不是替代原始素材归档系统。
