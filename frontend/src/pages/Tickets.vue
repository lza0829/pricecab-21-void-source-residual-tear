<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const skus = ref([])
const tickets = ref([])
const policy = ref(null)
const msg = ref('')
const err = ref('')
const form = reactive({
  title: '',
  effective_at: '2026-11-16T10:00:00Z',
  note: '',
  sku_code: '',
  new_price: '',
})
const lines = ref([])

// 作废表单：一次只对一张单展开，原因必填
const voidForm = reactive({ ticket_id: null, ticket_no: '', reason: '' })
const voiding = ref(false)

const voidableStatuses = computed(() => new Set(['scheduled', 'applied']))

async function refresh() {
  skus.value = await api.skus()
  tickets.value = await api.tickets()
  policy.value = await api.voidPolicy()
  if (!form.sku_code && skus.value.length) form.sku_code = skus.value[0].sku_code
}

function addLine() {
  if (!form.sku_code || form.new_price === '') {
    err.value = '请选择商品并填写新价'
    return
  }
  lines.value.push({ sku_code: form.sku_code, new_price: Number(form.new_price) })
  form.new_price = ''
  err.value = ''
}

function removeLine(i) {
  lines.value.splice(i, 1)
}

async function submit() {
  msg.value = ''
  err.value = ''
  try {
    const t = await api.createTicket({
      title: form.title,
      effective_at: form.effective_at,
      note: form.note || null,
      lines: lines.value,
    })
    msg.value = `已创建 ${t.ticket_no}`
    form.title = ''
    form.note = ''
    lines.value = []
    await refresh()
  } catch (e) {
    err.value = e.message
  }
}

function openVoid(t) {
  voidForm.ticket_id = t.id
  voidForm.ticket_no = t.ticket_no
  voidForm.reason = ''
  err.value = ''
}

function cancelVoid() {
  voidForm.ticket_id = null
  voidForm.ticket_no = ''
  voidForm.reason = ''
}

async function confirmVoid() {
  msg.value = ''
  err.value = ''
  const reason = voidForm.reason.trim()
  if (!reason) {
    err.value = '作废原因必填，需留痕'
    return
  }
  voiding.value = true
  try {
    const r = await api.voidTicket(voidForm.ticket_id, reason)
    msg.value =
      r.status === 'voided' && r.rolled_back_lines
        ? `已作废 ${voidForm.ticket_no}，并按价格历史回退 ${r.rolled_back_lines} 行价签（历史只读留痕）`
        : `已作废 ${voidForm.ticket_no}（未生效单，无价签回退）`
    cancelVoid()
    await refresh()
  } catch (e) {
    err.value = e.message
  } finally {
    voiding.value = false
  }
}

function tagClass(status) {
  if (status === 'applied') return 'ok'
  if (status === 'voided') return 'voided'
  return 'warn'
}

onMounted(() => refresh().catch((e) => (err.value = e.message)))
</script>

<template>
  <section class="hero">
    <h1>改价单</h1>
    <p>为商品预约新价与生效时刻。未到业务钟前不会写入现行价签；误建单可作废，已应用单按全局唯一命运策略处理。</p>
  </section>

  <div v-if="policy" class="panel" style="border-left-color: var(--danger)">
    <h2>已应用单作废策略（全局唯一，互斥）</h2>
    <p class="msg" style="color: var(--ink); margin: 0">
      <strong>{{ policy.label }}</strong>
    </p>
    <p class="msg" style="margin: 6px 0 0">
      作废时按价格历史回退该单写入的价签，来源单标作废，历史只追加只读审计、不删除任何历史行，应用批次原计数不变。
    </p>
  </div>

  <div class="panel">
    <h2>新建改价单</h2>
    <div class="row">
      <div class="field"><label>标题</label><input v-model="form.title" placeholder="例如：午间茶饮促销售价" /></div>
      <div class="field"><label>生效时刻 (UTC)</label><input v-model="form.effective_at" /></div>
      <div class="field" style="flex:1"><label>备注</label><input v-model="form.note" /></div>
    </div>
    <div class="row">
      <div class="field">
        <label>商品</label>
        <select v-model="form.sku_code">
          <option v-for="s in skus" :key="s.sku_code" :value="s.sku_code">
            {{ s.sku_code }} · {{ s.title }}（现价 {{ s.current_price }}）
          </option>
        </select>
      </div>
      <div class="field"><label>新价</label><input v-model="form.new_price" type="number" step="0.01" /></div>
      <button class="btn ghost" type="button" @click="addLine">加入明细</button>
    </div>
    <table v-if="lines.length">
      <thead><tr><th>SKU</th><th>新价</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(l, i) in lines" :key="i">
          <td>{{ l.sku_code }}</td>
          <td>{{ l.new_price }}</td>
          <td><button class="btn ghost" type="button" @click="removeLine(i)">移除</button></td>
        </tr>
      </tbody>
    </table>
    <div class="row" style="margin-top:12px">
      <button class="btn" type="button" @click="submit">提交改价单</button>
    </div>
    <p v-if="msg" class="msg ok">{{ msg }}</p>
    <p v-if="err" class="msg err">{{ err }}</p>
  </div>

  <div class="panel">
    <h2>改价单列表</h2>
    <table>
      <thead>
        <tr>
          <th>单号</th><th>标题</th><th>生效时刻</th><th>行数</th><th>状态</th>
          <th>作废次数</th><th>已应用批次</th><th>作废原因 / 时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="t in tickets" :key="t.id">
          <tr>
            <td>{{ t.ticket_no }}</td>
            <td>{{ t.title }}</td>
            <td>{{ t.effective_at }}</td>
            <td>{{ t.line_count }}</td>
            <td><span class="tag" :class="tagClass(t.status)">{{ t.status }}</span></td>
            <td>{{ t.void_count || 0 }}</td>
            <td>{{ t.apply_batch_id || '—' }}</td>
            <td>
              <template v-if="t.status === 'voided'">
                <div>{{ t.void_reason }}</div>
                <div class="msg" style="font-size:0.75rem">{{ t.voided_at }}</div>
              </template>
              <span v-else class="msg">—</span>
            </td>
            <td>
              <button
                v-if="voidableStatuses.has(t.status)"
                class="btn danger"
                type="button"
                :disabled="voidForm.ticket_id === t.id && voiding"
                @click="openVoid(t)"
              >
                作废
              </button>
              <span v-else class="msg">—</span>
            </td>
          </tr>
          <tr v-if="voidForm.ticket_id === t.id">
            <td colspan="9" style="background: color-mix(in srgb, var(--danger) 8%, transparent)">
              <div class="row" style="margin:0; align-items:flex-end">
                <div class="field" style="flex:1">
                  <label>作废 {{ t.ticket_no }} 的原因（必填，将留痕）</label>
                  <input
                    v-model="voidForm.reason"
                    placeholder="例如：误建 / 价格录错，回退以历史为准"
                    @keyup.enter="confirmVoid"
                  />
                </div>
                <button class="btn danger" type="button" :disabled="voiding" @click="confirmVoid">
                  {{ voiding ? '作废中…' : '确认作废' }}
                </button>
                <button class="btn ghost" type="button" :disabled="voiding" @click="cancelVoid">取消</button>
              </div>
              <p v-if="t.status === 'applied'" class="msg" style="margin:8px 0 0">
                该单已应用：确认后将按价格历史回退其写入的价签，历史与应用批次原计数保留不动。
              </p>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
