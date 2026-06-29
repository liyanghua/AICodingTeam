# Claim Pack Seed

## C1: 高搜索量不是充分条件

- Claim: 高搜索量只能说明需求存在，不说明存在可进入机会。
- Evidence needed: search_volume, competition_index, paid_competition, competitor density.
- Failure mode: 只按搜索量排序会把红海词误判为机会。

## C2: 价格带空档必须结合供给能力

- Claim: 价格带空档只有在消费者需求真实且供应链可支持时才构成机会。
- Evidence needed: competitor price distribution, review pain points, supply_chain_constraints.
- Failure mode: 只看价格空白会产生不可执行机会。

## C3: 评论痛点是高价值机会证据

- Claim: 重复出现且未被竞品解决的评论痛点，是机会卡的重要证据。
- Evidence needed: review snippets, pain point frequency, competitor selling points.
- Failure mode: 单条评论不能支撑强判断。

## C4: 内容热度与货架成交需要分开判断

- Claim: 内容平台热度高但货架成交弱，更可能是内容机会或主图表达机会。
- Evidence needed: content engagement, keyword search, sales estimates.
- Failure mode: 把内容热点直接当商品机会。

## Update Rules

- 被业务专家否定的 claim 必须记录 failed_claim。
- 被真实经营结果验证的 claim 可以提升权重。
- 数据不足导致误判时，优先更新 DataSpec，而不是直接改 Prompt。
