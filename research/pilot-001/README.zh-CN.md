# 首批 10 个案例：证据是否足够，而非预测能否赚钱

整理日期：2026-09-24。已查阅真实 Polymarket 规则及官方来源。**没有调用 Jev，没有独立人工裁定，没有历史盘口，没有交易收益结果。**

这批是开发用的阅读理解／弃权能力小样本，不是独立测试集。10 题来自 4 个事件组、8 个合约命题、5 份官方材料。相同事件必须放在同一数据分组；不能随机拆分后宣称外部泛化。

## 文件

- [corpus.json](corpus.json)：来源 URL、日期、短原文引文、整理后的事实、规则摘要和案例组合。
- [labels.provisional.json](labels.provisional.json)：候选标签、理由和局限，与模型输入分开保存。
- [当前 V1 范围](../../docs/V1_FIT_CHECK.zh-CN.md)。

## 标签到底表示什么

主标签判断的是：**仅凭提供材料，是否足以确立该合约的 YES／NO 条件？**

- SUFFICIENT_YES：材料已建立 YES 条件，例如合约只要求公告，而正式公告已出现。
- SUFFICIENT_NO：材料已排除所选结果，例如官方已宣布另一个教宗名。
- INSUFFICIENT：未来条件尚未完成、缺少必要信息，或未能证明历史上的不存在。
- AMBIGUOUS：存在多种合理规则解释或证据冲突。本批没有强行添加这种题。

另外保存方向提示 SUPPORTS_YES / SUPPORTS_NO / UNKNOWN，但它是研究者的定性解读，不作为金标准或交易概率。**不充分不等于毫无信息；支持 NO 也不等于已经证明 NO。**

## 10 个案例与候选标签

| ID | 市场与所给材料 | 充分性标签 | 核心陷阱 |
| --- | --- | --- | --- |
| P01 | iPhone 17 在 9 月 9 日前发售；仅提供 9 月 9 日宣布事实 | INSUFFICIENT | 宣布不等于可购买；这是刻意截短对照 |
| P02 | 同一市场；补充 9 月 12 日预售、19 日上市 | INSUFFICIENT，方向支持 NO | 未来安排支持方向，但不是已完成的最终 NO |
| P03 | iPhone 17e 在 3 月 15 日前宣布；3 月 2 日官方公告 | SUFFICIENT_YES | 规则只需宣布，无需等开售 |
| P04 | iPhone 17e 在 2 月 28 日前宣布；同一 3 月 2 日公告 | INSUFFICIENT | 截止后的公告本身不能证明之前绝无公告 |
| P05 | GTA VI 在 2025 年发售；5 月公告改计划至 2026 年 | INSUFFICIENT，方向支持 NO | 延期预期不等于实际年底未发售 |
| P06 | GTA VI 在 2026 年 6 月前发售；5 月公告计划 5 月 26 日 | INSUFFICIENT，方向支持 YES | 计划赶得上不等于已发售 |
| P07 | GTA VI 是否宣布推迟原定 5 月 26 日发售；11 月官方新日期 | SUFFICIENT_YES | 公告本身满足这一合约的条件 |
| P08 | GTA VI 在 2026 年 6 月前实际发售；同一 11 月公告 | INSUFFICIENT，方向支持 NO | 同一证据用于不同规则，充分性不同 |
| P09 | 新教宗名是否 Leo；官方宣布 Leo XIV / Robert Francis Prevost | SUFFICIENT_YES | 识别采用的教宗名 |
| P10 | 新教宗名是否 Francis；同一官方宣布 | SUFFICIENT_NO | 世俗姓名中的 Francis 不是教宗名 |

所有标签为 **Codex 核对来源后提出，尚未独立裁定**。在存在合理分歧时，应修订 rubric／排除题目，而不是默认模型错了。P02、P04、P05、P06、P08 尤其需要注意“支持方向”与“逻辑充分”的区别。

## 原始来源对应

每个链接对应已查看的页面，JSON 中保存可定位的短引文。完整第三方文章没有复制进仓库。

| 题目 | 规则 | 官方材料 |
| --- | --- | --- |
| P01–02 | [iPhone 17 截止 9 月 9 日](https://polymarket.com/event/will-apple-release-iphone-17-by-september-9/will-apple-release-iphone-17-by-september-9) | [Apple 2025-09-09 发布稿](https://www.apple.com/newsroom/2025/09/apple-debuts-iphone-17/) |
| P03–04 | [iPhone 17e 各日期公告市场](https://polymarket.com/event/will-apple-announce-the-iphone-17e-by-february-28) | [Apple 2026-03-02 发布稿](https://www.apple.com/newsroom/2026/03/apple-introduces-iphone-17e/) |
| P05 | [GTA VI 2025 发售](https://polymarket.com/event/gta-vi-released-in-2025) | [Take-Two 2025-05-02 公告](https://www.take2games.com/ir/news/take-two-interactive-software-inc-reiterates-expectations) |
| P06 | [GTA VI 2026 年 6 月前发售](https://polymarket.com/event/gta-vi-released-before-june-2026) | 同一 Take-Two 5 月公告 |
| P07 | [GTA VI 延期公告](https://polymarket.com/event/gta-6-launch-postponed) | [Take-Two 2025-11-06 财报，第 1 页](https://ir.take2games.com/node/31811/pdf) |
| P08 | 同 P06 的实际发售市场 | 同一 Take-Two 11 月公告 |
| P09–10 | [下一任教宗名](https://polymarket.com/event/what-will-be-the-next-popes-papal-name) | [Vatican News 官方公布](https://www.vaticannews.va/en/pope/news/2025-05/habemus-papam.html) |

## 如何使用

在仓库根目录运行（仅标准库，无密钥、无网络）：

```sh
python3 scripts/pilot_dataset.py
python3 scripts/pilot_dataset.py --export reports/pilot-inputs.json
```

导出脚本用字段白名单构建输入，不包含标签、理由、方向提示、历史结算结果或当前价格。导出包含规则与材料的研究者英文摘要，原文短引文与来源另保存在 corpus。**这能测试整理后材料的理解，不能代表模型处理完整原始网页的表现。** 若小样本值得继续，下一轮应增加依法取得的完整相关段落版本，并单独比较摘要与原文表现。

对模型的统一问题：只根据提供材料，判断是否已建立目标 YES/NO 条件；不能使用记忆中的后续事件。输出标签、理由和证据编号。不要求预测概率，更不计算收益。

建议先冻结输入 hash，逐题运行规则／Jev／通用模型，记录实际版本、响应、延迟、token 和费用。规则基线不得写死 case ID、产品名称或答案；它需要抽取事件类型、日期和命名主体。**当前脚本只校验／导出，未实现任何模型调用，也没有伪造模型成绩。**

## 审计局限

1. 原文和规则是现在查到的版本，不是当时归档快照；历史规则是否修订未核实。
2. 来源日期保留到日，没有编造精确发布／接收时刻。不能测量交易延迟。
3. P01 是人为减少上下文的对照，不能把它当真实新闻流样本。
4. P04 的材料在目标截止之后，明确是事后时序对照，绝不是当时可用信号。
5. P06 的市场在公告当天创建，秒级先后未核实，不能宣称那时可以买卖。
6. 10 题只有 4 组；科技发布案例占多数，标签分布不平衡（3 YES、1 NO、6 不足），没有真正冲突／歧义样本。
7. 都是已知历史事件，模型可能记住答案；正确率不能解释为未来预测能力。
8. 当前页面带有结算信息；研究者无法做到盲审。模型输入已剥离这些信息，但标签仍需独立复核。
9. 没有盘口、费用、成交数据，任何交易价值与胜率结论都不成立。
10. 尝试读取的美联储 2025 年声明页面在本次工具中只返回导航，PDF 也未成功取得；未把无法读到的一手正文硬塞入案例集。

## 第一轮实际发现

案例能整理出来，但最难的往往不是分类，而是定义问题。若把“支持 YES”混同“YES 已成立”，会得到过度自信的自动交易信号。简单名字抽取题可能用规则即可；真正复杂的弃权题是否适合 Jev，需要实际运行才能回答。

本批完成的是资料准备与标签草案。没有证明 Jev 比其他方法更好，也没有证明新闻驱动策略可盈利。
