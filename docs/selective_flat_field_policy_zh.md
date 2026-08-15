# Log 标定点与 LUT 的选择性平场策略

## 1. 核心原则

平场不是对所有数据统一执行的预处理。是否校正取决于空间亮度变化在该组数据中是误差，还是被测信号本身。

| 数据类型 | 横轴 `x` | 纵轴 `y` | 原因 |
|---|---|---|---|
| `black_anchor` | 保留零输入 | 保留实测黑码值 | 零光输入不存在可校正的乘性照明场 |
| `controlled_exposure` | 乘 RAW 线性空间因子 | 保留原始 Log 码值 | 目标是修正该色块位置对应的真实线性曝光 |
| `local_white_gradient` | 保留原始局部线性差 | 保留同位置 Log 码值 | 白场梯度就是用于估计局部 OETF 的密集输入变化 |
| `paired_transfer` | 保留 HLG 反算值 | 保留同位置 Log 码值 | 同一像素位置已经共享场景照明，额外平场会重复修改输入 |

`controlled_exposure` 的计算形式为：

```text
x_corrected = x_spectral_or_photometric * spatial_factor_raw_linear
y_corrected = y_log_measured
```

空间因子只允许作用于横轴。策略实现拒绝在其他三类样本上提供非 1 的空间因子，并拒绝非零的黑场横轴。

## 2. CSV 契约

`compare-templates` 接受以下可选列：

```text
linear,encoded,capture_id,measurement_kind,spatial_factor
0.0,64.0,black,black_anchor,1.0
0.10,320.0,g40_01,controlled_exposure,0.86
0.18,410.0,local_01,local_white_gradient,1.0
0.32,520.0,pair_01,paired_transfer,1.0
```

若省略 `measurement_kind`，样本按 `paired_transfer` 处理；若省略 `spatial_factor`，其值为 `1.0`。输出 JSON 会记录每类样本数量、执行动作和空间因子范围。

若 `encoded` 使用原生码值且黑场不为 0，模板比较应增加 `--fit-offset`；若输入已经减去黑码值并归一化，可保持默认的零偏置拟合。

## 3. LUT 构建中的位置

标定点策略和图像空间校正是两件不同的事：

```text
线性图像
  -> 校验拍摄几何 ID
  -> 应用二维平场 F(x,y,channel)
  -> 色卡取样
  -> Log 编码/逆曲线与颜色模型
  -> 生成 3D LUT L(R,G,B)
```

当前整合管线只允许对线性图像应用 RAW 派生的乘性平场。焦距、裁切、分辨率、相机姿态或布光发生变化时，必须更换 `geometry_id` 和对应模型；几何不匹配会直接报错。

普通 `.cube` 的输入只有 `(R,G,B)`，无法表达像素位置 `(x,y)`。因此二维平场始终是 LUT 外部的上游操作，不能烘焙进 3D LUT，也不能把“使用平场后训练出的 LUT”表述为“LUT 内含平场”。

## 4. 有效性边界

- RAW 与视频必须经过 FOV、畸变和位置配准后，RAW 空间因子才可用于视频位置。
- RAW 与视频若使用不同裁切、数字增稳、局部 tone mapping 或镜头校正，空间因子的可迁移性必须单独验证。
- 同位置 HLG/Log 配对不需要平场，不等于 HLG 与 Log 必然共享完全相同的 ISP 前端。
- 选择性策略提高物理可解释性，不保证在有限样本上取得最低经验拟合误差；必须同时报告留出误差。
- 仓库只提供策略、接口和合成验证，不包含设备实测系数、素材或项目结论。
