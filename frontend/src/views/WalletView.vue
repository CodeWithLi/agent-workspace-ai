<template>
  <section class="page narrow-page">
    <div class="page-head">
      <div><h1>Token 钱包</h1><p>AI 员工与多 Agent 工作流用量。</p></div>
      <el-tag type="warning">模拟充值</el-tag>
    </div>

    <div class="wallet-balance">
      <div><span>可用 AI Token</span><strong>{{ wallet?.balance ?? auth.user?.ai_token_balance ?? 0 }}</strong></div>
      <dl><div><dt>单次聊天</dt><dd>{{ wallet?.chat_cost ?? '-' }}</dd></div><div><dt>多 Agent 工作流</dt><dd>{{ wallet?.workflow_cost ?? '-' }}</dd></div></dl>
    </div>

    <section class="section-band">
      <h3>模拟充值</h3>
      <div class="recharge-options">
        <button v-for="amount in packages" :key="amount" :class="{ active: selectedAmount === amount }" @click="selectedAmount = amount">
          <strong>{{ amount }} 元</strong><span>{{ amount * (wallet?.recharge_tokens_per_yuan || 100) }} Token</span>
        </button>
      </div>
      <el-button type="primary" :icon="Coin" :loading="recharging" @click="recharge">确认模拟充值</el-button>
    </section>

    <section class="section-band">
      <h3>Token 流水</h3>
      <el-table :data="wallet?.transactions || []" class="data-table">
        <el-table-column label="时间" min-width="180"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column prop="description" label="说明" min-width="220" />
        <el-table-column prop="transaction_type" label="类型" width="120" />
        <el-table-column label="变动" width="120"><template #default="{ row }"><strong :class="row.amount > 0 ? 'token-in' : 'token-out'">{{ row.amount > 0 ? '+' : '' }}{{ row.amount }}</strong></template></el-table-column>
        <el-table-column prop="balance_after" label="余额" width="120" />
      </el-table>
    </section>

    <section class="section-band">
      <div class="section-head-inline"><h3>模型实际用量</h3><span>{{ usageTokenTotal.toLocaleString() }} tokens · {{ formatCost(usageCostMicros) }}</span></div>
      <el-table :data="usage" class="data-table">
        <el-table-column label="时间" min-width="170"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column prop="operation" label="操作" width="100" />
        <el-table-column prop="model" label="模型" min-width="150" />
        <el-table-column prop="total_tokens" label="Tokens" width="110" />
        <el-table-column label="耗时" width="100"><template #default="{ row }">{{ row.latency_ms }} ms</template></el-table-column>
        <el-table-column label="估算成本" width="120"><template #default="{ row }">{{ formatCost(row.estimated_cost_micros) }}</template></el-table-column>
      </el-table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Coin } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import type { LLMUsage, RechargeOrder, Wallet } from '../api/types'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const wallet = ref<Wallet | null>(null)
const packages = [10, 50, 100, 500]
const selectedAmount = ref(50)
const recharging = ref(false)
const usage = ref<LLMUsage[]>([])
const usageTokenTotal = computed(() => usage.value.reduce((total, item) => total + item.total_tokens, 0))
const usageCostMicros = computed(() => usage.value.reduce((total, item) => total + item.estimated_cost_micros, 0))

function formatCost(micros: number) {
  return (micros / 1_000_000).toFixed(6)
}

async function load() {
  const [walletResponse, usageResponse] = await Promise.all([
    api.get<Wallet>('/billing/wallet'),
    api.get<LLMUsage[]>('/billing/usage', { params: { limit: 50 } })
  ])
  wallet.value = walletResponse.data
  usage.value = usageResponse.data
  auth.setTokenBalance(walletResponse.data.balance)
}

async function recharge() {
  recharging.value = true
  try {
    const { data } = await api.post<RechargeOrder>('/billing/recharge', {
      amount_yuan: selectedAmount.value,
      request_id: crypto.randomUUID()
    })
    ElMessage.success(`已到账 ${data.token_amount} AI Token`)
    await load()
  } finally {
    recharging.value = false
  }
}

onMounted(load)
</script>
