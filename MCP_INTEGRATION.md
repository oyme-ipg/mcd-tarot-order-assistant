# 🔌 MCP 集成说明 · mcd-tarot-fortune × 麦当劳点餐 MCP

> 一句话：**占卜离线跑，MCP 只在「问实时价」和「真要下单」时出场。**

---

## 1. 定位与原则

| 项 | 说明 |
| --- | --- |
| 依赖类型 | **可选增强**，不是前置依赖 |
| 声明文件 | [`mcp_declaration.json`](mcp_declaration.json)（机器可读） |
| 离线可用 | ✅ 月相本地算、商品来自采集快照，占卜全流程不需要网络 |
| 介入时机 | ① 用户问本地实时价 ② 用户明确要下单 |
| 硬边界 | 绝不自动下单、绝不代付、绝不改 22 张牌的映射 |

**为什么内置快照价而不是每次都查**：抽牌是娱乐行为，每次都拉接口会把仪式感拖成加载动画，也会在用户没同意的情况下消耗点餐权限。快照价 + 脚注免责已经足够；真要掏钱时再去核实时价。

---

## 1.5 配置接入

MCP 提供者名为 `mcd-mcp`（见 `mcp_declaration.json`）。两种接法：

1. **内置连接器**：在连接器管理里启用麦当劳点餐即可，无需手写配置。
2. **手写配置**：参考 [`mcp-config.example.json`](mcp-config.example.json)，把 `mcpServers.mcd-mcp` 合并进 `~/.workbuddy/mcp.json`（不是 `.mcp.json`），然后到连接器管理页对新服务点「信任」启用。

模板里的 `command / args / url / env` 均为**占位示例**，真实值以提供方官方文档为准。

---

## 2. 触发判断（先看这个）

| 用户说了什么 | 走哪条 | 调不调 MCP |
| --- | --- | --- |
| 「开启今日运势」「抽塔罗牌」「算一卦」 | 占卜流程 | ❌ 不调 |
| 「我选 7」「再抽一张」 | 抽牌流程 | ❌ 不调 |
| 「我这附近多少钱」「上海是不是这个价」 | 价格校准 | ✅ 调（只读） |
| 「现在还卖这个吗」 | 价格校准 + 在售校验 | ✅ 调（只读） |
| 「来一份」「我要买」「下单」 | 下单流程 | ✅ 调（最后一步需确认） |
| 「麦乐送」「送到公司」 | 外送下单流程 | ✅ 调 |

---

## 3. 场景 A · 价格校准（只读，最常用）

用户抽到牌后问「我这边多少钱」时使用。

```
① query-nearby-stores
   beType=1（到店自提）或 5（得来速）
   searchType=2, city=<用户城市>, keyword=<地标/商圈>
   → 拿 storeCode（beType=5 时还要拿 beCode）
   → 展示门店列表，让用户选一家

② query-meals
   storeCode=<上一步>, orderType=1, beType=<同上>
   （beType=5 时必传 beCode；beType=1 时不传，传了会报错）
   → 在返回菜单里按 sku 匹配本技能的 item.sku
   → 用该店 currentPrice 覆盖展示价

③ 可选 calculate-price
   items=[{productCode: sku, quantity: 1}]
   → 拿含优惠的实付价（返回单位【分】，展示前 ÷100）
```

**展示要求**：覆盖价格后，把脚注从快照来源换成实时来源——
`💡 实时价取自{storeName}（{storeCode}），查询于 {此刻}。`

若实时价与快照价不同，补一句原因：城市差异 / 渠道差异（自提 vs 外送）/ 时段优惠。**以实时价为准。**

---

## 4. 场景 B · 到店下单（写操作，需确认）

```
① query-nearby-stores   beType=1, searchType=2, city, keyword
② 用户确认门店 → 记下 storeCode
③ query-meals           storeCode, orderType=1, beType=1
④ （可选）query-meal-detail  code=<sku>
   用户问「能不能换/去冰/不要葱」时才调；不要主动展开特调列表
⑤ calculate-price       items=[{productCode: sku, quantity: 1}]
   → 展示：门店 / 商品 / 数量 / 实付金额（÷100）
⑥ 【停下来】等用户明确说「下单 / 确认」
⑦ create-order
```

⚠️ 第 ⑥ 步不可跳过。**占卜是占卜，下单是下单**——用户说「给我算一卦」不构成下单授权。

---

## 5. 场景 C · 麦乐送 / 团餐

与场景 B 的差别只有取门店的方式和 beCode：

| 场景 | beType | orderType | beCode |
| --- | --- | --- | --- |
| 到店自提 | 1 | 1 | 不传（传了报错） |
| 得来速 DT | 5 | 1 | 必传（来自 query-nearby-stores） |
| 麦乐送到家 | 2 | 2 | 必传（来自 delivery-query-stores） |
| 企业团餐 | 6 | 2 | 必传（来自 delivery-query-stores） |

外送：`delivery-query-stores` → 拿 beCode → `query-meals(orderType=2, beType=2, beCode)` → `calculate-price` → 确认 → `create-order`。

---

## 6. 字段映射

| 本技能 | MCP | 备注 |
| --- | --- | --- |
| `item.sku` | `productCode` / 菜单里的商品 `code` | 22 个 SKU 全部来自官方菜单，可直接匹配 |
| `item.price`（元，快照） | `query-meals` 的 `currentPrice` | **同为元**（字符串，如 `"25.5"`）→ 直接覆盖展示，**不要 ÷100** |
| `meta.source_store.storeCode` | `storeCode` | 快照默认 1450713 |
| `meta.source_store.storeName` | `storeName` | 覆盖脚注门店名 |
| — | `originalPrice` | 用于显示「原价 X，现优惠中」 |
| — | `calculate-price` 的 `price` / `productPrice` | **单位为分**（整数，如 `2550`）→ 展示前 ÷100 |

> ⚠️ **单位陷阱（2026-10-23 实测确认）**：`query-meals` 的 `currentPrice` 是**元**，`calculate-price` 的 `price` 是**分**，两者不同。
> 早期版本本表误将 `currentPrice` 标为「分」，照做会把 ¥25.5 的巨无霸显示成 ¥0.255。

---

## 7. 降级与错误处理

| 情况 | 处理 | 话术示例 |
| --- | --- | --- |
| 门店查询失败 / 无结果 | 回退内置门店 1450713 快照价 | 「没查到你附近的店，先按上海这家给你参考」 |
| 菜单拉取失败 | 保留快照价 + 免责脚注 | 「实时价没拉到，价格可能浮动 ±10%」 |
| SKU 在该店匹配不到 | 说明不可售，推荐同价位替代牌 | 「这款你这边暂时点不了，换个价位接近的？」 |
| 商品已下架 | 保持映射不变，如实告知 | 「它退役了，但牌还在」 |
| 实时价 ≠ 快照价 | 以实时价为准并解释差异 | 「你这边贵 1 块，是外送渠道的差价」 |
| 用户未确认就要下单 | 拒绝自动下单 | 「你说一声『下单』我就去建单」 |
| MCP 整体不可用 | 全流程照常跑完占卜 | 不影响任何占卜输出 |

**不要做的事**：编 SKU、编价格、把快照价说成实时价、在未确认门店的情况下下单。

---

## 8. 与 SKILL.md 的分工

- `SKILL.md` —— 面向 Agent 的交互协议（Stage 0-5、话术、边界）。**Stage 5 直接内联了可执行的 MCP 工具名与入参**，Agent 不读本文件也能完成价格校准。
- `mcp_integration.md`（本文件）—— 降级策略、外送/团餐链路、完整错误处理，作为 Stage 5 的扩展参考。
- `mcp_declaration.json` —— 面向工具链的依赖声明（工具清单、权限、fallback）。

> 2026-10-23 修订：此前「SKILL.md 不写接口细节、落地全看本文件」的分工导致**执行链断链**——Agent 跑占卜时不会来读这个文件，MCP 永远不会被调用。现改为在 SKILL.md 的 Stage 5 写死工具名。

---

_更新于 2026-10-23 · 对应 skill v1.0 · MCP provider: mcd-mcp_
