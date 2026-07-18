# shuangxian — 双弦投资系统 v2.2

每日收盘后自动扫描，输出共振/低吸信号，推送至微信 + IMA知识库。

## 更新日志
- 20260629: server酱3和PushPlus双推送
- 20260703: 资金沉淀率，三层共振分，主力军捕获器
- 20260718: GitHub Actions → IMA知识库自动归档

## IMA知识库推送

扫描完成后自动将报告上传至 **「双弦」** 知识库：
- 📁 每日报告 → 按日归档
- 📁 月度股池 → 按月滚动

### 配置
需在 GitHub Secrets 添加：
- `IMA_OPENAPI_CLIENTID` — IMA API 客户端ID
- `IMA_OPENAPI_APIKEY` — IMA API 密钥

> 获取方式：访问 https://ima.qq.com/agent-interface
