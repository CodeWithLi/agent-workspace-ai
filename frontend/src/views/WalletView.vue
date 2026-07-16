<template>
  <section class="page narrow-page">
    <div class="page-head">
      <div><h2>Token 钱包</h2><p>AI 员工与多 Agent 工作流用量。</p></div>
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Coin } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api } from '../api/client'
import type { RechargeOrder, Wallet } from '../api/types'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const wallet = ref<Wallet | null>(null)
const packages = [10, 50, 100, 500]
const selectedAmount = ref(50)
const recharging = ref(false)

async function load() {
  const { data } = await api.get<Wallet>('/billing/wallet')
  wallet.value = data
  auth.setTokenBalance(data.balance)
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
