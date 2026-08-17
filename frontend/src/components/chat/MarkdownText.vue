<template>
  <div ref="el" class="md" v-html="html"></div>
</template>

<script setup>
import { computed, onMounted, onUpdated, ref } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({ text: { type: String, default: '' } })
const el = ref(null)
const html = computed(() => renderMarkdown(props.text))

// 为代码块包裹一层并附加"复制"按钮（渲染完成后执行，内容变化时重复挂载）
function attachCopy() {
  if (!el.value) return
  el.value.querySelectorAll('pre').forEach((pre) => {
    if (pre.parentElement?.classList.contains('code-wrap')) return
    const wrap = document.createElement('div')
    wrap.className = 'code-wrap'
    pre.parentNode.insertBefore(wrap, pre)
    wrap.appendChild(pre)
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'copy-btn'
    btn.textContent = '复制'
    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code')?.innerText || ''
      try {
        await navigator.clipboard.writeText(code)
        btn.textContent = '已复制'
        setTimeout(() => { btn.textContent = '复制' }, 1500)
      } catch { /* 剪贴板不可用时忽略 */ }
    })
    wrap.appendChild(btn)
  })
}
onMounted(attachCopy)
onUpdated(attachCopy)
</script>

<style scoped>
.md :deep(pre) { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow: auto; font-size: 13px; line-height: 1.6; }
.md :deep(p) { margin: 4px 0; line-height: 1.7; word-break: break-word; }
.md :deep(ul), .md :deep(ol) { padding-left: 20px; margin: 4px 0; }
.md :deep(code) { background: #f0f2f5; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
.md :deep(pre code) { background: transparent; padding: 0; }
.md :deep(a) { color: var(--el-color-primary); }
.md :deep(blockquote) { border-left: 3px solid #e0e0e0; margin: 6px 0; padding-left: 10px; color: #888; }
.md :deep(table) { border-collapse: collapse; margin: 6px 0; }
.md :deep(td), .md :deep(th) { border: 1px solid #ddd; padding: 4px 8px; }
.code-wrap { position: relative; }
.copy-btn { position: absolute; top: 6px; right: 6px; font-size: 12px; padding: 2px 8px; border: 1px solid #d0d7de; border-radius: 4px; background: #fff; cursor: pointer; opacity: 0; transition: opacity 0.2s; }
.code-wrap:hover .copy-btn { opacity: 1; }
</style>
