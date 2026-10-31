# Realnin 管理端商城前端 Backlog

当前范围：商品、商城类目、配送、城市。Owner: RealninX。16张本地故事草案，没有自动创建远程Issue，也没有完成业务实现。完整结构见 [backlog.json](backlog.json)。

| ID | 用户故事 | 依赖 | 状态 |
|---|---|---|---|
| RN-SETUP-01 | 确认范围、接入公共框架与可替换 Mock 数据层 | — | Todo |
| RN-CITY-01 | 查看和新增中英双语城市，默认快递 | RN-SETUP-01 | Todo |
| RN-CITY-02 | 安全切换城市配送方式并提示联动结果 | RN-CITY-01 | Todo |
| RN-CAT-01 | 读取、添加中英双语商城类目 | RN-SETUP-01 | Todo |
| RN-CAT-02 | 逻辑删除商城类目并保护商品引用 | RN-CAT-01 | Todo |
| RN-PROD-01 | 查看商品列表与服务端库存状态 | RN-SETUP-01, RN-CAT-01 | Todo |
| RN-PROD-02 | 新增和编辑双语商品及合法价格、类目 | RN-PROD-01, RN-CAT-01 | Todo |
| RN-PROD-03 | 选择、预览和排序商品主图与详情图 | RN-PROD-02 | Todo |
| RN-PROD-04 | 修改账面库存与入库，处理预留和并发冲突 | RN-PROD-02 | Todo |
| RN-PROD-05 | 维护商品上下架和改价的展示边界 | RN-PROD-02 | Todo |
| RN-PROD-06 | 维护基础点赞并保留用户真实点赞 | RN-PROD-02 | Todo |
| RN-DEL-01 | 维护统一线下配送费 | RN-SETUP-01 | Todo |
| RN-DEL-02 | 维护快递邮费与包邮门槛 | RN-DEL-01 | Todo |
| RN-DEL-03 | 按线下城市配置可送区 | RN-CITY-02 | Todo |
| RN-DEL-04 | 维护每日共用送达时段 | RN-DEL-03 | Todo |
| RN-VERIFY-01 | 完成四模块前端回归并交付接口契约 | RN-PROD-03, RN-PROD-04, RN-PROD-05, RN-PROD-06, RN-CAT-02, RN-DEL-02, RN-DEL-04 | Todo |

建议先确认公共框架/认证/契约，再做城市与商城类目、商品、配送，最后前端回归。每个功能故事独立分支和PR。Frontend Done与真实Integration Done分开，未验证的真实环境不得标完成。
