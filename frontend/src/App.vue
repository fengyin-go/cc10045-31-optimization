<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">实时数据分析与可视化应用平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">支撑实时数据聚合、多维度分析、可视化图表生成和数据应用发布的分析平台</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "报告历史与核数", path: "/report-history" }, { label: "实时聚合器", path: "/realtime_agg" }, { label: "事件追踪器", path: "/event_tracker" }, { label: "仪表盘构建器", path: "/dashboard_builder" }, { label: "查询缓存层", path: "/query_cache" }, { label: "分群引擎", path: "/segment_engine" }, { label: "指标存储", path: "/metric_store" }, { label: "下钻路径", path: "/drill_path" }, { label: "分析告警策略", path: "/alert_policy" }, { label: "数据报告", path: "/data_report" }, { label: "异常归因", path: "/anomaly_analysis" }, { label: "预测模型", path: "/forecast_model" }, { label: "分群对比", path: "/cohort_compare" }, { label: "分析结果导出", path: "/data_export" }, { label: "数据订阅", path: "/data_subscription" }, { label: "查询历史", path: "/query_history" }, { label: "报告快照", path: "/report_snapshot" }, { label: "数据API", path: "/data_api" }, { label: "留存分析", path: "/retention_analysis" }, { label: "漏斗分析器", path: "/funnel_analyzer" }, { label: "多维数据集构建", path: "/cube_builder" }]
</script>
