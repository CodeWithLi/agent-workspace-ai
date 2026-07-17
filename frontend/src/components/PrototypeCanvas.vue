<template>
  <div
    class="prototype-runtime"
    :class="[`runtime-${screen.layout}`, `runtime-${deviceMode}`]"
    :style="themeStyle"
  >
    <header v-if="screen.layout !== 'auth'" class="runtime-header">
      <div class="runtime-brand"><span>{{ spec.product_name.slice(0, 1) }}</span><strong>{{ spec.product_name }}</strong></div>
      <nav aria-label="原型导航">
        <button
          v-for="item in visibleNavigation"
          :key="item.id"
          :class="{ active: item.id === screen.id }"
          @click="$emit('navigate', item.id)"
        >{{ item.name }}</button>
      </nav>
      <div class="runtime-user">{{ deviceMode === 'mobile' ? '我' : '我的账号' }}</div>
    </header>

    <main class="runtime-content">
      <div v-if="toastMessage" class="runtime-toast" role="status">{{ toastMessage }}</div>
      <section
        v-for="section in screen.sections"
        :key="section.id"
        class="runtime-section"
        :class="`section-${section.width}`"
      >
        <header v-if="section.title || section.description" class="section-copy">
          <h1 v-if="section.title">{{ section.title }}</h1>
          <p v-if="section.description">{{ section.description }}</p>
        </header>

        <div class="runtime-components">
          <template v-for="component in section.components" :key="component.id">
            <h2 v-if="component.type === 'heading'" class="component-heading">{{ component.text }}</h2>
            <p v-else-if="component.type === 'text'" class="component-text">{{ component.text }}</p>
            <hr v-else-if="component.type === 'divider'" class="component-divider" />

            <label v-else-if="component.type === 'input'" class="runtime-field">
              <span>{{ component.label }}<b v-if="component.required"> *</b></span>
              <input
                v-model="inputValues[component.id]"
                :placeholder="component.placeholder"
                :disabled="component.disabled"
                :type="component.id.includes('password') ? 'password' : 'text'"
              />
            </label>

            <label v-else-if="component.type === 'textarea'" class="runtime-field">
              <span>{{ component.label }}<b v-if="component.required"> *</b></span>
              <textarea v-model="inputValues[component.id]" :placeholder="component.placeholder" :disabled="component.disabled" rows="4" />
            </label>

            <label v-else-if="component.type === 'select'" class="runtime-field">
              <span>{{ component.label }}<b v-if="component.required"> *</b></span>
              <select v-model="inputValues[component.id]" :disabled="component.disabled">
                <option value="" disabled>请选择</option>
                <option v-for="option in component.options" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>

            <button
              v-else-if="component.type === 'button'"
              class="runtime-button"
              :class="`button-${component.variant}`"
              :disabled="component.disabled"
              @click="handleAction(component)"
            >{{ component.label || component.text }}</button>

            <button
              v-else-if="component.type === 'link'"
              class="runtime-link"
              :disabled="component.disabled"
              @click="handleAction(component)"
            >{{ component.label || component.text }}</button>

            <div v-else-if="component.type === 'stepper'" class="runtime-stepper" :aria-label="`当前第 ${stepActive(component)} 步`">
              <div v-for="(step, index) in component.steps" :key="step" :class="{ current: index + 1 === stepActive(component), done: index + 1 < stepActive(component) }">
                <span>{{ index + 1 }}</span><strong>{{ step }}</strong>
              </div>
            </div>

            <div v-else-if="component.type === 'stats'" class="runtime-stats">
              <article v-for="item in component.items" :key="String(item.label)">
                <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
              </article>
            </div>

            <div v-else-if="component.type === 'callout'" class="runtime-callout">
              <strong v-if="component.label">{{ component.label }}</strong>
              <p>{{ component.text }}</p>
            </div>

            <div v-else-if="component.type === 'table'" class="runtime-table-wrap">
              <table>
                <thead><tr><th v-for="column in component.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="(item, rowIndex) in component.items" :key="rowIndex">
                    <td v-for="column in component.columns" :key="column">{{ item[column] ?? '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-else-if="component.type === 'tabs'" class="runtime-tabs" role="tablist">
              <button
                v-for="option in component.options"
                :key="option.value"
                role="tab"
                :aria-selected="tabValue(component) === option.value"
                :class="{ active: tabValue(component) === option.value }"
                @click="tabStates[component.id] = option.value"
              >{{ option.label }}</button>
            </div>

            <div v-else-if="component.type === 'list'" class="runtime-list">
              <article v-for="(item, index) in component.items" :key="index">
                <span class="list-marker">{{ index + 1 }}</span>
                <div><strong>{{ item.title }}</strong><small>{{ item.meta }}</small></div>
              </article>
            </div>
          </template>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { PrototypeComponentSpec, PrototypeScreen, PrototypeSpecification } from '../api/types'

const props = defineProps<{
  spec: PrototypeSpecification
  screenId: string
  deviceMode: 'desktop' | 'mobile'
}>()

const emit = defineEmits<{
  navigate: [screenId: string]
  interaction: [message: string]
}>()

const inputValues = reactive<Record<string, string>>({})
const stepStates = reactive<Record<string, number>>({})
const tabStates = reactive<Record<string, string>>({})
const toastMessage = ref('')
let toastTimer = 0

const screen = computed<PrototypeScreen>(() =>
  props.spec.screens.find((item) => item.id === props.screenId) || props.spec.screens[0]
)
const visibleNavigation = computed(() => props.spec.screens.slice(0, props.deviceMode === 'mobile' ? 2 : 4))
const themeStyle = computed(() => ({
  '--prototype-primary': props.spec.theme.primary,
  '--prototype-accent': props.spec.theme.accent,
  '--prototype-background': props.spec.theme.background,
  '--prototype-surface': props.spec.theme.surface,
  '--prototype-foreground': props.spec.theme.foreground,
  '--prototype-radius': props.spec.theme.radius === 'compact' ? '4px' : props.spec.theme.radius === 'rounded' ? '12px' : '8px'
}))

function showToast(message: string) {
  window.clearTimeout(toastTimer)
  toastMessage.value = message
  emit('interaction', message)
  toastTimer = window.setTimeout(() => { toastMessage.value = '' }, 2200)
}

function stepActive(component: PrototypeComponentSpec) {
  return stepStates[component.id] || component.active_step || 1
}

function tabValue(component: PrototypeComponentSpec) {
  return tabStates[component.id] || component.options[0]?.value || ''
}

async function handleAction(component: PrototypeComponentSpec) {
  const action = component.action
  if (!action) return
  if (action.type === 'navigate' && action.target) {
    if (action.message) showToast(action.message)
    emit('navigate', action.target)
    return
  }
  if (action.type === 'back') {
    window.history.back()
    return
  }
  if (action.type === 'advance_step') {
    const stepper = screen.value.sections.flatMap((section) => section.components).find((item) => item.type === 'stepper')
    if (stepper) {
      const current = stepActive(stepper)
      stepStates[stepper.id] = Math.min(stepper.steps.length, current + 1)
    }
    showToast(action.message || '已进入下一步')
    return
  }
  if (action.type === 'copy') {
    try {
      await navigator.clipboard.writeText(component.value || component.text)
    } catch {
      // Clipboard access can be unavailable in embedded previews; feedback still confirms the intended interaction.
    }
    showToast(action.message || '内容已复制')
    return
  }
  showToast(action.message || (action.type === 'submit' ? '提交成功' : '操作已完成'))
}

watch(() => [props.screenId, props.spec], () => {
  toastMessage.value = ''
})
</script>

<style scoped>
.prototype-runtime {
  --prototype-primary: #1f2937;
  --prototype-accent: #2563eb;
  --prototype-background: #f7f8fa;
  --prototype-surface: #fff;
  --prototype-foreground: #111827;
  --prototype-radius: 8px;
  position: relative;
  width: 100%;
  min-height: 680px;
  overflow: hidden;
  border-radius: var(--prototype-radius);
  background: var(--prototype-background);
  color: var(--prototype-foreground);
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}

.runtime-header {
  display: grid;
  min-height: 60px;
  grid-template-columns: minmax(150px, 1fr) auto minmax(100px, 1fr);
  align-items: center;
  gap: 20px;
  padding: 0 28px;
  border-bottom: 1px solid #e5e7eb;
  background: var(--prototype-surface);
}

.runtime-brand { display: flex; align-items: center; gap: 9px; }
.runtime-brand > span { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; background: var(--prototype-primary); color: #fff; font-weight: 800; }
.runtime-brand strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-header nav { display: flex; gap: 4px; }
.runtime-header nav button,
.runtime-user { min-height: 36px; padding: 0 12px; border: 0; border-radius: 6px; background: transparent; color: #64748b; font: inherit; cursor: pointer; }
.runtime-header nav button:hover,
.runtime-header nav button.active { background: #f1f5f9; color: var(--prototype-foreground); }
.runtime-user { justify-self: end; display: grid; place-items: center; background: #f1f5f9; cursor: default; }

.runtime-content { display: grid; gap: 22px; padding: 34px; }
.runtime-auth .runtime-content { min-height: 680px; place-content: center; }
.runtime-section { width: 100%; margin: 0 auto; padding: 26px; border: 1px solid #e2e8f0; border-radius: var(--prototype-radius); background: var(--prototype-surface); }
.runtime-auth .runtime-section { box-shadow: 0 14px 36px rgba(15, 23, 42, 0.08); }
.section-narrow { max-width: 500px; }
.section-medium { max-width: 720px; }
.section-wide { max-width: 1040px; }
.section-full { max-width: none; }
.section-copy { margin-bottom: 22px; }
.section-copy h1 { margin: 0 0 7px; font-size: 22px; line-height: 1.3; }
.section-copy p { margin: 0; color: #64748b; line-height: 1.55; }
.runtime-components { display: grid; gap: 16px; }
.component-heading { margin: 0; font-size: 20px; line-height: 1.35; }
.component-text { margin: 0; color: #475569; line-height: 1.6; }
.component-divider { width: 100%; margin: 2px 0; border: 0; border-top: 1px solid #e2e8f0; }

.runtime-field { display: grid; gap: 7px; color: #334155; font-size: 13px; font-weight: 700; }
.runtime-field b { color: #b91c1c; }
.runtime-field input,
.runtime-field textarea,
.runtime-field select { width: 100%; min-height: 44px; padding: 10px 13px; border: 1px solid #cbd5e1; border-radius: 7px; background: #fff; color: #0f172a; font: inherit; font-weight: 400; outline: none; }
.runtime-field textarea { resize: vertical; }
.runtime-field input:focus,
.runtime-field textarea:focus,
.runtime-field select:focus { border-color: var(--prototype-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--prototype-accent) 14%, transparent); }

.runtime-button,
.runtime-link { min-height: 44px; border-radius: 7px; font: inherit; font-weight: 700; cursor: pointer; }
.runtime-button { padding: 0 18px; border: 1px solid #cbd5e1; background: #fff; color: #334155; }
.runtime-button:hover { border-color: #94a3b8; background: #f8fafc; }
.button-primary { border-color: var(--prototype-primary); background: var(--prototype-primary); color: #fff; }
.button-primary:hover { border-color: color-mix(in srgb, var(--prototype-primary) 85%, #000); background: color-mix(in srgb, var(--prototype-primary) 85%, #000); }
.button-success { border-color: #15803d; background: #15803d; color: #fff; }
.button-warning { border-color: #b45309; background: #b45309; color: #fff; }
.button-danger { border-color: #b91c1c; background: #b91c1c; color: #fff; }
.runtime-link { justify-self: center; padding: 0 8px; border: 0; background: transparent; color: var(--prototype-accent); text-decoration: underline; text-underline-offset: 3px; }
.runtime-button:disabled,
.runtime-link:disabled { opacity: 0.5; cursor: not-allowed; }

.runtime-stepper { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin-bottom: 8px; }
.runtime-stepper > div { position: relative; display: grid; justify-items: center; gap: 7px; color: #94a3b8; font-size: 12px; text-align: center; }
.runtime-stepper > div::after { position: absolute; top: 15px; left: calc(50% + 22px); width: calc(100% - 44px); height: 1px; background: #dbe3ee; content: ""; }
.runtime-stepper > div:last-child::after { display: none; }
.runtime-stepper span { z-index: 1; display: grid; width: 30px; height: 30px; place-items: center; border-radius: 50%; background: #e8eef6; color: #64748b; }
.runtime-stepper .current,
.runtime-stepper .done { color: var(--prototype-primary); }
.runtime-stepper .current span,
.runtime-stepper .done span { background: var(--prototype-primary); color: #fff; }

.runtime-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.runtime-stats article { display: grid; gap: 5px; padding: 16px; border: 1px solid #e2e8f0; border-radius: 7px; background: #f8fafc; }
.runtime-stats span { color: #64748b; font-size: 12px; }
.runtime-stats strong { font-size: 22px; font-variant-numeric: tabular-nums; }
.runtime-callout { padding: 14px 16px; border-left: 3px solid var(--prototype-accent); border-radius: 4px; background: color-mix(in srgb, var(--prototype-accent) 7%, #fff); }
.runtime-callout strong { display: block; margin-bottom: 5px; font-size: 12px; }
.runtime-callout p { margin: 0; overflow-wrap: anywhere; color: #475569; line-height: 1.55; }

.runtime-table-wrap { max-width: 100%; overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 7px; }
.runtime-table-wrap table { width: 100%; min-width: 520px; border-collapse: collapse; text-align: left; }
.runtime-table-wrap th,
.runtime-table-wrap td { padding: 12px 14px; border-bottom: 1px solid #e2e8f0; font-size: 12px; white-space: nowrap; }
.runtime-table-wrap th { background: #f8fafc; color: #475569; font-weight: 700; }
.runtime-table-wrap tbody tr:last-child td { border-bottom: 0; }
.runtime-tabs { display: flex; gap: 4px; padding: 4px; border-radius: 7px; background: #f1f5f9; }
.runtime-tabs button { min-height: 36px; flex: 1; padding: 0 12px; border: 0; border-radius: 5px; background: transparent; color: #64748b; font: inherit; cursor: pointer; }
.runtime-tabs button.active { background: #fff; color: #0f172a; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.1); }
.runtime-list { display: grid; gap: 10px; }
.runtime-list article { display: flex; align-items: center; gap: 12px; padding: 13px; border: 1px solid #e2e8f0; border-radius: 7px; }
.list-marker { display: grid; width: 28px; height: 28px; flex: 0 0 auto; place-items: center; border-radius: 50%; background: #eff6ff; color: #1d4ed8; font-size: 12px; font-weight: 800; }
.runtime-list article > div { display: grid; gap: 3px; }
.runtime-list small { color: #64748b; }
.runtime-toast { position: absolute; z-index: 5; top: 18px; left: 50%; padding: 10px 16px; border-radius: 7px; background: #0f172a; color: #fff; font-size: 13px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.2); transform: translateX(-50%); }

.runtime-mobile { min-height: 720px; }
.runtime-mobile .runtime-header { grid-template-columns: 1fr auto; padding: 0 14px; }
.runtime-mobile .runtime-header nav { display: none; }
.runtime-mobile .runtime-content { padding: 18px 14px 28px; }
.runtime-mobile.runtime-auth .runtime-content { min-height: 720px; align-content: center; }
.runtime-mobile .runtime-section { padding: 20px 16px; }
.runtime-mobile .runtime-stats { grid-template-columns: 1fr; }
.runtime-mobile .runtime-stepper strong { font-size: 10px; }
.runtime-mobile .runtime-table-wrap table { min-width: 620px; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
</style>
